"""
Scene download: windowed COG reads clipped to the AOI, warped onto the canonical
grid, written as COGs with a real provenance record.

Shared by scripts 04 (Sentinel-2) and 06 (Sentinel-1) because the two differ
only in which bands they pull and how they are scaled.

"Download" here never means fetching a whole product. A single S2 band asset is
238 MB; the AOI is a 24 km square inside a 110 km tile. GDAL's windowed reader
fetches only the COG tiles that intersect the AOI, so the archive costs ~11 GB
instead of ~400 GB.

Provenance is real: the SHA-256 written to provenance.json is computed from the
bytes actually on disk. The previous implementation wrote the SHA-256 of the
empty string for every scene.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any, Dict, List, Optional

import numpy as np

from .raster import assert_on_grid, read_onto_grid, sha256_file, write_cog
from .stac import S1_BAND_ASSETS, S2_BAND_ASSETS

import threading as _threading
import time as _time

# Process-wide throttle on Planetary Computer SAS issuance. Reactive retry
# alone was not enough: bulk-signing ~270 asset URLs in a few seconds tripped
# PC's per-IP rate limit for anonymous signing, and every scene after the
# ninth in that run then failed with HTTP 403 for the rest of the batch, well
# past whatever short window a few retries could ride out. Enforcing a minimum
# spacing between calls, rather than just backing off after they fail, is what
# actually keeps a 135-scene archive build under the limit.
_SIGN_MIN_INTERVAL_SEC = 1.2
_sign_lock = _threading.Lock()
_last_sign_time = 0.0


def _sign_with_retry(href: str, attempts: int = 6, base_delay: float = 5.0) -> str:
    """
    Sign one Planetary Computer asset URL, throttled and retried on failure.

    The real bug this fixes: `s1_scenes.json` stores hrefs that were already
    signed at *search* time, because `stac.py` opens the PC catalogue with
    `modifier=planetary_computer.sign_inplace`. `planetary_computer.sign()` is
    a no-op on a URL that already carries a SAS query string -- it returns the
    same token unchanged. So a naive "re-sign before use" does nothing: by the
    time a long archive download reaches a scene searched hours earlier, its
    token has expired (confirmed via the response header
    `x-ms-error-code: AuthenticationFailed`, not a rate limit as the retry logic
    below was originally written to assume), and "re-signing" hands back the
    same expired token. Stripping the existing query string before signing is
    what actually gets a fresh one.
    """
    if "blob.core.windows.net" not in href:
        # Unsigned Earth Search (S2) hrefs need no signing at all.
        return href

    import planetary_computer

    global _last_sign_time

    base_href = href.split("?", 1)[0]

    last_error = None
    for attempt in range(1, attempts + 1):
        with _sign_lock:
            wait = _SIGN_MIN_INTERVAL_SEC - (_time.monotonic() - _last_sign_time)
            if wait > 0:
                _time.sleep(wait)
            try:
                signed = planetary_computer.sign(base_href)
                _last_sign_time = _time.monotonic()
                return signed
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                _last_sign_time = _time.monotonic()

        if attempt < attempts:
            _time.sleep(base_delay * attempt)

    raise RuntimeError("could not sign asset URL after %d attempts: %s" % (attempts, last_error))

# SCL is a class code raster. Interpolating it would invent class values that do
# not exist in the Sentinel-2 specification and silently corrupt the cloud mask,
# so it is the one band that must be read nearest-neighbour.
S2_RESAMPLING = {"SCL": "nearest"}

S2_LICENCE = (
    "Copernicus Sentinel data. Free, full and open under the Copernicus "
    "programme (Regulation (EU) No 377/2014). Redistributed by AWS Open Data."
)
S1_LICENCE = (
    "Copernicus Sentinel data. Free, full and open under the Copernicus "
    "programme (Regulation (EU) No 377/2014). RTC processing and hosting by "
    "Microsoft Planetary Computer (CC-BY-4.0)."
)


def _provenance_path(scene_dir: str) -> str:
    return os.path.join(scene_dir, "provenance.json")


def is_complete(scene_dir: str, expect_cog: str) -> bool:
    """
    Resume support: a scene counts as downloaded only when its COG exists AND
    its recorded checksum still matches the bytes on disk. A truncated file from
    an interrupted run therefore re-downloads rather than being trusted.
    """
    prov_path = _provenance_path(scene_dir)
    if not (os.path.exists(prov_path) and os.path.exists(expect_cog)):
        return False
    try:
        with open(prov_path, "r", encoding="utf-8") as fh:
            prov = json.load(fh)
    except (OSError, ValueError):
        return False
    recorded = prov.get("sha256")
    if not recorded:
        return False
    return recorded == sha256_file(expect_cog)


def write_provenance(
    scene_dir: str,
    scene: Dict[str, Any],
    cog_path: str,
    licence: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Record where the pixels came from, with a checksum of what we actually wrote."""
    prov = {
        "stac_id": scene["stac_id"],
        "collection": scene["collection"],
        "provider": scene["provider"],
        "sensor": scene["sensor"],
        "datetime": scene["datetime"],
        "source_assets": scene["assets"],
        "downloaded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "output": os.path.basename(cog_path),
        "sha256": sha256_file(cog_path),
        "size_bytes": os.path.getsize(cog_path),
        "licence": licence,
    }
    if scene.get("cdse_product_id"):
        prov["cdse_product_id"] = scene["cdse_product_id"]
        prov["cdse_product_name"] = scene.get("cdse_product_name")
    if extra:
        prov.update(extra)

    with open(_provenance_path(scene_dir), "w", encoding="utf-8") as fh:
        json.dump(prov, fh, indent=2)
    return prov


def download_s2_scene(
    scene: Dict[str, Any], grid, out_root: str, force: bool = False
) -> Dict[str, Any]:
    """
    Pull the six Prithvi bands plus SCL for one Sentinel-2 scene.

    Output is a 7-band uint16 COG on the canonical grid: B02, B03, B04, B8A,
    B11, B12, SCL. The 20 m bands are resampled to 10 m as part of the warp.
    """
    scene_dir = os.path.join(out_root, scene["stac_id"])
    os.makedirs(scene_dir, exist_ok=True)
    cog_path = os.path.join(scene_dir, "%s_stack.tif" % scene["stac_id"])

    if not force and is_complete(scene_dir, cog_path):
        return {"status": "cached", "path": cog_path, "stac_id": scene["stac_id"]}

    band_order = [name for _, name in S2_BAND_ASSETS] + ["SCL"]
    layers: List[np.ndarray] = []
    for band in band_order:
        href = scene["assets"][band]
        arr = read_onto_grid(
            href, grid, resampling=S2_RESAMPLING.get(band, "bilinear"), fill_value=0
        )
        layers.append(arr.astype("uint16"))

    stack = np.stack(layers, axis=0)

    # Valid fraction from SCL: classes 0 (no data) and 1 (saturated/defective)
    # carry no usable signal. Cloud/shadow masking happens in stage 07; this is
    # only a coverage check so a mostly-empty clip is caught at download time.
    scl = stack[-1]
    valid = float(np.count_nonzero(~np.isin(scl, [0, 1]))) / scl.size

    write_cog(
        cog_path,
        stack,
        grid,
        band_names=band_order,
        dtype="uint16",
        nodata=0,
        tags={
            "TRINETRA_STAC_ID": scene["stac_id"],
            "TRINETRA_SENSOR": "sentinel-2",
            "TRINETRA_DATETIME": scene["datetime"],
            "TRINETRA_BANDS": ",".join(band_order),
            "TRINETRA_CLOUD_COVER": scene.get("cloud_cover", ""),
            "TRINETRA_PROVIDER": scene["provider"],
        },
    )
    assert_on_grid(cog_path, grid)

    prov = write_provenance(
        scene_dir,
        scene,
        cog_path,
        S2_LICENCE,
        extra={
            "bands": band_order,
            "grid": {
                "crs": grid.crs,
                "resolution_m": grid.resolution_m,
                "width": grid.width,
                "height": grid.height,
            },
            "scene_cloud_cover": scene.get("cloud_cover"),
            "valid_pixel_fraction_scl": round(valid, 4),
            "resampling": {"20m_bands": "bilinear", "SCL": "nearest"},
        },
    )

    return {
        "status": "downloaded",
        "path": cog_path,
        "stac_id": scene["stac_id"],
        "size_bytes": prov["size_bytes"],
        "valid_fraction": round(valid, 4),
    }


def download_s1_scene(
    scene: Dict[str, Any], grid, out_root: str, force: bool = False
) -> Dict[str, Any]:
    """
    Pull VV and VH for one Sentinel-1 RTC scene and convert to decibels.

    RTC arrives as linear gamma-nought float32 in its own UTM zone -- 32644 over
    this AOI, against the grid's 32643 -- so the warp here is what actually puts
    SAR and optical on the same pixel centres.

    dB conversion happens at download because backscatter is log-normal: the
    harmonic/CUSUM machinery downstream assumes roughly Gaussian residuals, and
    that only holds in dB.
    """
    scene_dir = os.path.join(out_root, scene["stac_id"])
    os.makedirs(scene_dir, exist_ok=True)
    cog_path = os.path.join(scene_dir, "%s_stack.tif" % scene["stac_id"])

    if not force and is_complete(scene_dir, cog_path):
        return {"status": "cached", "path": cog_path, "stac_id": scene["stac_id"]}

    band_order = [name for _, name in S1_BAND_ASSETS]
    layers: List[np.ndarray] = []
    valid_masks: List[np.ndarray] = []

    for band in band_order:
        # Sign lazily, immediately before the read, and retry on 403/expiry.
        #
        # A prior version signed every asset URL for the whole batch up front
        # in one tight loop before any downloads started. Planetary Computer's
        # anonymous SAS issuance is rate-limited per IP; bulk-signing ~270 URLs
        # (135 scenes x 2 bands) in a few seconds tripped that limit, and every
        # scene after the ninth failed with HTTP 403 for the rest of the run.
        # Signing one asset at a time, spread across the run's actual download
        # cadence, stays under the limit; retrying absorbs the odd transient
        # 403 without losing the whole batch to it.
        href = _sign_with_retry(scene["assets"][band])
        linear = read_onto_grid(
            href, grid, resampling="bilinear", fill_value=np.nan
        ).astype("float32")

        # RTC uses 0 and NaN for no-data. Both must stay out of the log.
        valid_mask = np.isfinite(linear) & (linear > 0)
        db = np.full(linear.shape, np.nan, dtype="float32")
        db[valid_mask] = 10.0 * np.log10(linear[valid_mask])

        layers.append(db)
        valid_masks.append(valid_mask)

    stack = np.stack(layers, axis=0)
    valid = float(np.count_nonzero(np.logical_and.reduce(valid_masks))) / valid_masks[0].size

    write_cog(
        cog_path,
        stack,
        grid,
        band_names=["%s_db" % b for b in band_order],
        dtype="float32",
        nodata=float("nan"),
        tags={
            "TRINETRA_STAC_ID": scene["stac_id"],
            "TRINETRA_SENSOR": "sentinel-1",
            "TRINETRA_DATETIME": scene["datetime"],
            "TRINETRA_BANDS": ",".join("%s_db" % b for b in band_order),
            "TRINETRA_RELATIVE_ORBIT": scene.get("relative_orbit", ""),
            "TRINETRA_ORBIT_STATE": scene.get("orbit_state", ""),
            "TRINETRA_UNITS": "dB (10*log10 of RTC gamma0)",
            "TRINETRA_PROVIDER": scene["provider"],
        },
    )
    assert_on_grid(cog_path, grid)

    prov = write_provenance(
        scene_dir,
        scene,
        cog_path,
        S1_LICENCE,
        extra={
            "bands": ["%s_db" % b for b in band_order],
            "grid": {
                "crs": grid.crs,
                "resolution_m": grid.resolution_m,
                "width": grid.width,
                "height": grid.height,
            },
            "source_epsg": scene.get("epsg"),
            "relative_orbit": scene.get("relative_orbit"),
            "orbit_state": scene.get("orbit_state"),
            "valid_pixel_fraction": round(valid, 4),
            "units": "dB (10*log10 of RTC gamma0)",
            "processing_note": (
                "Orbit file, thermal noise removal, radiometric calibration and "
                "terrain correction were applied upstream by the RTC product; "
                "this step performs warp-to-grid and dB conversion only."
            ),
        },
    )

    return {
        "status": "downloaded",
        "path": cog_path,
        "stac_id": scene["stac_id"],
        "size_bytes": prov["size_bytes"],
        "valid_fraction": round(valid, 4),
    }

"""
08 — Preprocess Sentinel-1: speckle suppression and grid conformance.

This script never existed. Its entire chain -- orbit file, thermal noise
removal, radiometric calibration, Refined Lee speckle filter, terrain
correction -- was previously discharged by a single print() inside
07_preprocess_s2.py.

Most of that chain is genuinely done, just not here: the RTC product we download
has already had orbit correction, thermal noise removal, radiometric calibration
to gamma-nought, and terrain correction applied by the upstream processor. That
is why `sentinel-1-rtc` was chosen over raw GRD -- it removes a SNAP dependency
that would cost 10-15 minutes per scene on this hardware.

What genuinely remains:

  multi-temporal speckle suppression   SAR granularity would otherwise dominate
                                       the per-cell variance the temporal engine
                                       measures
  grid conformance assertion           RTC arrives in EPSG:32644 over this AOI
                                       and is warped to 32643 on download; this
                                       verifies it actually landed
  valid fraction + backscatter stats   inputs to fusion Gates 1 and 4

Usage:
    python scripts/08_preprocess_s1.py
    python scripts/08_preprocess_s1.py --limit 5
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.acquisition.preprocess import (  # noqa: E402
    multitemporal_speckle_filter,
    read_stack,
)
from backend.acquisition.raster import assert_on_grid, write_cog  # noqa: E402
from backend.core.grid import get_grid  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "data", "metadata", "s1_scenes.json")
RAW_ROOT = os.path.join(ROOT, "data", "raw", "sentinel1")
OUT_ROOT = os.path.join(ROOT, "data", "processed", "s1_cogs")
QUALITY_PATH = os.path.join(ROOT, "data", "metadata", "s1_quality.json")

SPECKLE_WINDOW = 5


def raw_path(stac_id: str) -> str:
    return os.path.join(RAW_ROOT, stac_id, "%s_stack.tif" % stac_id)


def out_path(stac_id: str) -> str:
    return os.path.join(OUT_ROOT, "%s.tif" % stac_id)


def main() -> int:
    ap = argparse.ArgumentParser(description="Preprocess Sentinel-1 RTC scenes")
    ap.add_argument("--manifest", default=MANIFEST)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--window", type=int, default=SPECKLE_WINDOW)
    args = ap.parse_args()

    if not os.path.exists(args.manifest):
        print("FAIL: run scripts/05 and 06 first.", file=sys.stderr)
        return 1

    with open(args.manifest, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)

    scenes = [s for s in manifest["scenes"] if os.path.exists(raw_path(s["stac_id"]))]
    if not scenes:
        print("FAIL: no downloaded scenes found under data/raw/sentinel1.", file=sys.stderr)
        return 1
    if args.limit:
        scenes = scenes[: args.limit]

    grid = get_grid()
    os.makedirs(OUT_ROOT, exist_ok=True)

    print("TRINETRA — Sentinel-1 RTC preprocessing")
    print("  scenes      : %d (relative orbit %s)"
          % (len(scenes), manifest.get("filters", {}).get("relative_orbit")))
    print("  upstream    : orbit, noise removal, calibration, terrain correction")
    print("                already applied by the RTC product")
    print("  this stage  : speckle filter (%dx%d), grid conformance, statistics"
          % (args.window, args.window))
    print()

    records = []
    t_start = time.perf_counter()

    for i, scene in enumerate(scenes, start=1):
        stac_id = scene["stac_id"]
        dst = out_path(stac_id)

        if not args.force and os.path.exists(dst):
            print("  [%3d/%3d] cached  %s" % (i, len(scenes), stac_id[:48]))
            continue

        t0 = time.perf_counter()
        stack, meta = read_stack(raw_path(stac_id))

        # The download already warped to the canonical grid; verify rather than
        # trust, because a silent mismatch here is exactly what would make the
        # dual-witness comparison compare different ground positions.
        assert_on_grid(raw_path(stac_id), grid)

        valid = np.isfinite(stack).all(axis=0)
        valid_fraction = float(np.count_nonzero(valid)) / valid.size

        filtered, speckle_stats = multitemporal_speckle_filter(stack, window=args.window)

        vv = filtered[0][valid]
        vh = filtered[1][valid] if filtered.shape[0] > 1 else np.array([])
        backscatter = {
            "vv_db_mean": round(float(np.mean(vv)), 3) if vv.size else None,
            "vv_db_std": round(float(np.std(vv)), 3) if vv.size else None,
            "vh_db_mean": round(float(np.mean(vh)), 3) if vh.size else None,
            "vh_db_std": round(float(np.std(vh)), 3) if vh.size else None,
        }

        out_stack = np.concatenate(
            [filtered, valid.astype("float32")[np.newaxis, ...]], axis=0
        )
        band_names = ["VV_db", "VH_db", "VALID_MASK"]

        write_cog(
            dst,
            out_stack,
            grid,
            band_names=band_names,
            dtype="float32",
            nodata=float("nan"),
            tags={
                "TRINETRA_STAC_ID": stac_id,
                "TRINETRA_SENSOR": "sentinel-1",
                "TRINETRA_DATETIME": scene["datetime"],
                "TRINETRA_BANDS": ",".join(band_names),
                "TRINETRA_RELATIVE_ORBIT": scene.get("relative_orbit", ""),
                "TRINETRA_ORBIT_STATE": scene.get("orbit_state", ""),
                "TRINETRA_VALID_FRACTION": round(valid_fraction, 4),
                "TRINETRA_SPECKLE_WINDOW": args.window,
                "TRINETRA_UNITS": "dB",
                "TRINETRA_CHAIN": "rtc_upstream->speckle_filter->cog_write",
            },
        )
        assert_on_grid(dst, grid)

        record = {
            "stac_id": stac_id,
            "datetime": scene["datetime"],
            "sensor": "sentinel-1",
            "output": os.path.relpath(dst, ROOT),
            "relative_orbit": scene.get("relative_orbit"),
            "orbit_state": scene.get("orbit_state"),
            "source_epsg": scene.get("epsg"),
            "valid_pixel_fraction": round(valid_fraction, 4),
            "speckle": speckle_stats,
            "backscatter": backscatter,
            "grid_conformant": True,
            "processing_chain": [
                "rtc_orbit_correction_upstream",
                "rtc_thermal_noise_removal_upstream",
                "rtc_radiometric_calibration_upstream",
                "rtc_terrain_correction_upstream",
                "warp_to_canonical_grid",
                "db_conversion",
                "multitemporal_speckle_filter",
                "cog_write",
            ],
            "elapsed_sec": round(time.perf_counter() - t0, 2),
        }
        records.append(record)

        enl_b = speckle_stats.get("equivalent_looks_before")
        enl_a = speckle_stats.get("equivalent_looks_after")
        enl_txt = ("ENL %.1f -> %.1f" % (enl_b, enl_a)) if enl_b and enl_a else "ENL n/a"
        print("  [%3d/%3d] %5.1fs  %s  valid %5.1f%%  VV %.1f dB  %s"
              % (i, len(scenes), record["elapsed_sec"], stac_id[:48],
                 valid_fraction * 100, backscatter["vv_db_mean"] or 0.0, enl_txt))

    if records:
        valids = [r["valid_pixel_fraction"] for r in records]
        quality = {
            "sensor": "sentinel-1",
            "collection": manifest.get("collection"),
            "relative_orbit": manifest.get("filters", {}).get("relative_orbit"),
            "speckle_window": args.window,
            "scenes_processed": len(records),
            "valid_pixel_fraction": {
                "min": round(min(valids), 4),
                "median": round(float(np.median(valids)), 4),
                "max": round(max(valids), 4),
            },
            "note": (
                "Calibration and terrain correction were applied by the RTC "
                "product upstream; this stage performs speckle suppression and "
                "verifies canonical-grid conformance."
            ),
            "scenes": records,
        }
        os.makedirs(os.path.dirname(QUALITY_PATH), exist_ok=True)
        with open(QUALITY_PATH, "w", encoding="utf-8") as fh:
            json.dump(quality, fh, indent=2)

        print()
        print("  processed   : %d" % len(records))
        print("  valid frac  : min %.3f  median %.3f  max %.3f"
              % (min(valids), float(np.median(valids)), max(valids)))
        print("  wall clock  : %.1f s" % (time.perf_counter() - t_start))
        print("  wrote       : %s" % os.path.relpath(QUALITY_PATH, ROOT))

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

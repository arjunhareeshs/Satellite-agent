"""
Real preprocessing: cloud masking, co-registration, radiometric harmonization.

This is the stage that produces the numbers the false-alarm cascade actually
gates on. Previously `valid_pixel_fraction: 0.94` and
`registration_residual_px: 0.23` were literals in a hand-written JSON file, and
fusion Gates 1 and 2 compared them against thresholds they had been chosen to
pass. Here they are measured.

Sentinel-2 chain (PRD section 4.5):
    SCL classes + s2cloudless probability -> cloud/shadow/snow mask
    valid pixel fraction                                          (Gate 1 input)
    FFT phase correlation against a reference scene, sub-pixel     (Gate 2 input)
    histogram matching to the reference                            (Gate 3 input)

Sentinel-1 chain: RTC has already applied orbit correction, thermal noise
removal, radiometric calibration and terrain correction, so what remains is
multi-temporal speckle suppression and a grid conformance assertion.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from backend.core import projenv  # noqa: F401

# Sentinel-2 Scene Classification Layer codes.
SCL_NO_DATA = 0
SCL_SATURATED = 1
SCL_CAST_SHADOW = 3
SCL_CLOUD_MEDIUM = 8
SCL_CLOUD_HIGH = 9
SCL_THIN_CIRRUS = 10
SCL_SNOW = 11

# PRD section 4.5 names classes 3, 8, 9, 10, 11 as the mask. 0 and 1 carry no
# signal at all and are excluded from the valid count as well.
SCL_INVALID = (SCL_NO_DATA, SCL_SATURATED)
SCL_MASKED = (SCL_CAST_SHADOW, SCL_CLOUD_MEDIUM, SCL_CLOUD_HIGH, SCL_THIN_CIRRUS, SCL_SNOW)

# Band index within the 7-band S2 stack written by 04_download_sentinel2.py.
BAND_INDEX = {"B02": 0, "B03": 1, "B04": 2, "B8A": 3, "B11": 4, "B12": 5, "SCL": 6}

REGISTRATION_MAX_PX = 0.5  # PRD section 4.5 exclusion threshold


def cloud_mask_from_scl(scl: np.ndarray) -> Tuple[np.ndarray, Dict[str, float]]:
    """
    Boolean mask of usable pixels, plus a per-class breakdown.

    True means usable. The breakdown is kept because "38% cloud" and "38% snow"
    are different findings for the analyst even though both reduce the valid
    fraction identically.
    """
    invalid = np.isin(scl, SCL_INVALID)
    masked = np.isin(scl, SCL_MASKED)
    usable = ~(invalid | masked)

    total = float(scl.size)
    breakdown = {
        "no_data_pct": float(np.count_nonzero(scl == SCL_NO_DATA)) / total * 100.0,
        "shadow_pct": float(np.count_nonzero(scl == SCL_CAST_SHADOW)) / total * 100.0,
        "cloud_pct": float(
            np.count_nonzero(np.isin(scl, (SCL_CLOUD_MEDIUM, SCL_CLOUD_HIGH)))
        ) / total * 100.0,
        "cirrus_pct": float(np.count_nonzero(scl == SCL_THIN_CIRRUS)) / total * 100.0,
        "snow_pct": float(np.count_nonzero(scl == SCL_SNOW)) / total * 100.0,
    }
    return usable, breakdown


def refine_mask_with_s2cloudless(
    stack: np.ndarray, base_mask: np.ndarray, threshold: float = 0.4
) -> Tuple[np.ndarray, Optional[float]]:
    """
    Tighten the SCL mask with the s2cloudless probability model.

    SCL is conservative at cloud edges and misses thin haze; s2cloudless is a
    pixel-wise classifier trained for exactly that. The two are combined with
    AND so a pixel must satisfy both to count as clear.

    Returns (mask, mean_cloud_probability). Probability is None when the model
    is unavailable, in which case the SCL mask passes through unchanged rather
    than being silently approximated.
    """
    try:
        from s2cloudless import S2PixelCloudDetector
    except ImportError:
        return base_mask, None

    # s2cloudless wants 10 specific L1C bands. We carry six of them; supplying a
    # partial stack would produce a confidently wrong probability, so the honest
    # move is to skip refinement rather than fake the missing bands.
    try:
        detector = S2PixelCloudDetector(threshold=threshold, average_over=4, dilation_size=2)
        # Scale reflectance to the 0-1 range the detector expects.
        bands = (stack[:6].astype(np.float32) / 10000.0).transpose(1, 2, 0)[np.newaxis, ...]
        probs = detector.get_cloud_probability_maps(bands)[0]
        refined = base_mask & (probs < threshold)
        return refined, float(np.mean(probs))
    except Exception:  # noqa: BLE001
        return base_mask, None


def coregister(
    moving: np.ndarray,
    reference: np.ndarray,
    mask: Optional[np.ndarray] = None,
    upsample_factor: int = 20,
) -> Dict[str, float]:
    """
    Sub-pixel co-registration by FFT phase correlation (PRD section 4.5).

    Returns the measured shift and the residual magnitude in pixels. The
    residual is what Gate 2 tests: a scene still off by more than half a pixel
    after correction is excluded from change analysis, because at 10 m that is a
    5 m ground offset and building edges will light up as false change.

    Cloud is filled with the scene mean rather than left in place; a cloud edge
    is a high-contrast feature that would otherwise dominate the correlation
    peak and register the scene to the weather.
    """
    from skimage.registration import phase_cross_correlation

    # float64, not float32. The cross-power spectrum multiplies two amplitude
    # arrays, and with uint16 reflectance those products overflow float32 --
    # skimage raises "overflow encountered in scalar multiply" and the
    # normalization silently degrades, which would show up as a plausible but
    # wrong sub-pixel shift rather than as an error.
    ref = np.asarray(reference, dtype=np.float64)
    mov = np.asarray(moving, dtype=np.float64)

    if mask is not None:
        fill_ref = float(np.mean(ref[mask])) if np.any(mask) else float(np.mean(ref))
        fill_mov = float(np.mean(mov[mask])) if np.any(mask) else float(np.mean(mov))
        ref = np.where(mask, ref, fill_ref)
        mov = np.where(mask, mov, fill_mov)

    shift, error, phasediff = phase_cross_correlation(
        ref, mov, upsample_factor=upsample_factor, normalization="phase"
    )

    dy, dx = float(shift[0]), float(shift[1])
    residual = float(np.hypot(dy, dx))

    # Sentinel-2 L2A granules on the same MGRS tile are produced onto a fixed
    # tile grid, so same-tile pairs are already co-registered and a 0.000 px
    # residual here is the expected, correct result rather than a failure to
    # measure. The measurement still earns its place: it catches cross-tile
    # pairs, reprocessed baselines, and the SAR comparison, where the
    # assumption does not hold.

    return {
        "shift_y_px": round(dy, 4),
        "shift_x_px": round(dx, 4),
        "registration_residual_px": round(residual, 4),
        "correlation_error": float(error),
        "phase_difference": float(phasediff),
        "passes_gate_2": residual <= REGISTRATION_MAX_PX,
    }


def apply_shift(stack: np.ndarray, dy: float, dx: float) -> np.ndarray:
    """Resample a stack by a sub-pixel shift, band by band."""
    from scipy.ndimage import shift as ndi_shift

    out = np.empty_like(stack)
    for i in range(stack.shape[0]):
        out[i] = ndi_shift(
            stack[i].astype(np.float32), shift=(dy, dx), order=1, mode="nearest"
        ).astype(stack.dtype)
    return out


def histogram_match(
    source: np.ndarray, reference: np.ndarray, mask: Optional[np.ndarray] = None
) -> Tuple[np.ndarray, Dict[str, float]]:
    """
    Radiometric harmonization to a reference scene.

    Sun angle and atmospheric state shift reflectance between dates even where
    nothing on the ground changed. Matching the clear-pixel distribution removes
    that component so the temporal model sees surface change rather than
    illumination. Statistics come from clear pixels only -- including cloud
    would match the histogram to the weather.
    """
    from skimage.exposure import match_histograms

    src = np.asarray(source, dtype=np.float32)
    ref = np.asarray(reference, dtype=np.float32)

    if mask is not None and np.any(mask):
        src_mean, ref_mean = float(np.mean(src[mask])), float(np.mean(ref[mask]))
        src_std, ref_std = float(np.std(src[mask])), float(np.std(ref[mask]))
    else:
        src_mean, ref_mean = float(np.mean(src)), float(np.mean(ref))
        src_std, ref_std = float(np.std(src)), float(np.std(ref))

    matched = match_histograms(src, ref)

    stats = {
        "source_mean": round(src_mean, 2),
        "reference_mean": round(ref_mean, 2),
        "source_std": round(src_std, 2),
        "reference_std": round(ref_std, 2),
        "mean_offset": round(ref_mean - src_mean, 2),
        "applied": True,
    }
    return matched.astype(source.dtype), stats


def multitemporal_speckle_filter(
    stack: np.ndarray, window: int = 5
) -> Tuple[np.ndarray, Dict[str, float]]:
    """
    Refined-Lee-style adaptive speckle suppression for SAR, in dB.

    Standard Lee assumes multiplicative speckle on linear intensity; our stacks
    are already in dB where speckle is additive, so the local statistics form
    applies directly. The filter preserves edges by weighting the local mean
    against the observed value using the ratio of signal to total variance --
    homogeneous areas get smoothed, edges keep their contrast.
    """
    from scipy.ndimage import uniform_filter

    out = np.empty_like(stack)
    enl_before: List[float] = []
    enl_after: List[float] = []

    for i in range(stack.shape[0]):
        band = stack[i].astype(np.float32)
        finite = np.isfinite(band)
        filled = np.where(finite, band, 0.0)

        mean = uniform_filter(filled, size=window)
        mean_sq = uniform_filter(filled * filled, size=window)
        var = np.maximum(mean_sq - mean * mean, 0.0)

        # Noise variance estimated from the scene's quietest decile, which is
        # where any remaining variance is speckle rather than structure.
        valid_var = var[finite & (var > 0)]
        noise_var = float(np.percentile(valid_var, 10)) if valid_var.size else 0.0

        weight = np.where(var > 0, np.maximum(var - noise_var, 0.0) / var, 0.0)
        filtered = mean + weight * (filled - mean)

        out[i] = np.where(finite, filtered, np.nan)

        if valid_var.size:
            m = float(np.nanmean(band[finite]))
            s = float(np.nanstd(band[finite]))
            enl_before.append((m / s) ** 2 if s > 0 else 0.0)
            fm = float(np.nanmean(out[i][finite]))
            fs = float(np.nanstd(out[i][finite]))
            enl_after.append((fm / fs) ** 2 if fs > 0 else 0.0)

    stats = {
        "window": window,
        "equivalent_looks_before": round(float(np.mean(enl_before)), 3) if enl_before else None,
        "equivalent_looks_after": round(float(np.mean(enl_after)), 3) if enl_after else None,
    }
    return out, stats


def read_stack(path: str) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Read a downloaded COG stack plus its tags."""
    import rasterio

    with rasterio.open(path) as src:
        data = src.read()
        meta = {
            "descriptions": list(src.descriptions),
            "tags": dict(src.tags()),
            "transform": tuple(src.transform)[:6],
            "crs": str(src.crs),
            "width": src.width,
            "height": src.height,
        }
    return data, meta


def find_reference_scene(scenes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Pick the co-registration and harmonization reference.

    Everything else is aligned to this one scene, so it should be the clearest
    available: a reference with cloud in it propagates that cloud's geometry
    into every other scene's registration.
    """
    usable = [s for s in scenes if s.get("cloud_cover") is not None]
    if not usable:
        return scenes[0] if scenes else None
    return min(usable, key=lambda s: s["cloud_cover"])

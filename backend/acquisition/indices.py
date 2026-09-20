"""
Spectral indices and per-cell aggregation — the Tier A trajectory signal.

This is the cheap, dense half of a deliberate two-tier strategy.

Embedding every chip at every date with Prithvi would be 170 scenes x 324 chips
= ~55,000 forward passes, which is not viable on a 4 GB card. But the temporal
engine does not need a 768-d embedding at every date to find a break: CCDC and
BFAST, which the PRD's harmonic/CUSUM design follows, operate on spectral
indices. So:

  Tier A (here)  spectral indices for every analysis cell at every date.
                 Pure numpy, minutes not hours. Drives break detection.
  Tier B         Prithvi + RemoteCLIP embeddings for entities on reference
                 dates. Drives retrieval.
  Tier C         Prithvi embedding trajectories for change candidates only.
                 Drives the trajectory chart the PRD's evidence panel shows.

Indices computed, and why each earns its place:

  NDVI   vegetation  — falls when vegetation is cleared for construction
  NDBI   built-up    — rises when impervious surface appears
  NDWI   water       — separates genuine water change from flooding artefacts
  BSI    bare soil   — catches the cleared-ground phase before a structure
  VV/VH  backscatter — the SAR witness; rises sharply on vertical structure
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np

from backend.core import projenv  # noqa: F401

# Band positions in the processed S2 stack written by 07_preprocess_s2.py.
S2_BANDS = {"B02": 0, "B03": 1, "B04": 2, "B8A": 3, "B11": 4, "B12": 5,
            "SCL": 6, "VALID_MASK": 7}

INDEX_NAMES = ["ndvi", "ndbi", "ndwi", "bsi"]
SAR_NAMES = ["vv_db", "vh_db", "vh_vv_ratio"]

_EPS = 1e-6


def _safe_ratio(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    """Normalized difference with a guarded denominator."""
    den = np.where(np.abs(den) < _EPS, np.nan, den)
    return num / den


def compute_s2_indices(stack: np.ndarray, scale: float = 10000.0) -> Dict[str, np.ndarray]:
    """
    Compute the four optical indices from a processed S2 stack.

    `stack` is band-first as written by stage 07. Reflectance is scaled from
    L2A integer counts to the 0-1 range the index formulas assume.
    """
    blue = stack[S2_BANDS["B02"]].astype(np.float32) / scale
    green = stack[S2_BANDS["B03"]].astype(np.float32) / scale
    red = stack[S2_BANDS["B04"]].astype(np.float32) / scale
    nir = stack[S2_BANDS["B8A"]].astype(np.float32) / scale
    swir1 = stack[S2_BANDS["B11"]].astype(np.float32) / scale
    swir2 = stack[S2_BANDS["B12"]].astype(np.float32) / scale

    ndvi = _safe_ratio(nir - red, nir + red)
    ndbi = _safe_ratio(swir1 - nir, swir1 + nir)
    ndwi = _safe_ratio(green - nir, green + nir)
    # BSI (Rikimaru): combines the soil-bright pair against the vegetation pair,
    # which separates freshly cleared ground from both vegetation and concrete.
    bsi = _safe_ratio((swir1 + red) - (nir + blue), (swir1 + red) + (nir + blue))

    return {"ndvi": ndvi, "ndbi": ndbi, "ndwi": ndwi, "bsi": bsi}


def compute_s1_indices(stack: np.ndarray) -> Dict[str, np.ndarray]:
    """
    SAR features from a processed S1 stack (already in dB).

    The VH/VV ratio is kept because it discriminates scattering mechanism:
    a new building produces a double-bounce signature that lifts VV far more
    than VH, whereas a flooded field drops both. That difference is what makes
    the monsoon negative control work.
    """
    vv = stack[0].astype(np.float32)
    vh = stack[1].astype(np.float32) if stack.shape[0] > 1 else np.full_like(vv, np.nan)
    return {"vv_db": vv, "vh_db": vh, "vh_vv_ratio": vh - vv}


def valid_mask_from_stack(stack: np.ndarray, sensor: str) -> np.ndarray:
    """Boolean usable-pixel mask carried in the last band by stages 07 and 08."""
    if sensor == "sentinel-2":
        return stack[S2_BANDS["VALID_MASK"]].astype(bool)
    return np.isfinite(stack[:2]).all(axis=0)


def aggregate_to_cells(
    values: Dict[str, np.ndarray],
    cell_ids: np.ndarray,
    valid: np.ndarray,
    min_valid_fraction: float = 0.5,
) -> Dict[int, Dict[str, float]]:
    """
    Reduce per-pixel index rasters to per-cell means.

    `cell_ids` is an integer raster labelling every pixel with its analysis cell.
    Cells whose usable fraction falls below the threshold return NaN rather than
    a mean over a handful of cloud-edge pixels -- a partially observed cell that
    reports a confident value is precisely how a false break gets manufactured.

    Uses bincount rather than a per-cell loop: at ~5,600 cells over 5.9 Mpx a
    Python loop would dominate the stage's runtime.
    """
    flat_cells = cell_ids.ravel()
    flat_valid = valid.ravel()
    n_cells = int(flat_cells.max()) + 1 if flat_cells.size else 0
    if n_cells == 0:
        return {}

    total_counts = np.bincount(flat_cells, minlength=n_cells)
    valid_counts = np.bincount(flat_cells, weights=flat_valid.astype(np.float64),
                               minlength=n_cells)

    with np.errstate(invalid="ignore", divide="ignore"):
        valid_fraction = np.where(total_counts > 0, valid_counts / total_counts, 0.0)

    usable = valid_fraction >= min_valid_fraction

    out: Dict[int, Dict[str, float]] = {}
    per_key_means: Dict[str, np.ndarray] = {}

    for key, raster in values.items():
        flat = raster.ravel().astype(np.float64)
        finite = np.isfinite(flat) & flat_valid
        weights = np.where(finite, flat, 0.0)
        sums = np.bincount(flat_cells, weights=weights, minlength=n_cells)
        counts = np.bincount(flat_cells, weights=finite.astype(np.float64),
                             minlength=n_cells)
        with np.errstate(invalid="ignore", divide="ignore"):
            per_key_means[key] = np.where(counts > 0, sums / counts, np.nan)

    for cell in range(n_cells):
        if total_counts[cell] == 0:
            continue
        record: Dict[str, float] = {
            "valid_fraction": float(valid_fraction[cell]),
            "pixel_count": int(total_counts[cell]),
        }
        for key, means in per_key_means.items():
            record[key] = float(means[cell]) if usable[cell] else float("nan")
        out[cell] = record

    return out


def build_cell_index(
    grid, h3_resolution: int = 9
) -> Tuple[np.ndarray, Dict[int, str]]:
    """
    Label every pixel on the canonical grid with an analysis cell.

    Cells are H3 resolution 9 (~0.1 km2), as PRD section 4.6 specifies: uniform
    neighbour distance and a hierarchical rollup, which a square grid does not
    give you. Returns an integer label raster plus a mapping from label to H3
    index so trajectories carry a real, joinable cell identifier.

    Computing H3 per pixel would be 5.9 M lookups; instead we evaluate H3 on a
    coarse sub-grid and nearest-fill, which lands cell boundaries within a pixel
    or two -- well inside the positional uncertainty of the imagery itself.
    """
    import h3
    from pyproj import Transformer

    # One sample per ~1/3 cell edge keeps boundaries tight without the full cost.
    step = 8
    rows = np.arange(0, grid.height, step)
    cols = np.arange(0, grid.width, step)

    transform = grid.transform
    xs = transform.c + (cols + 0.5) * transform.a
    ys = transform.f + (rows + 0.5) * transform.e
    grid_x, grid_y = np.meshgrid(xs, ys)

    to_wgs84 = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True)
    lon, lat = to_wgs84.transform(grid_x, grid_y)

    h3_codes = np.empty(lon.shape, dtype=object)
    for i in range(lon.shape[0]):
        for j in range(lon.shape[1]):
            h3_codes[i, j] = h3.latlng_to_cell(float(lat[i, j]), float(lon[i, j]),
                                               h3_resolution)

    unique = sorted({c for c in h3_codes.ravel()})
    code_to_label = {code: idx for idx, code in enumerate(unique)}
    label_to_code = {idx: code for code, idx in code_to_label.items()}

    coarse = np.vectorize(code_to_label.get)(h3_codes).astype(np.int32)

    # Nearest-neighbour upsample back to full grid resolution.
    row_idx = np.minimum(np.arange(grid.height) // step, coarse.shape[0] - 1)
    col_idx = np.minimum(np.arange(grid.width) // step, coarse.shape[1] - 1)
    labels = coarse[np.ix_(row_idx, col_idx)]

    return labels, label_to_code

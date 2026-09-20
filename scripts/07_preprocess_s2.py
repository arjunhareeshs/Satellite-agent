"""
07 — Preprocess Sentinel-2: cloud mask, co-register, harmonize.

Replaces a version that created two empty directories, wrote one hand-authored
quality_manifest.json, and printed "Gate 2 Passed" -- while also claiming in its
header to be doing the Sentinel-1 chain, which is now 08_preprocess_s1.py.

For each downloaded scene this measures, rather than asserts:

  valid_pixel_fraction        from SCL + s2cloudless            -> fusion Gate 1
  registration_residual_px    FFT phase correlation, sub-pixel  -> fusion Gate 2
  radiometric offset          histogram match to the reference  -> fusion Gate 3

Scenes with a residual above 0.5 px after correction are flagged
`excluded_from_change` but kept for retrieval, exactly as PRD section 4.5 says.

Usage:
    python scripts/07_preprocess_s2.py
    python scripts/07_preprocess_s2.py --limit 5
    python scripts/07_preprocess_s2.py --force
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
    BAND_INDEX,
    REGISTRATION_MAX_PX,
    apply_shift,
    cloud_mask_from_scl,
    coregister,
    find_reference_scene,
    histogram_match,
    read_stack,
    refine_mask_with_s2cloudless,
)
from backend.acquisition.raster import assert_on_grid, write_cog  # noqa: E402
from backend.core.grid import get_grid  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "data", "metadata", "s2_scenes.json")
RAW_ROOT = os.path.join(ROOT, "data", "raw", "sentinel2")
OUT_ROOT = os.path.join(ROOT, "data", "processed", "s2_cogs")
QUALITY_PATH = os.path.join(ROOT, "data", "metadata", "s2_quality.json")

# Co-registration runs on NIR: it has strong, stable structure at built-up edges
# and is far less sensitive to atmospheric scattering than the visible bands.
COREG_BAND = "B8A"


def raw_path(stac_id: str) -> str:
    return os.path.join(RAW_ROOT, stac_id, "%s_stack.tif" % stac_id)


def out_path(stac_id: str) -> str:
    return os.path.join(OUT_ROOT, "%s.tif" % stac_id)


def main() -> int:
    ap = argparse.ArgumentParser(description="Preprocess Sentinel-2 scenes")
    ap.add_argument("--manifest", default=MANIFEST)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-cloudless", action="store_true",
                    help="Skip s2cloudless refinement, use SCL alone")
    args = ap.parse_args()

    if not os.path.exists(args.manifest):
        print("FAIL: run scripts/03 and 04 first.", file=sys.stderr)
        return 1

    with open(args.manifest, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)

    scenes = [s for s in manifest["scenes"] if os.path.exists(raw_path(s["stac_id"]))]
    if not scenes:
        print("FAIL: no downloaded scenes found under data/raw/sentinel2.", file=sys.stderr)
        return 1
    if args.limit:
        scenes = scenes[: args.limit]

    grid = get_grid()
    os.makedirs(OUT_ROOT, exist_ok=True)

    reference = find_reference_scene(scenes)
    print("TRINETRA — Sentinel-2 preprocessing")
    print("  scenes      : %d" % len(scenes))
    print("  reference   : %s (cloud %.1f%%)"
          % (reference["stac_id"], reference.get("cloud_cover", 0.0)))
    print("  coreg band  : %s" % COREG_BAND)
    print("  gate 2      : residual <= %.2f px" % REGISTRATION_MAX_PX)
    print()

    ref_stack, _ = read_stack(raw_path(reference["stac_id"]))
    ref_scl = ref_stack[BAND_INDEX["SCL"]]
    ref_mask, _ = cloud_mask_from_scl(ref_scl)
    ref_coreg_band = ref_stack[BAND_INDEX[COREG_BAND]]

    records = []
    excluded = 0
    t_start = time.perf_counter()

    for i, scene in enumerate(scenes, start=1):
        stac_id = scene["stac_id"]
        dst = out_path(stac_id)

        if not args.force and os.path.exists(dst):
            print("  [%3d/%3d] cached  %s" % (i, len(scenes), stac_id))
            continue

        t0 = time.perf_counter()
        stack, meta = read_stack(raw_path(stac_id))
        scl = stack[BAND_INDEX["SCL"]]

        # ---- Gate 1: cloud / shadow / snow mask --------------------------
        mask, breakdown = cloud_mask_from_scl(scl)
        cloud_prob = None
        if not args.no_cloudless:
            mask, cloud_prob = refine_mask_with_s2cloudless(stack, mask)
        valid_fraction = float(np.count_nonzero(mask)) / mask.size

        # ---- Gate 2: co-registration -------------------------------------
        is_reference = stac_id == reference["stac_id"]
        if is_reference:
            coreg = {
                "shift_y_px": 0.0,
                "shift_x_px": 0.0,
                "registration_residual_px": 0.0,
                "correlation_error": 0.0,
                "phase_difference": 0.0,
                "passes_gate_2": True,
                "note": "reference scene",
            }
            reflectance = stack[:6]
        else:
            coreg = coregister(
                stack[BAND_INDEX[COREG_BAND]],
                ref_coreg_band,
                mask=mask & ref_mask,
            )
            reflectance = apply_shift(
                stack[:6], coreg["shift_y_px"], coreg["shift_x_px"]
            )

        # ---- Gate 3: radiometric harmonization ---------------------------
        if is_reference:
            harmon = {"applied": False, "note": "reference scene"}
        else:
            harmonized = np.empty_like(reflectance)
            offsets = []
            for band_idx in range(6):
                matched, stats = histogram_match(
                    reflectance[band_idx], ref_stack[band_idx], mask=mask & ref_mask
                )
                harmonized[band_idx] = matched
                offsets.append(stats["mean_offset"])
            reflectance = harmonized
            harmon = {"applied": True, "mean_offset_per_band": offsets}

        # ---- write -------------------------------------------------------
        out_stack = np.concatenate(
            [
                reflectance.astype("uint16"),
                scl[np.newaxis, ...].astype("uint16"),
                (mask.astype("uint16") * 1)[np.newaxis, ...],
            ],
            axis=0,
        )
        band_names = ["B02", "B03", "B04", "B8A", "B11", "B12", "SCL", "VALID_MASK"]

        write_cog(
            dst,
            out_stack,
            grid,
            band_names=band_names,
            dtype="uint16",
            nodata=0,
            tags={
                "TRINETRA_STAC_ID": stac_id,
                "TRINETRA_SENSOR": "sentinel-2",
                "TRINETRA_DATETIME": scene["datetime"],
                "TRINETRA_BANDS": ",".join(band_names),
                "TRINETRA_VALID_FRACTION": round(valid_fraction, 4),
                "TRINETRA_REGISTRATION_PX": coreg["registration_residual_px"],
                "TRINETRA_REFERENCE_SCENE": reference["stac_id"],
                "TRINETRA_CHAIN": "mask->coregister->harmonize",
            },
        )
        assert_on_grid(dst, grid)

        passes = coreg["passes_gate_2"]
        if not passes:
            excluded += 1

        record = {
            "stac_id": stac_id,
            "datetime": scene["datetime"],
            "sensor": "sentinel-2",
            "output": os.path.relpath(dst, ROOT),
            "reference_scene": reference["stac_id"],
            "valid_pixel_fraction": round(valid_fraction, 4),
            "scl_breakdown_pct": {k: round(v, 2) for k, v in breakdown.items()},
            "s2cloudless_mean_probability": (
                round(cloud_prob, 4) if cloud_prob is not None else None
            ),
            "scene_cloud_cover": scene.get("cloud_cover"),
            "coregistration": coreg,
            "radiometric": harmon,
            "excluded_from_change": not passes,
            "processing_chain": [
                "scl_mask",
                "s2cloudless_refine" if cloud_prob is not None else "scl_only",
                "phase_correlation_coregister",
                "histogram_match",
                "cog_write",
            ],
            "elapsed_sec": round(time.perf_counter() - t0, 2),
        }
        records.append(record)

        flag = "" if passes else "  EXCLUDED from change (gate 2)"
        print("  [%3d/%3d] %5.1fs  %s  valid %5.1f%%  residual %.3f px%s"
              % (i, len(scenes), record["elapsed_sec"], stac_id,
                 valid_fraction * 100, coreg["registration_residual_px"], flag))

    # ---- quality manifest -------------------------------------------------
    if records:
        valids = [r["valid_pixel_fraction"] for r in records]
        residuals = [r["coregistration"]["registration_residual_px"] for r in records]
        quality = {
            "sensor": "sentinel-2",
            "reference_scene": reference["stac_id"],
            "coregistration_band": COREG_BAND,
            "gate_2_threshold_px": REGISTRATION_MAX_PX,
            "scenes_processed": len(records),
            "scenes_excluded_from_change": excluded,
            "valid_pixel_fraction": {
                "min": round(min(valids), 4),
                "median": round(float(np.median(valids)), 4),
                "max": round(max(valids), 4),
            },
            "registration_residual_px": {
                "min": round(min(residuals), 4),
                "median": round(float(np.median(residuals)), 4),
                "max": round(max(residuals), 4),
            },
            "scenes": records,
        }
        os.makedirs(os.path.dirname(QUALITY_PATH), exist_ok=True)
        with open(QUALITY_PATH, "w", encoding="utf-8") as fh:
            json.dump(quality, fh, indent=2)

        print()
        print("  processed   : %d" % len(records))
        print("  excluded    : %d (registration residual > %.2f px)"
              % (excluded, REGISTRATION_MAX_PX))
        print("  valid frac  : min %.3f  median %.3f  max %.3f"
              % (min(valids), float(np.median(valids)), max(valids)))
        print("  residual px : min %.3f  median %.3f  max %.3f"
              % (min(residuals), float(np.median(residuals)), max(residuals)))
        print("  wall clock  : %.1f s" % (time.perf_counter() - t_start))
        print("  wrote       : %s" % os.path.relpath(QUALITY_PATH, ROOT))

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
09 — Cut processed scenes into georeferenced chips.

Replaces a version that wrote one hardcoded chips_sample.json dict and never
opened a raster.

Each chip is 256 x 256 px at 10 m (2.56 km on a side -- enough context for a
"near river" relationship to be visible within the chip) with a 128 px stride,
so consecutive chips overlap by half. The overlap matters: at stride 256 an
object straddling a boundary is cut in two and segmented as two partial
objects. Stage 10 dissolves duplicates back together using this overlap.

Chips are not written as separate files. At 324 chips per scene x ~170 scenes
that would be 55,000 small files, and the windowed read from the scene COG is
fast enough that materializing them buys nothing. What this stage produces is
the chip *index* -- geometry, H3 cell, quality -- which stages 10 and 11 use to
pull pixels on demand.

Usage:
    python scripts/09_create_chips.py
    python scripts/09_create_chips.py --limit 5
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.acquisition.indices import S2_BANDS  # noqa: E402
from backend.core.grid import get_grid, load_aoi_config  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S2_QUALITY = os.path.join(ROOT, "data", "metadata", "s2_quality.json")
S1_QUALITY = os.path.join(ROOT, "data", "metadata", "s1_quality.json")
OUT_PATH = os.path.join(ROOT, "data", "metadata", "chips.json")

# Below this usable fraction a chip cannot support a reliable segmentation or
# embedding, so it is indexed but flagged rather than silently included.
MIN_USABLE_FRACTION = 0.5


def chip_windows(grid, chip_size: int, stride: int):
    """Yield (row, col, row_off, col_off) for every chip origin on the grid."""
    for r, row_off in enumerate(range(0, grid.height - chip_size + 1, stride)):
        for c, col_off in enumerate(range(0, grid.width - chip_size + 1, stride)):
            yield r, c, row_off, col_off


def main() -> int:
    cfg = load_aoi_config()
    chip_cfg = cfg.get("chipping", {})

    ap = argparse.ArgumentParser(description="Index georeferenced chips")
    ap.add_argument("--chip-size", type=int, default=chip_cfg.get("chip_size_px", 256))
    ap.add_argument("--stride", type=int, default=chip_cfg.get("stride_px", 128))
    ap.add_argument("--h3-resolution", type=int, default=chip_cfg.get("h3_resolution", 9))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=OUT_PATH)
    args = ap.parse_args()

    if not os.path.exists(S2_QUALITY):
        print("FAIL: run scripts/07_preprocess_s2.py first.", file=sys.stderr)
        return 1

    import h3
    import rasterio
    from pyproj import Transformer
    from rasterio.windows import Window

    with open(S2_QUALITY, "r", encoding="utf-8") as fh:
        s2_quality = json.load(fh)

    s1_scenes = []
    if os.path.exists(S1_QUALITY):
        with open(S1_QUALITY, "r", encoding="utf-8") as fh:
            s1_scenes = json.load(fh).get("scenes", [])

    scenes = s2_quality["scenes"]
    if args.limit:
        scenes = scenes[: args.limit]

    grid = get_grid()
    windows = list(chip_windows(grid, args.chip_size, args.stride))
    to_wgs84 = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True)

    print("TRINETRA — chipping")
    print("  scenes      : %d Sentinel-2, %d Sentinel-1" % (len(scenes), len(s1_scenes)))
    print("  chip        : %d x %d px @ %g m (%.2f km per side)"
          % (args.chip_size, args.chip_size, grid.resolution_m,
             args.chip_size * grid.resolution_m / 1000))
    print("  stride      : %d px (%.0f%% overlap)"
          % (args.stride, (1 - args.stride / args.chip_size) * 100))
    print("  per scene   : %d chips" % len(windows))
    print("  analysis    : H3 resolution %d" % args.h3_resolution)
    print()

    # ---- chip geometry is scene-independent; compute it once ---------------
    transform = grid.transform
    geometry = []
    for r, c, row_off, col_off in windows:
        left = transform.c + col_off * transform.a
        top = transform.f + row_off * transform.e
        right = left + args.chip_size * transform.a
        bottom = top + args.chip_size * transform.e

        cx, cy = (left + right) / 2.0, (top + bottom) / 2.0
        clon, clat = to_wgs84.transform(cx, cy)
        min_lon, min_lat = to_wgs84.transform(left, bottom)
        max_lon, max_lat = to_wgs84.transform(right, top)

        geometry.append(
            {
                "row": r,
                "col": c,
                "row_off": row_off,
                "col_off": col_off,
                "bbox": [round(min_lon, 6), round(min_lat, 6),
                         round(max_lon, 6), round(max_lat, 6)],
                "centroid": [round(clon, 6), round(clat, 6)],
                "h3_r%d" % args.h3_resolution: h3.latlng_to_cell(
                    clat, clon, args.h3_resolution
                ),
                "utm_bounds": [left, bottom, right, top],
            }
        )

    print("  computed %d chip footprints on the canonical grid" % len(geometry))
    print()

    # ---- per-scene quality -------------------------------------------------
    chips = []
    usable_total = 0
    t_start = time.perf_counter()

    for i, scene in enumerate(scenes, start=1):
        scene_path = os.path.join(ROOT, scene["output"])
        if not os.path.exists(scene_path):
            print("  [%3d/%3d] SKIP  missing %s" % (i, len(scenes), scene["output"]))
            continue

        t0 = time.perf_counter()
        date = scene["datetime"][:10]
        scene_usable = 0

        with rasterio.open(scene_path) as src:
            valid_band = S2_BANDS["VALID_MASK"] + 1
            scl_band = S2_BANDS["SCL"] + 1

            for geom in geometry:
                window = Window(
                    geom["col_off"], geom["row_off"], args.chip_size, args.chip_size
                )
                valid = src.read(valid_band, window=window).astype(bool)
                scl = src.read(scl_band, window=window)

                valid_fraction = float(np.count_nonzero(valid)) / valid.size
                cloud_fraction = float(np.count_nonzero(np.isin(scl, (8, 9, 10)))) / scl.size
                usable = valid_fraction >= MIN_USABLE_FRACTION
                if usable:
                    scene_usable += 1

                chips.append(
                    {
                        "chip_id": "delhi_r%04d_c%04d_%s"
                        % (geom["row"], geom["col"], date.replace("-", "")),
                        "scene_id": scene["stac_id"],
                        "sensor": "sentinel-2",
                        "datetime": scene["datetime"],
                        "row": geom["row"],
                        "col": geom["col"],
                        "row_off": geom["row_off"],
                        "col_off": geom["col_off"],
                        "bbox": geom["bbox"],
                        "centroid": geom["centroid"],
                        "h3_r%d" % args.h3_resolution: geom["h3_r%d" % args.h3_resolution],
                        "crs": grid.crs,
                        "valid_fraction": round(valid_fraction, 4),
                        "cloud_fraction": round(cloud_fraction, 4),
                        "usable": usable,
                        "storage_uri": scene["output"],
                        "excluded_from_change": scene.get("excluded_from_change", False),
                    }
                )

        usable_total += scene_usable
        print("  [%3d/%3d] %5.1fs  %s  %d/%d chips usable"
              % (i, len(scenes), time.perf_counter() - t0, scene["stac_id"],
                 scene_usable, len(geometry)))

    # ---- write -------------------------------------------------------------
    h3_key = "h3_r%d" % args.h3_resolution
    index = {
        "chip_size_px": args.chip_size,
        "stride_px": args.stride,
        "resolution_m": grid.resolution_m,
        "crs": grid.crs,
        "h3_resolution": args.h3_resolution,
        "chips_per_scene": len(geometry),
        "scenes_indexed": len({c["scene_id"] for c in chips}),
        "total_chips": len(chips),
        "usable_chips": usable_total,
        "min_usable_fraction": MIN_USABLE_FRACTION,
        "unique_h3_cells": len({c[h3_key] for c in chips}),
        "chips": chips,
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(index, fh)

    print()
    print("  total chips : %d across %d scenes" % (len(chips), index["scenes_indexed"]))
    print("  usable      : %d (%.1f%%)"
          % (usable_total, 100.0 * usable_total / max(len(chips), 1)))
    print("  H3 cells    : %d distinct at resolution %d"
          % (index["unique_h3_cells"], args.h3_resolution))
    print("  wall clock  : %.1f s" % (time.perf_counter() - t_start))
    print("  wrote       : %s (%.1f MB)"
          % (os.path.relpath(args.out, ROOT), os.path.getsize(args.out) / 1e6))
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

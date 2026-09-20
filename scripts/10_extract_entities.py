"""
10 — Segment chips into typed geo-objects.

Replaces a version whose entire body was os.makedirs plus three print()
statements, the last of which asserted "[OK] Extracted 1,420 geo-objects" -- a
literal that then propagated into build_report.json and the /stats endpoint.

Pipeline per chip:

    read 6-band window from the processed scene COG
    build an 8-bit RGB view for the segmenter
    FastSAM (or SAM) proposes class-agnostic regions
    filter by indexable area
    polygonize each mask with rasterio.features.shapes
    type it from geometry + spectral signature
    accumulate

Then across the whole date:

    dissolve duplicates created by the 50% chip overlap (IoU > 0.5)
    compute area, orientation, centroid in the working CRS

Entities are extracted on *reference dates* rather than every date -- one clear
scene per quarter. A geo-object does not need re-segmenting every 10 days; what
changes over time is its trajectory, which stage 14 builds. This is what keeps
the entity pass to ~19 dates instead of ~170.

Usage:
    python scripts/10_extract_entities.py
    python scripts/10_extract_entities.py --quality        # SAM instead of FastSAM
    python scripts/10_extract_entities.py --limit-dates 2  # smoke test
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from typing import Any, Dict, List

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.acquisition.indices import S2_BANDS, compute_s2_indices  # noqa: E402
from backend.core.grid import get_grid  # noqa: E402
from backend.models.segmentation import (  # noqa: E402
    classify_region,
    filter_regions,
    get_segmenter,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHIPS_PATH = os.path.join(ROOT, "data", "metadata", "chips.json")
S2_QUALITY = os.path.join(ROOT, "data", "metadata", "s2_quality.json")
OUT_PATH = os.path.join(ROOT, "data", "metadata", "entities.json")

# Reference dates for segmentation: one clear scene per quarter.
REFERENCE_PER_QUARTER = 1
# Two masks overlapping by more than this across the chip seam are the same
# object seen twice.
DEDUP_IOU = 0.5


def to_rgb(window: np.ndarray, percentile: float = 2.0) -> np.ndarray:
    """
    Build an 8-bit RGB view for the segmenter.

    Percentile stretch rather than a fixed scale: L2A reflectance over a hazy
    Delhi scene occupies a narrow part of the range, and a fixed divisor leaves
    the segmenter looking at a flat grey image with no edges to find.
    """
    rgb = np.stack(
        [window[S2_BANDS["B04"]], window[S2_BANDS["B03"]], window[S2_BANDS["B02"]]],
        axis=-1,
    ).astype(np.float32)

    out = np.zeros(rgb.shape, dtype=np.uint8)
    for band in range(3):
        channel = rgb[..., band]
        finite = channel[np.isfinite(channel) & (channel > 0)]
        if finite.size == 0:
            continue
        lo, hi = np.percentile(finite, [percentile, 100 - percentile])
        if hi <= lo:
            continue
        out[..., band] = np.clip((channel - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)
    return out


def select_reference_dates(scenes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One clear scene per calendar quarter."""
    quarters: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for scene in scenes:
        if scene.get("excluded_from_change"):
            continue
        dt = scene["datetime"]
        quarter = "%s-Q%d" % (dt[:4], (int(dt[5:7]) - 1) // 3 + 1)
        quarters[quarter].append(scene)

    chosen: List[Dict[str, Any]] = []
    for quarter in sorted(quarters):
        ranked = sorted(
            quarters[quarter], key=lambda s: -s.get("valid_pixel_fraction", 0.0)
        )
        chosen.extend(ranked[:REFERENCE_PER_QUARTER])
    return chosen


def dissolve_duplicates(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge entities duplicated across the 50% chip overlap.

    Compared only within a spatial bucket rather than all-pairs: at a few
    thousand entities per date, an O(n^2) shapely intersection would dominate
    this stage.
    """
    from shapely.geometry import shape
    from shapely.ops import unary_union

    buckets: Dict[Any, List[int]] = defaultdict(list)
    geoms = []
    for idx, ent in enumerate(entities):
        geom = shape(ent["_geometry_utm"])
        geoms.append(geom)
        cx, cy = geom.centroid.x, geom.centroid.y
        # 1 km buckets; chip overlap is 1.28 km so neighbours land in adjacent keys.
        buckets[(int(cx // 1000), int(cy // 1000))].append(idx)

    merged_into: Dict[int, int] = {}
    groups: Dict[int, List[int]] = defaultdict(list)

    for key, idxs in buckets.items():
        neighbours = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                neighbours.extend(buckets.get((key[0] + dx, key[1] + dy), []))

        for i in idxs:
            if i in merged_into:
                continue
            groups[i].append(i)
            merged_into[i] = i
            for j in neighbours:
                if j <= i or j in merged_into:
                    continue
                if entities[i]["entity_type"] != entities[j]["entity_type"]:
                    continue
                gi, gj = geoms[i], geoms[j]
                if not gi.intersects(gj):
                    continue
                inter = gi.intersection(gj).area
                union = gi.union(gj).area
                if union > 0 and inter / union > DEDUP_IOU:
                    groups[i].append(j)
                    merged_into[j] = i

    out: List[Dict[str, Any]] = []
    for root, members in groups.items():
        if len(members) == 1:
            out.append(entities[root])
            continue
        union_geom = unary_union([geoms[m] for m in members])
        merged = dict(entities[root])
        merged["_geometry_utm"] = union_geom.__geo_interface__
        merged["area_m2"] = round(union_geom.area, 1)
        merged["class_confidence"] = round(
            float(np.mean([entities[m]["class_confidence"] for m in members])), 3
        )
        merged["merged_from_chips"] = sorted({entities[m]["chip_id"] for m in members})
        out.append(merged)

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Segment chips into geo-objects")
    ap.add_argument("--quality", action="store_true", help="Use SAM ViT-B instead of FastSAM")
    ap.add_argument("--limit-dates", type=int, default=None)
    ap.add_argument("--limit-chips", type=int, default=None)
    ap.add_argument("--out", default=OUT_PATH)
    args = ap.parse_args()

    for path, hint in ((CHIPS_PATH, "09_create_chips.py"), (S2_QUALITY, "07_preprocess_s2.py")):
        if not os.path.exists(path):
            print("FAIL: run scripts/%s first." % hint, file=sys.stderr)
            return 1

    import rasterio
    from pyproj import Transformer
    from rasterio.features import shapes as raster_shapes
    from rasterio.windows import Window, transform as window_transform

    with open(CHIPS_PATH, "r", encoding="utf-8") as fh:
        chip_index = json.load(fh)
    with open(S2_QUALITY, "r", encoding="utf-8") as fh:
        s2_quality = json.load(fh)

    grid = get_grid()
    chip_size = chip_index["chip_size_px"]
    h3_key = "h3_r%d" % chip_index["h3_resolution"]

    reference_scenes = select_reference_dates(s2_quality["scenes"])
    if args.limit_dates:
        reference_scenes = reference_scenes[: args.limit_dates]

    segmenter = get_segmenter(quality=args.quality)
    to_wgs84 = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True)

    chips_by_scene: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for chip in chip_index["chips"]:
        if chip.get("usable"):
            chips_by_scene[chip["scene_id"]].append(chip)

    print("TRINETRA — entity extraction")
    print("  segmenter   : %s" % segmenter.name)
    print("  ref dates   : %d (one clear scene per quarter)" % len(reference_scenes))
    print("  area filter : 200 - 500,000 m2")
    print("  dedup       : IoU > %.2f across the %d px chip overlap"
          % (DEDUP_IOU, chip_size - chip_index["stride_px"]))
    print()

    all_entities: List[Dict[str, Any]] = []
    type_counts: Dict[str, int] = defaultdict(int)
    t_start = time.perf_counter()

    for scene_i, scene in enumerate(reference_scenes, start=1):
        scene_path = os.path.join(ROOT, scene["output"])
        if not os.path.exists(scene_path):
            continue

        chips = chips_by_scene.get(scene["stac_id"], [])
        if args.limit_chips:
            chips = chips[: args.limit_chips]
        if not chips:
            continue

        date = scene["datetime"][:10]
        t_scene = time.perf_counter()
        scene_entities: List[Dict[str, Any]] = []

        with rasterio.open(scene_path) as src:
            for chip in chips:
                window = Window(chip["col_off"], chip["row_off"], chip_size, chip_size)
                data = src.read(window=window)
                win_transform = window_transform(window, src.transform)

                rgb = to_rgb(data)
                if rgb.max() == 0:
                    continue

                try:
                    regions = segmenter.segment(rgb)
                except Exception as exc:  # noqa: BLE001
                    print("    segmentation failed on %s: %s" % (chip["chip_id"], exc))
                    continue

                regions = filter_regions(regions, grid.resolution_m)
                if not regions:
                    continue

                indices = compute_s2_indices(data)
                valid = data[S2_BANDS["VALID_MASK"]].astype(bool)

                for region in regions:
                    # Reject regions sitting mostly under cloud: the segmenter
                    # happily outlines a cloud edge as a crisp object.
                    if np.count_nonzero(region.mask & valid) / region.area_px < 0.6:
                        continue

                    entity_type, confidence, attributes = classify_region(
                        region, indices, grid.resolution_m
                    )
                    if entity_type == "unknown":
                        continue

                    polygons = [
                        geom
                        for geom, value in raster_shapes(
                            region.mask.astype(np.uint8),
                            mask=region.mask,
                            transform=win_transform,
                        )
                        if value == 1
                    ]
                    if not polygons:
                        continue
                    geometry_utm = max(polygons, key=lambda g: len(str(g)))

                    from shapely.geometry import shape as to_shape

                    shp = to_shape(geometry_utm)
                    if shp.is_empty:
                        continue
                    cx, cy = shp.centroid.x, shp.centroid.y
                    clon, clat = to_wgs84.transform(cx, cy)

                    rect = shp.minimum_rotated_rectangle
                    orientation = 0.0
                    try:
                        coords = list(rect.exterior.coords)[:4]
                        edge = max(
                            zip(coords, coords[1:] + coords[:1]),
                            key=lambda pair: (pair[1][0] - pair[0][0]) ** 2
                            + (pair[1][1] - pair[0][1]) ** 2,
                        )
                        orientation = float(
                            np.degrees(
                                np.arctan2(
                                    edge[1][1] - edge[0][1], edge[1][0] - edge[0][0]
                                )
                            )
                            % 180
                        )
                    except (AttributeError, IndexError):
                        pass

                    scene_entities.append(
                        {
                            "entity_type": entity_type,
                            "class_confidence": round(confidence, 3),
                            "area_m2": round(shp.area, 1),
                            "orientation_deg": round(orientation, 1),
                            "centroid": {"lon": round(clon, 6), "lat": round(clat, 6)},
                            "centroid_utm": [round(cx, 2), round(cy, 2)],
                            h3_key: chip[h3_key],
                            "chip_id": chip["chip_id"],
                            "scene_id": scene["stac_id"],
                            "observed_date": date,
                            "segmenter": segmenter.name,
                            "segment_score": round(region.score, 3),
                            "attributes": attributes,
                            "_geometry_utm": geometry_utm,
                        }
                    )

        before = len(scene_entities)
        scene_entities = dissolve_duplicates(scene_entities)
        for ent in scene_entities:
            type_counts[ent["entity_type"]] += 1
        all_entities.extend(scene_entities)

        print("  [%2d/%2d] %6.1fs  %s  %d chips -> %d regions -> %d entities"
              % (scene_i, len(reference_scenes), time.perf_counter() - t_scene,
                 date, len(chips), before, len(scene_entities)))

    # ---- assign stable IDs and project geometry to WGS84 -------------------
    from shapely.geometry import mapping, shape as to_shape
    from shapely.ops import transform as shp_transform

    prefix = {
        "building": "BLDG", "road": "ROAD", "water": "WTR",
        "vegetation": "VEG", "bare_ground": "BARE",
    }
    counters: Dict[str, int] = defaultdict(int)

    for ent in all_entities:
        code = prefix.get(ent["entity_type"], "OBJ")
        counters[code] += 1
        ent["entity_id"] = "%s_%06d" % (code, counters[code])

        geom_utm = to_shape(ent.pop("_geometry_utm"))
        geom_wgs = shp_transform(
            lambda x, y, z=None: to_wgs84.transform(x, y), geom_utm
        )
        ent["geometry"] = mapping(geom_wgs)
        ent["geometry_crs"] = "EPSG:4326"

    output = {
        "segmenter": segmenter.name,
        "reference_dates": [s["datetime"][:10] for s in reference_scenes],
        "grid": {"crs": grid.crs, "resolution_m": grid.resolution_m},
        "dedup_iou": DEDUP_IOU,
        "total_entities": len(all_entities),
        "by_type": dict(sorted(type_counts.items(), key=lambda kv: -kv[1])),
        "entities": all_entities,
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(output, fh)

    print()
    print("  entities    : %d" % len(all_entities))
    for etype, count in output["by_type"].items():
        print("    %-14s %d" % (etype, count))
    print("  wall clock  : %.1f s" % (time.perf_counter() - t_start))
    print("  wrote       : %s (%.1f MB)"
          % (os.path.relpath(args.out, ROOT), os.path.getsize(args.out) / 1e6))

    if not all_entities:
        print("FAIL: no entities extracted.", file=sys.stderr)
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

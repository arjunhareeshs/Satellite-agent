"""
01 — Validate the AOI and derive the canonical analysis grid.

Previously this script copied five fields out of config/aoi.yaml and claimed in
its docstring to compute area and derive MGRS tiles; it did neither, which is
how config/aoi.yaml came to carry an area of 538.2 km2 (the real geodesic area
is 597.0) and the MGRS tiles 43RFG/43RFH, neither of which covers this bbox.
Both errors survived because nothing recomputed them.

This version recomputes everything and fails loudly on drift.

Writes data/metadata/aoi_summary.json and data/raw/vectors/aoi.geojson.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.grid import (  # noqa: E402
    geodesic_area_km2,
    get_grid,
    load_aoi_config,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AREA_TOLERANCE_KM2 = 1.0


def derive_mgrs_tiles(bounds: dict) -> list:
    """
    Derive the MGRS 100 km square IDs that intersect the AOI.

    Sampled on a grid rather than at the four corners: a bbox can clip a tile
    along an edge without containing any of that tile's corners, and that is
    exactly the case that produced the wrong tile list before.
    """
    import mgrs

    m = mgrs.MGRS()
    tiles = set()
    steps = 12
    lon_span = bounds["max_lon"] - bounds["min_lon"]
    lat_span = bounds["max_lat"] - bounds["min_lat"]

    for i in range(steps + 1):
        for j in range(steps + 1):
            lon = bounds["min_lon"] + lon_span * i / steps
            lat = bounds["min_lat"] + lat_span * j / steps
            # MGRS at 100 km precision -> zone + band + 100 km square
            code = m.toMGRS(lat, lon, MGRSPrecision=0)
            tiles.add(code[:5] if len(code) >= 5 else code)

    return sorted(tiles)


def main() -> int:
    cfg = load_aoi_config()
    bounds = cfg["bounds"]
    poly = cfg["polygon_coordinates"]

    print("TRINETRA — AOI definition")
    print("  name        : %s (config version %s)" % (cfg["name"], cfg.get("version")))
    print("  bounds      : %.4f, %.4f -> %.4f, %.4f"
          % (bounds["min_lon"], bounds["min_lat"], bounds["max_lon"], bounds["max_lat"]))

    # ---- polygon validity -------------------------------------------------
    from shapely.geometry import Polygon

    ring = Polygon(poly)
    if not ring.is_valid:
        print("  FAIL: polygon is not valid: %s" % ring.is_valid_reason, file=sys.stderr)
        return 1
    if poly[0] != poly[-1]:
        print("  FAIL: polygon ring is not closed", file=sys.stderr)
        return 1
    print("  polygon     : valid, closed, %d vertices" % (len(poly) - 1))

    # ---- area -------------------------------------------------------------
    area = geodesic_area_km2(
        bounds["min_lon"], bounds["min_lat"], bounds["max_lon"], bounds["max_lat"]
    )
    declared = float(cfg.get("area_km2", 0.0))
    print("  area        : %.2f km2 computed (config says %.2f)" % (area, declared))
    if abs(area - declared) > AREA_TOLERANCE_KM2:
        print(
            "  FAIL: config/aoi.yaml area_km2 is %.2f but the geodesic area is %.2f.\n"
            "        Update config/aoi.yaml rather than ignoring this."
            % (declared, area),
            file=sys.stderr,
        )
        return 1

    # ---- MGRS -------------------------------------------------------------
    squares = derive_mgrs_tiles(bounds)
    declared_squares = sorted(cfg.get("mgrs_squares", []))
    print("  mgrs squares: %s computed (config says %s)" % (squares, declared_squares))
    if squares != declared_squares:
        print(
            "  FAIL: config/aoi.yaml mgrs_squares %s does not match the derived %s."
            % (declared_squares, squares),
            file=sys.stderr,
        )
        return 1

    # Sentinel-2 granule tiles are a different, larger set than the strict MGRS
    # squares: granules span 110 km and overlap neighbours by roughly 10 km, so a
    # granule named for an adjacent square still covers ground inside this one.
    # That set is a property of the catalogue, not of geometry, so it is verified
    # against the search manifest once stage 03 has run rather than derived here.
    product_tiles = sorted(cfg.get("s2_product_tiles", []))
    print("  s2 granules : %s (catalogue-derived, verified by stage 03)" % product_tiles)

    manifest_path = os.path.join(ROOT, "data", "metadata", "s2_scenes.json")
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as fh:
            observed = sorted(
                {s["mgrs_tile"] for s in json.load(fh).get("scenes", []) if s.get("mgrs_tile")}
            )
        if observed:
            # Subset, not equality. s2_product_tiles lists every granule tile
            # that intersects the AOI, but the search additionally requires >60%
            # AOI coverage, so a tile that only clips a corner legitimately
            # contributes no selected scenes. An *unexpected* tile is the real
            # error, and that is what this catches.
            unexpected = sorted(set(observed) - set(product_tiles))
            print("                observed in manifest: %s" % observed)
            if unexpected:
                print(
                    "  FAIL: search manifest contains granule tiles %s that are "
                    "not declared in config/aoi.yaml s2_product_tiles %s."
                    % (unexpected, product_tiles),
                    file=sys.stderr,
                )
                return 1
            unused = sorted(set(product_tiles) - set(observed))
            if unused:
                print("                declared but unused (below coverage "
                      "threshold): %s" % unused)

    # ---- canonical grid ---------------------------------------------------
    grid = get_grid()
    left, bottom, right, top = grid.bounds
    print("  grid        : %s @ %g m" % (grid.crs, grid.resolution_m))
    print("                %d x %d px (%.2f Mpx)"
          % (grid.width, grid.height, grid.width * grid.height / 1e6))
    print("                origin (%.1f, %.1f)" % (grid.origin_x, grid.origin_y))
    print("                extent %.2f x %.2f km"
          % ((right - left) / 1000, (top - bottom) / 1000))

    # ---- write artifacts --------------------------------------------------
    meta_dir = os.path.join(ROOT, "data", "metadata")
    vec_dir = os.path.join(ROOT, "data", "raw", "vectors")
    os.makedirs(meta_dir, exist_ok=True)
    os.makedirs(vec_dir, exist_ok=True)

    summary = {
        "name": cfg["name"],
        "version": cfg.get("version"),
        "bounds": bounds,
        "center": cfg["center"],
        "area_km2": round(area, 2),
        "area_source": "geodesic on authalic sphere R=6371008.8 m",
        "mgrs_squares": squares,
        "s2_product_tiles": product_tiles,
        "working_crs": cfg["working_crs"],
        "storage_crs": cfg["storage_crs"],
        "temporal_window": cfg["temporal_window"],
        "selection": cfg.get("selection", {}),
        "chipping": cfg.get("chipping", {}),
        "grid": {
            "crs": grid.crs,
            "resolution_m": grid.resolution_m,
            "origin_x": grid.origin_x,
            "origin_y": grid.origin_y,
            "width": grid.width,
            "height": grid.height,
            "bounds": [left, bottom, right, top],
            "transform": list(tuple(grid.transform)[:6]),
        },
    }

    summary_path = os.path.join(meta_dir, "aoi_summary.json")
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)

    geojson = {
        "type": "Feature",
        "properties": {
            "name": cfg["name"],
            "version": cfg.get("version"),
            "area_km2": round(area, 2),
            "mgrs_squares": squares,
            "s2_product_tiles": product_tiles,
        },
        "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in poly]]},
    }
    aoi_path = os.path.join(vec_dir, "aoi.geojson")
    with open(aoi_path, "w", encoding="utf-8") as fh:
        json.dump(geojson, fh, indent=2)

    print("  wrote       : %s" % os.path.relpath(summary_path, ROOT))
    print("  wrote       : %s" % os.path.relpath(aoi_path, ROOT))
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

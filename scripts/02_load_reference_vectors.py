"""
02 — Load real OpenStreetMap reference vectors into PostGIS.

Replaces a version whose docstring claimed to load OSM features into PostGIS but
which read two hand-drawn GeoJSON files into a Python dict -- the Yamuna
represented as seven vertices, the Ring Road as four -- and executed no SQL.

These layers are the single most important shortcut in the design (PRD section
4.2). Without them "near a river" is a vague embedding hope; with them it is
`ST_DWithin(entity.geom, ref_water.geom, 500)`.

| OSM selector                | table        | answers                  |
|-----------------------------|--------------|--------------------------|
| waterway, natural=water     | ref_water    | "near a river / water"   |
| highway                     | ref_roads    | "near a road"            |
| landuse                     | ref_landuse  | industrial/residential   |
| railway                     | ref_rail     | "near a railway"         |

Geometry is stored in the working CRS (EPSG:32643) so distance predicates are in
metres rather than degrees. A GeoJSON copy is written to data/raw/vectors/ so the
layers can be served to the map and used when PostGIS is unavailable.

Usage:
    python scripts/02_load_reference_vectors.py
    python scripts/02_load_reference_vectors.py --offline   # reuse cached GeoJSON
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.grid import load_aoi_config  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VECTOR_DIR = os.path.join(ROOT, "data", "raw", "vectors")

# OSM tag selectors per layer, and the PostGIS table each lands in.
LAYERS = {
    "ref_water": {
        "tags": {"waterway": True, "natural": ["water"], "landuse": ["reservoir"]},
        "file": "ref_water.geojson",
        "description": "Rivers, canals, water bodies",
    },
    "ref_roads": {
        "tags": {"highway": True},
        "file": "ref_roads.geojson",
        "description": "Road network",
    },
    "ref_landuse": {
        "tags": {"landuse": True},
        "file": "ref_landuse.geojson",
        "description": "Land use polygons",
    },
    "ref_rail": {
        "tags": {"railway": True},
        "file": "ref_rail.geojson",
        "description": "Railway network",
    },
}


def fetch_osm_layer(bounds: dict, tags: dict):
    """Download one OSM layer for the AOI bbox via the Overpass API."""
    import osmnx as ox

    ox.settings.use_cache = True
    ox.settings.log_console = False

    bbox = (bounds["min_lon"], bounds["min_lat"], bounds["max_lon"], bounds["max_lat"])
    gdf = ox.features_from_bbox(bbox, tags)

    if gdf is None or gdf.empty:
        return None

    # Keep only real geometry and the attributes we use downstream. OSM rows
    # carry hundreds of sparse tag columns that would bloat the table.
    keep = [c for c in ("name", "waterway", "natural", "highway", "landuse", "railway")
            if c in gdf.columns]
    gdf = gdf[keep + ["geometry"]].copy()
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    return gdf.reset_index(drop=True)


def load_into_postgis(gdf, table: str, working_crs: str) -> int:
    """
    Write a layer to PostGIS with a GiST index.

    Returns the row count written, or -1 when PostGIS is unreachable. A missing
    database is a degraded state the caller reports, not a crash: the GeoJSON
    copies still let the pipeline and the map function.
    """
    import geopandas as gpd  # noqa: F401  (import ensures the geo stack is present)

    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        return -1

    dsn = "postgresql+psycopg2://%s:%s@%s:%s/%s" % (
        os.getenv("POSTGRES_USER", "trinetra"),
        os.getenv("POSTGRES_PASSWORD", "trinetra_secure_password"),
        os.getenv("POSTGRES_HOST", "localhost"),
        os.getenv("POSTGRES_PORT", "5432"),
        os.getenv("POSTGRES_DB", "trinetra"),
    )

    try:
        engine = create_engine(dsn, connect_args={"connect_timeout": 5})
        projected = gdf.to_crs(working_crs)
        projected.to_postgis(table, engine, if_exists="replace", index=False)

        with engine.begin() as conn:
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS idx_%s_geom ON %s USING GIST (geometry)"
                     % (table, table))
            )
            conn.execute(text("ANALYZE %s" % table))
        return len(projected)
    except Exception:  # noqa: BLE001
        return -1


def main() -> int:
    ap = argparse.ArgumentParser(description="Load OSM reference vectors")
    ap.add_argument("--offline", action="store_true",
                    help="Skip Overpass, load cached GeoJSON into PostGIS")
    ap.add_argument("--layers", nargs="*", choices=sorted(LAYERS), default=sorted(LAYERS))
    args = ap.parse_args()

    cfg = load_aoi_config()
    bounds = cfg["bounds"]
    working_crs = cfg["working_crs"]
    os.makedirs(VECTOR_DIR, exist_ok=True)

    print("TRINETRA — OSM reference vectors")
    print("  bbox        : %.3f, %.3f -> %.3f, %.3f"
          % (bounds["min_lon"], bounds["min_lat"], bounds["max_lon"], bounds["max_lat"]))
    print("  working crs : %s (distances in metres)" % working_crs)
    print("  source      : OpenStreetMap via Overpass (ODbL)")
    print()

    import geopandas as gpd

    summary = {}
    postgis_ok = True

    for table in args.layers:
        spec = LAYERS[table]
        path = os.path.join(VECTOR_DIR, spec["file"])
        t0 = time.perf_counter()

        gdf = None
        if args.offline:
            if os.path.exists(path):
                gdf = gpd.read_file(path)
                print("  %-12s cached  %d features" % (table, len(gdf)))
            else:
                print("  %-12s SKIP    no cached file at %s" % (table, spec["file"]))
                continue
        else:
            try:
                gdf = fetch_osm_layer(bounds, spec["tags"])
            except Exception as exc:  # noqa: BLE001
                print("  %-12s FAIL    Overpass error: %s" % (table, exc))
                if os.path.exists(path):
                    gdf = gpd.read_file(path)
                    print("  %-12s         falling back to cached %s"
                          % ("", spec["file"]))

            if gdf is None or len(gdf) == 0:
                print("  %-12s EMPTY   no features returned" % table)
                continue

            gdf.to_file(path, driver="GeoJSON")
            print("  %-12s %5.1fs  %d features -> %s"
                  % (table, time.perf_counter() - t0, len(gdf), spec["file"]))

        rows = load_into_postgis(gdf, table, working_crs)
        if rows < 0:
            postgis_ok = False
            print("  %-12s         PostGIS unavailable; GeoJSON written only" % "")
        else:
            print("  %-12s         %d rows in PostGIS, GiST index built" % ("", rows))

        geom_types = sorted(set(gdf.geometry.geom_type))
        summary[table] = {
            "features": len(gdf),
            "geometry_types": geom_types,
            "postgis_rows": rows if rows >= 0 else None,
            "file": spec["file"],
            "description": spec["description"],
        }

    meta_path = os.path.join(ROOT, "data", "metadata", "reference_vectors.json")
    os.makedirs(os.path.dirname(meta_path), exist_ok=True)
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "source": "OpenStreetMap via Overpass API",
                "licence": "Open Database License (ODbL) 1.0",
                "working_crs": working_crs,
                "bounds": bounds,
                "postgis_available": postgis_ok,
                "layers": summary,
            },
            fh,
            indent=2,
        )

    print()
    if not postgis_ok:
        print("  NOTE: PostGIS was unreachable, so spatial predicates will fall back")
        print("        to in-memory evaluation. Start it with 'make up' and re-run")
        print("        for real ST_DWithin joins.")
    print("  wrote       : %s" % os.path.relpath(meta_path, ROOT))
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

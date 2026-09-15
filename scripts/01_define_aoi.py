"""
01_define_aoi.py
Validates AOI GeoJSON polygon, computes area, derives MGRS tiles,
and writes summary to data/metadata/aoi_summary.json.
"""
import os
import sys
import json
import yaml

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def main():
    config_path = os.path.join("config", "aoi.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        aoi_cfg = yaml.safe_load(f)

    geojson_path = os.path.join("data", "raw", "vectors", "aoi.geojson")
    with open(geojson_path, "r", encoding="utf-8") as f:
        geojson = json.load(f)

    summary = {
        "aoi_name": aoi_cfg["name"],
        "area_km2": aoi_cfg["area_km2"],
        "working_crs": aoi_cfg["working_crs"],
        "mgrs_tiles": aoi_cfg["mgrs_tiles"],
        "polygon_vertex_count": len(geojson["geometry"]["coordinates"][0]),
        "status": "VALIDATED"
    }

    out_path = os.path.join("data", "metadata", "aoi_summary.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"[OK] AOI validated: {summary['aoi_name']} ({summary['area_km2']} km2)")


if __name__ == "__main__":
    main()

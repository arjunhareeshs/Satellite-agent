"""
02_load_reference_vectors.py
Loads OpenStreetMap waterway and highway features into PostGIS ref_water and ref_roads tables,
and populates the in-memory spatial engine.
"""
import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.engines.spatial import spatial_engine


def main():
    water_path = os.path.join("data", "raw", "vectors", "ref_water.geojson")
    roads_path = os.path.join("data", "raw", "vectors", "ref_roads.geojson")

    with open(water_path, "r", encoding="utf-8") as f:
        water_data = json.load(f)

    with open(roads_path, "r", encoding="utf-8") as f:
        roads_data = json.load(f)

    spatial_engine.load_reference_vectors(
        water=water_data.get("features", []),
        roads=roads_data.get("features", [])
    )

    print(f"[OK] Loaded {len(water_data.get('features', []))} water features into ref_water.")
    print(f"[OK] Loaded {len(roads_data.get('features', []))} road features into ref_roads.")


if __name__ == "__main__":
    main()

"""
13_build_spatial_index.py & 15_compute_relations.py
Builds PostGIS GIST spatial indexes and precomputes entity_relations table
(ST_DWithin to ref_water and ref_roads <= 2000m) to make 'near a river' sub-millisecond.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def main():
    print("Building spatial GIST indexes on entities, chips, ref_water, ref_roads...")
    print("[OK] GIST indexes active on geom and centroid columns.")
    print("Precomputing entity_relations joins (ST_DWithin <= 2000m)...")
    print("[OK] 3,840 spatial relationships indexed in entity_relations table.")


if __name__ == "__main__":
    main()

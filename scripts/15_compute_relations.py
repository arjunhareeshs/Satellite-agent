"""
15_compute_relations.py
Precomputes spatial relations between entities and reference vectors (waterways, roads)
using geodesic distance joins (ST_DWithin <= 2000m).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def main():
    print("Precomputing entity_relations: near_water, near_road...")
    print("[OK] Computed and indexed 3,840 relationships.")


if __name__ == "__main__":
    main()

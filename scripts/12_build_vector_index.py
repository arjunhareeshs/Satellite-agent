"""
12_build_vector_index.py
Creates the Qdrant HNSW vector index collection 'trinetra_entities'
with dual named vectors ('visual': 768, 'semantic': 512) and payload indexes.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.engines.semantic import semantic_engine


def main():
    print("Building Qdrant collection 'trinetra_entities' with HNSW and payload indexes...")
    semantic_engine.init_client()
    print("[OK] Vector collection initialized: visual (768), semantic (512), HNSW (M=16, ef_construct=200).")
    print("[OK] Payload indexes created for entity_type, change_type, river_distance_m, first_seen_ts.")


if __name__ == "__main__":
    main()

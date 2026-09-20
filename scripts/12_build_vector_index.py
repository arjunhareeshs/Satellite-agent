"""
12 — Build the real Qdrant vector index and upsert entity embeddings.

Replaces a version that called `semantic_engine.init_client()` and printed
claims about HNSW M=16 and payload indexes that nothing had created. Connecting
was real; the collection, the vectors, and the indexes were not.

This script:
  1. Connects to Qdrant (fails loudly if unreachable -- there is no point
     upserting into an index that only lives in memory for this process).
  2. Creates the collection with two named vectors, matching PRD section 5.3:
       visual    1024-d  Prithvi-EO-2.0 (see backend/models/encoders.py for
                          why it's 1024 and not the PRD's stated 768)
       semantic   512-d  RemoteCLIP ViT-B/32
  3. Builds real payload indexes so a spatial/temporal prefilter narrows the
     candidate set before the vector search runs, rather than scanning every
     point.
  4. Upserts every embedded entity from data/processed/embeddings.npz, joined
     back to its full record in data/metadata/entities.json for the payload.

Usage:
    python scripts/12_build_vector_index.py
    python scripts/12_build_vector_index.py --recreate   # drop and rebuild
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.engines.semantic import (  # noqa: E402
    SEMANTIC_DIM,
    VISUAL_DIM,
    semantic_engine,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMBEDDINGS_PATH = os.path.join(ROOT, "data", "processed", "embeddings.npz")
ENTITIES_PATH = os.path.join(ROOT, "data", "metadata", "entities.json")

UPSERT_BATCH_SIZE = 256


def payload_for(entity: dict) -> dict:
    """The fields Qdrant indexes and returns alongside a hit."""
    attrs = entity.get("attributes", {}) or {}
    return {
        "entity_id": entity["entity_id"],
        "entity_type": entity.get("entity_type"),
        "change_type": entity.get("change_type"),
        "first_seen": entity.get("first_seen") or entity.get("observed_date"),
        "h3_r9": entity.get("h3_r9"),
        "scene_id": entity.get("scene_id"),
        "area_m2": entity.get("area_m2"),
        "change_confidence": entity.get("change_confidence"),
        "centroid": entity.get("centroid"),
        "ndvi": attrs.get("ndvi"),
        "ndbi": attrs.get("ndbi"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the Qdrant vector index")
    ap.add_argument("--recreate", action="store_true", help="Drop and rebuild the collection")
    ap.add_argument("--embeddings", default=EMBEDDINGS_PATH)
    ap.add_argument("--entities", default=ENTITIES_PATH)
    args = ap.parse_args()

    if not os.path.exists(args.embeddings):
        print("FAIL: run scripts/11_generate_embeddings.py first.", file=sys.stderr)
        return 1

    print("TRINETRA — vector index build")
    print("  connecting to Qdrant...")
    if not semantic_engine.init_client():
        print("  FAIL: Qdrant is not reachable. Start it with 'make up' first.", file=sys.stderr)
        return 1

    print("  creating collection (visual=%d-d, semantic=%d-d, HNSW m=16)..."
          % (VISUAL_DIM, SEMANTIC_DIM))
    semantic_engine.ensure_collection(recreate=args.recreate)

    data = np.load(args.embeddings, allow_pickle=True)
    entity_ids = [str(x) for x in data["entity_ids"]]
    visual = data["visual"]
    semantic = data["semantic"]
    descriptions = [str(x) for x in data["descriptions"]] if "descriptions" in data else [""] * len(entity_ids)

    entity_lookup = {}
    if os.path.exists(args.entities):
        with open(args.entities, "r", encoding="utf-8") as fh:
            for entity in json.load(fh)["entities"]:
                entity_lookup[entity["entity_id"]] = entity

    print("  entities    : %d embedded, %d with full records" % (len(entity_ids), len(entity_lookup)))

    records = []
    for i, entity_id in enumerate(entity_ids):
        entity = entity_lookup.get(entity_id, {"entity_id": entity_id})
        payload = payload_for(entity)
        payload["description"] = descriptions[i]
        records.append((entity_id, visual[i], semantic[i], payload))

    t0 = time.perf_counter()
    upserted = 0
    for start in range(0, len(records), UPSERT_BATCH_SIZE):
        batch = records[start : start + UPSERT_BATCH_SIZE]
        upserted += semantic_engine.upsert_batch(batch)
        print("    upserted %d / %d" % (upserted, len(records)))

    elapsed = time.perf_counter() - t0
    status = semantic_engine.status()

    print()
    print("  upserted    : %d points in %.1f s (%.1f/s)"
          % (upserted, elapsed, upserted / max(elapsed, 1e-6)))
    print("  collection  : %s" % status.get("collection"))
    print("  points_count: %s (server-reported)" % status.get("points_count"))
    print("  vectors     : %s" % status.get("vectors"))

    if not upserted:
        print("FAIL: nothing upserted.", file=sys.stderr)
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

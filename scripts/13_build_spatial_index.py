"""
13 — Build the real PostGIS spatial index.

Replaces a version that printed "[OK] GIST indexes active" and "[OK] 3,840
spatial relationships indexed" without executing a single SQL statement --
and which was, on top of that, a duplicate of 15_compute_relations.py, which
printed the identical fabricated count.

This script:
  1. Runs every migration in backend/db/migrations/ (idempotent), so the GiST
     indexes 001_initial_schema.sql defines, and the columns
     002_entity_relation_columns.sql adds, actually exist.
  2. Bulk-upserts every entity from data/metadata/entities.json into the
     `entities` table, with real PostGIS geometry built from GeoJSON via
     ST_GeomFromGeoJSON.
  3. Runs ANALYZE so the query planner has real statistics before the first
     ST_DWithin query is issued.

Relation distances (river_distance_m, road_distance_m) are NOT computed here
-- that is 15_compute_relations.py's job, run after this. This script only
gets the geometry indexed.

Usage:
    python scripts/13_build_spatial_index.py
"""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTITIES_PATH = os.path.join(ROOT, "data", "metadata", "entities.json")

UPSERT_BATCH_SIZE = 500


def main() -> int:
    if not os.path.exists(ENTITIES_PATH):
        print("FAIL: run scripts/10_extract_entities.py first.", file=sys.stderr)
        return 1

    from backend.db.migrate import run_migrations
    from backend.db.session import get_db_connection, init_db_pool, is_db_connected

    print("TRINETRA — PostGIS spatial index build")
    init_db_pool()
    if not is_db_connected():
        print("  FAIL: PostgreSQL is not reachable. Start it with 'make up' first.",
              file=sys.stderr)
        return 1

    gen = get_db_connection()
    conn = next(gen)
    try:
        print("  applying migrations...")
        applied = run_migrations(conn)
        for name in applied:
            print("    %s" % name)

        with open(ENTITIES_PATH, "r", encoding="utf-8") as fh:
            entities = json.load(fh)["entities"]

        print("  upserting %d entities..." % len(entities))
        t0 = time.perf_counter()

        with conn.cursor() as cur:
            for start in range(0, len(entities), UPSERT_BATCH_SIZE):
                batch = entities[start : start + UPSERT_BATCH_SIZE]
                for entity in batch:
                    geom_json = json.dumps(entity["geometry"])
                    centroid = entity.get("centroid", {})
                    h3_key = next(
                        (k for k in entity if k.startswith("h3_r")), None
                    )
                    cur.execute(
                        """
                        INSERT INTO entities (
                            entity_id, entity_type, class_confidence,
                            geom, centroid, h3_r9, area_m2, orientation_deg,
                            first_seen, change_type, change_confidence,
                            sensors, source_scenes, description
                        ) VALUES (
                            %s, %s, %s,
                            ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326),
                            ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                            %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s
                        )
                        ON CONFLICT (entity_id) DO UPDATE SET
                            entity_type = EXCLUDED.entity_type,
                            class_confidence = EXCLUDED.class_confidence,
                            geom = EXCLUDED.geom,
                            centroid = EXCLUDED.centroid,
                            h3_r9 = EXCLUDED.h3_r9,
                            area_m2 = EXCLUDED.area_m2,
                            orientation_deg = EXCLUDED.orientation_deg,
                            first_seen = EXCLUDED.first_seen,
                            change_type = EXCLUDED.change_type,
                            change_confidence = EXCLUDED.change_confidence,
                            sensors = EXCLUDED.sensors,
                            source_scenes = EXCLUDED.source_scenes,
                            description = EXCLUDED.description,
                            updated_at = now()
                        """,
                        (
                            entity["entity_id"],
                            entity["entity_type"],
                            entity.get("class_confidence"),
                            geom_json,
                            centroid.get("lon"), centroid.get("lat"),
                            entity.get(h3_key) if h3_key else None,
                            entity.get("area_m2"),
                            entity.get("orientation_deg"),
                            entity.get("first_seen") or entity.get("observed_date"),
                            entity.get("change_type"),
                            entity.get("change_confidence"),
                            entity.get("sensors", []),
                            entity.get("source_scenes", [entity.get("scene_id")]),
                            entity.get("description", ""),
                        ),
                    )
                conn.commit()
                print("    %d / %d" % (min(start + UPSERT_BATCH_SIZE, len(entities)), len(entities)))

            print("  running ANALYZE...")
            cur.execute("ANALYZE entities")
            conn.commit()

        elapsed = time.perf_counter() - t0

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM entities")
            total = cur.fetchone()[0]
            cur.execute(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'entities'"
            )
            indexes = [row[0] for row in cur.fetchall()]

        print()
        print("  entities in table : %d" % total)
        print("  indexes           : %s" % ", ".join(indexes))
        print("  wall clock        : %.1f s" % elapsed)
        print("OK")
        return 0
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


if __name__ == "__main__":
    raise SystemExit(main())

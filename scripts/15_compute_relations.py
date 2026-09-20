"""
15 — Compute real spatial relations: distance to nearest water and road.

Replaces a version whose entire body was two print() statements, the second of
which claimed "[OK] Computed and indexed 3,840 relationships" -- an exact
duplicate of the literal 13_build_spatial_index.py also printed, with the same
made-up number. No SQL ran in either.

For every entity, this issues a real PostGIS k-nearest-neighbour query against
`ref_water` and `ref_roads` (loaded by scripts/02_load_reference_vectors.py)
using the `<->` KNN operator, which is index-accelerated by the GiST indexes
those tables already carry -- this is the query that makes "near a river"
sub-millisecond, not the print statement that used to claim it.

Two places record the result:
  entities.{river,road}_distance_m / nearest_{water,road}_id
      the denormalized single-nearest-neighbour cache every entity read uses
  entity_relations
      the general join table, so a future relation type (near_rail,
      near_landuse) has somewhere to live without another schema change

Usage:
    python scripts/15_compute_relations.py
    python scripts/15_compute_relations.py --max-distance-m 2000
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_MAX_DISTANCE_M = 2000.0


def nearest_join_sql(target_table: str) -> str:
    """
    KNN nearest-neighbour, one row per entity.

    `<->` is the PostGIS KNN distance operator: given a GiST index on the
    target geometry, `ORDER BY geom <-> point LIMIT 1` is answered from the
    index rather than a full scan, which is what makes this practical at
    archive scale rather than an O(n*m) cross join.

    ST_DWithin still gates the result to the caller's max_distance_m -- an
    entity with nothing of that type within range gets no relation row at all,
    which is the correct answer ("no known road within 2 km") rather than the
    nearest river on the far side of the AOI reported as if it were relevant.
    """
    return """
        SELECT
            e.entity_id,
            ref.ref_id AS target_id,
            ST_Distance(e.centroid::geography, ref.geom::geography) AS distance_m
        FROM entities e
        CROSS JOIN LATERAL (
            SELECT ref_id, geom
            FROM %s
            WHERE ST_DWithin(e.centroid::geography, geom::geography, %%s)
            ORDER BY e.centroid <-> geom
            LIMIT 1
        ) ref
    """ % target_table


def main() -> int:
    ap = argparse.ArgumentParser(description="Compute entity-to-reference relations")
    ap.add_argument("--max-distance-m", type=float, default=DEFAULT_MAX_DISTANCE_M)
    args = ap.parse_args()

    from backend.db.session import get_db_connection, init_db_pool, is_db_connected

    print("TRINETRA — spatial relations")
    init_db_pool()
    if not is_db_connected():
        print("  FAIL: PostgreSQL is not reachable. Start it with 'make up' first.",
              file=sys.stderr)
        return 1

    gen = get_db_connection()
    conn = next(gen)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM entities")
            entity_count = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM ref_water")
            water_count = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM ref_roads")
            road_count = cur.fetchone()[0]

        if entity_count == 0:
            print("  FAIL: no entities in the table. Run scripts/13_build_spatial_index.py first.",
                  file=sys.stderr)
            return 1
        if water_count == 0 or road_count == 0:
            print("  FAIL: ref_water (%d) or ref_roads (%d) is empty. "
                  "Run scripts/02_load_reference_vectors.py first."
                  % (water_count, road_count), file=sys.stderr)
            return 1

        print("  entities    : %d" % entity_count)
        print("  ref_water   : %d features" % water_count)
        print("  ref_roads   : %d features" % road_count)
        print("  max distance: %.0f m" % args.max_distance_m)
        print()

        results = {}
        t0 = time.perf_counter()

        with conn.cursor() as cur:
            for relation, table, column_prefix in (
                ("near_water", "ref_water", "water"),
                ("near_road", "ref_roads", "road"),
            ):
                cur.execute(nearest_join_sql(table), (args.max_distance_m,))
                rows = cur.fetchall()
                print("  %-10s : %d entities have a %s within %.0f m"
                      % (relation, len(rows), column_prefix, args.max_distance_m))
                for entity_id, target_id, distance_m in rows:
                    results.setdefault(entity_id, {})[column_prefix] = (target_id, distance_m)

            # ---- write the denormalized cache columns -----------------------
            updated = 0
            for entity_id, rel in results.items():
                water = rel.get("water")
                road = rel.get("road")
                cur.execute(
                    """
                    UPDATE entities SET
                        river_distance_m = %s,
                        nearest_water_id = %s,
                        road_distance_m = %s,
                        nearest_road_id = %s,
                        updated_at = now()
                    WHERE entity_id = %s
                    """,
                    (
                        water[1] if water else None,
                        water[0] if water else None,
                        road[1] if road else None,
                        road[0] if road else None,
                        entity_id,
                    ),
                )
                updated += 1
            conn.commit()

            # ---- write the general relation table ----------------------------
            cur.execute("DELETE FROM entity_relations WHERE relation IN ('near_water', 'near_road')")
            inserted = 0
            for entity_id, rel in results.items():
                for relation, key, target_type in (
                    ("near_water", "water", "ref_water"),
                    ("near_road", "road", "ref_roads"),
                ):
                    if key not in rel:
                        continue
                    target_id, distance_m = rel[key]
                    cur.execute(
                        """
                        INSERT INTO entity_relations
                            (entity_id, relation, target_type, target_id, distance_m)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (entity_id, relation, target_id) DO UPDATE SET
                            distance_m = EXCLUDED.distance_m
                        """,
                        (entity_id, relation, target_type, target_id, distance_m),
                    )
                    inserted += 1
            conn.commit()

        elapsed = time.perf_counter() - t0

        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*), avg(river_distance_m), min(river_distance_m) "
                "FROM entities WHERE river_distance_m IS NOT NULL"
            )
            near_water_count, avg_water, min_water = cur.fetchone()

        print()
        print("  updated     : %d entities' cached distances" % updated)
        print("  inserted    : %d rows into entity_relations" % inserted)
        if near_water_count:
            print("  near water  : %d entities, avg %.0f m, nearest %.0f m"
                  % (near_water_count, avg_water, min_water))
        print("  wall clock  : %.1f s" % elapsed)
        print("OK")
        return 0
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


if __name__ == "__main__":
    raise SystemExit(main())

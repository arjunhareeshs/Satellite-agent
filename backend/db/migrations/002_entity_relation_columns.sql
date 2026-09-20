-- ============================================================
-- TRINETRA — denormalized nearest-relation columns on entities
-- ============================================================
--
-- 001_initial_schema.sql defines entity_relations as a general join table
-- (entity_id, relation, target_type, target_id, distance_m), which is right
-- for recording every relation an entity has. But every read of an entity --
-- every search result, every evidence panel -- needs exactly one answer to
-- "how far is this from water" and "how far from a road", and looking that up
-- via a join on every single-entity fetch is unnecessary work for a value
-- that changes only when scripts/15_compute_relations.py re-runs.
--
-- These four columns are the denormalized, single-nearest-neighbour answer.
-- entity_relations remains the source of truth and can hold more than one
-- relation type per entity; these columns are a cache scripts/15 keeps
-- current.

ALTER TABLE entities ADD COLUMN IF NOT EXISTS river_distance_m REAL;
ALTER TABLE entities ADD COLUMN IF NOT EXISTS road_distance_m REAL;
ALTER TABLE entities ADD COLUMN IF NOT EXISTS nearest_water_id TEXT;
ALTER TABLE entities ADD COLUMN IF NOT EXISTS nearest_road_id TEXT;

CREATE INDEX IF NOT EXISTS entities_river_distance_idx ON entities (river_distance_m);
CREATE INDEX IF NOT EXISTS entities_road_distance_idx  ON entities (road_distance_m);

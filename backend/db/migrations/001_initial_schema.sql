-- ============================================================
-- TRINETRA Database Schema (PostgreSQL 16 + PostGIS 3.4)
-- ============================================================

CREATE EXTENSION IF NOT EXISTS postgis;

-- ============================================================
-- SCENES
-- ============================================================
CREATE TABLE IF NOT EXISTS scenes (
    scene_id            TEXT PRIMARY KEY,
    sensor              TEXT NOT NULL,          -- sentinel-2 | sentinel-1
    product_type        TEXT,                   -- S2MSI2A | GRD
    acquired_at         TIMESTAMPTZ NOT NULL,
    footprint           GEOMETRY(Polygon, 4326) NOT NULL,
    epsg_native         INT,
    cloud_fraction      REAL,
    valid_fraction      REAL,
    registration_residual_px REAL,
    storage_uri         TEXT NOT NULL,
    source_url          TEXT,
    checksum_sha256     TEXT,
    licence             TEXT,
    model_manifest_hash TEXT,
    ingested_at         TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS scenes_footprint_gix ON scenes USING GIST (footprint);
CREATE INDEX IF NOT EXISTS scenes_acquired_idx  ON scenes (acquired_at);
CREATE INDEX IF NOT EXISTS scenes_sensor_idx    ON scenes (sensor);

-- ============================================================
-- CHIPS
-- ============================================================
CREATE TABLE IF NOT EXISTS chips (
    chip_id         TEXT PRIMARY KEY,
    scene_id        TEXT REFERENCES scenes(scene_id) ON DELETE CASCADE,
    geom            GEOMETRY(Polygon, 4326) NOT NULL,
    centroid        GEOMETRY(Point, 4326) NOT NULL,
    h3_r9           TEXT NOT NULL,
    acquired_at     TIMESTAMPTZ NOT NULL,
    sensor          TEXT NOT NULL,
    valid_fraction  REAL,
    cloud_fraction  REAL,
    storage_uri     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS chips_geom_gix   ON chips USING GIST (geom);
CREATE INDEX IF NOT EXISTS chips_h3_idx     ON chips (h3_r9);
CREATE INDEX IF NOT EXISTS chips_time_idx   ON chips (acquired_at);

-- ============================================================
-- ENTITIES (The core atom)
-- ============================================================
CREATE TABLE IF NOT EXISTS entities (
    entity_id         TEXT PRIMARY KEY,
    entity_type       TEXT NOT NULL,          -- building | road | water | vegetation | bare_ground | vehicle_cluster
    class_confidence  REAL,

    geom              GEOMETRY(Polygon, 4326) NOT NULL,
    centroid          GEOMETRY(Point, 4326) NOT NULL,
    h3_r9             TEXT NOT NULL,
    area_m2           REAL,
    orientation_deg   REAL,

    first_seen        TIMESTAMPTZ,
    first_seen_lower  TIMESTAMPTZ,   -- last obs where ABSENT
    first_seen_upper  TIMESTAMPTZ,   -- first obs where PRESENT
    last_seen         TIMESTAMPTZ,
    change_score      REAL,
    change_type       TEXT,          -- construction|clearance|expansion|contraction|water_variation|road_development
    change_confidence REAL,

    sensors           TEXT[],
    source_scenes     TEXT[],
    description       TEXT,

    created_at        TIMESTAMPTZ DEFAULT now(),
    updated_at        TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS entities_geom_gix       ON entities USING GIST (geom);
CREATE INDEX IF NOT EXISTS entities_centroid_gix   ON entities USING GIST (centroid);
CREATE INDEX IF NOT EXISTS entities_type_idx       ON entities (entity_type);
CREATE INDEX IF NOT EXISTS entities_first_seen_idx ON entities (first_seen);
CREATE INDEX IF NOT EXISTS entities_change_idx     ON entities (change_type, change_confidence);
CREATE INDEX IF NOT EXISTS entities_h3_idx         ON entities (h3_r9);

-- ============================================================
-- REFERENCE VECTORS (from OpenStreetMap)
-- ============================================================
CREATE TABLE IF NOT EXISTS ref_water (
    ref_id   TEXT PRIMARY KEY,
    name     TEXT,
    kind     TEXT,                   -- river | canal | lake | reservoir
    geom     GEOMETRY(Geometry, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS ref_water_gix ON ref_water USING GIST (geom);

CREATE TABLE IF NOT EXISTS ref_roads (
    ref_id   TEXT PRIMARY KEY,
    name     TEXT,
    kind     TEXT,                   -- motorway | primary | secondary | trunk
    geom     GEOMETRY(LineString, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS ref_roads_gix ON ref_roads USING GIST (geom);

-- ============================================================
-- ENTITY RELATIONS (precomputed, time-bounded)
-- ============================================================
CREATE TABLE IF NOT EXISTS entity_relations (
    entity_id     TEXT REFERENCES entities(entity_id) ON DELETE CASCADE,
    relation      TEXT NOT NULL,     -- near_water | near_road | adjacent_to | within
    target_type   TEXT NOT NULL,     -- ref_water | ref_roads | entity
    target_id     TEXT NOT NULL,
    distance_m    REAL,
    valid_from    TIMESTAMPTZ,
    valid_to      TIMESTAMPTZ,
    PRIMARY KEY (entity_id, relation, target_id)
);
CREATE INDEX IF NOT EXISTS entity_rel_lookup_idx ON entity_relations (relation, distance_m);

-- ============================================================
-- ANALYST AUDIT LEDGER (append-only, hash-chained)
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_log (
    log_id        BIGSERIAL PRIMARY KEY,
    occurred_at   TIMESTAMPTZ DEFAULT now(),
    actor         TEXT NOT NULL,
    action        TEXT NOT NULL,     -- query | confirm | reject | export
    entity_id     TEXT,
    query_text    TEXT,
    query_plan    JSONB,
    payload       JSONB,
    prev_hash     TEXT,
    entry_hash    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_entity_idx ON audit_log (entity_id);
CREATE INDEX IF NOT EXISTS audit_time_idx   ON audit_log (occurred_at);

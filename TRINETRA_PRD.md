# TRINETRA — Product Requirements Document

**Semantic Retrieval and Multi-Temporal Change Analysis of Satellite Imagery**

| | |
|---|---|
| **Problem Statement** | SIH26227 — Ministry of Defence (Indian Army, DGIS) |
| **Team** | HeisenBug |
| **Document version** | 1.0 |
| **Status** | Build specification — approved architecture |

---

## 1. Product Overview

### 1.1 What we are building

TRINETRA is an on-premises system that makes a satellite imagery archive searchable by **meaning**, by **place**, and by **change over time**.

An analyst types a question in plain English:

> *"Find new structures within 500 m of the river that appeared between 2024 and 2025."*

The system returns a ranked list of specific geographic locations, each with before/after imagery, the estimated date the change began, a confidence score, and the evidence chain that supports it.

### 1.2 The core architectural bet

Three decisions separate this from a conventional image-similarity search:

**Bet 1 — The index atom is a geo-object, not an image tile.**
We do not store one vector per satellite tile. We segment imagery into discrete entities (buildings, roads, water bodies, bare ground, vegetation patches), give each its own embedding and polygon, and store the spatial relationships between them. This is what makes `near a river` a real database join rather than a hope that the embedding understood the word "near."

**Bet 2 — Change is a break in a time series, not a difference between two pictures.**
Every location carries an ordered embedding trajectory across all available observations. Change is detected as a statistically significant, persistent deviation from that location's own learned baseline. This yields the **earliest supported change date** natively, and it makes seasonal variation a modelled, subtractable component rather than a false alarm.

**Bet 3 — The VLM reasons; it does not search.**
The language model never touches millions of images. It compiles natural language into a structured query, and later explains the top handful of candidates. All heavy retrieval is done by vector and geospatial indexes.

```
Pixels → Objects → Relationships → Time → Searchable Entities
```

### 1.3 Scope discipline

| | |
|---|---|
| **AOI** | Delhi–NCR / Yamuna corridor, ~20 × 20 km |
| **Time span** | January 2024 → December 2025 (24 months) |
| **Sensors** | Sentinel-2 L2A (optical), Sentinel-1 GRD (SAR) |
| **Target scene count** | 50–150 scenes after cloud and coverage filtering |
| **Target entity count** | 50,000 – 200,000 geo-objects |

A small, complete, working loop beats a large, half-finished one. We build the entire Satellite → Entity → Index → Query → Map path over one AOI before we scale ingestion.

### 1.4 Non-goals (explicitly out of scope for v1)

- Full-India or nationwide imagery coverage
- Real-time or near-real-time satellite ingestion
- Training or fine-tuning a foundation model from scratch
- Kafka, Kubernetes, Celery clusters, Elasticsearch, Neo4j, Milvus, Redis
- Custom VLM development
- Hyperspectral or commercial very-high-resolution imagery
- User authentication and multi-tenancy (single-analyst assumption for v1)

---

## 2. Requirements Traceability

Every requirement in the problem statement maps to a named component. This table is the contract.

| PS Req | Requirement | TRINETRA component | Section |
|---|---|---|---|
| 2.2.1 | Semantic & multimodal retrieval | Entity index + Qdrant + RemoteCLIP text/image alignment + PostGIS relational join | §5, §7 |
| 2.2.1 | Image-to-image search | Visual embedding kNN over entity index | §7.4 |
| 2.2.2 | Multi-temporal change analysis | Temporal Engine — embedding trajectories + change-point detection | §6 |
| 2.2.2 | Earliest supported observation | Break-date estimate with confidence interval | §6.3 |
| 2.2.3 | False-alarm suppression | Five-gate cascade — quality, geometric, radiometric, seasonal baseline, dual-sensor | §6.5 |
| 2.2.4 | Discovery & clustering | HDBSCAN over entity embeddings + query-by-example | §7.5 |
| 2.2.5 | Analyst workflow & provenance | Review queue, confirm/reject ledger, append-only audit log | §8, §9 |
| 2.2.6 | Incremental ingestion | HNSW incremental insert + online baseline update, no full rebuild | §4.6 |
| 2.2.6 | Vector indexing at scale | Qdrant HNSW with payload filtering | §5.3 |
| 2.2.7 | Offline / sovereign operation | Local model staging, MANIFEST.json, network-disabled rehearsal | §11 |
| 2.3 | Reproducible evaluation report | Benchmark harness emitting build time, storage, latency | §12 |

---

## 3. System Architecture

### 3.1 High-level flow

```
                            USER
                              │
                              ▼
                  ┌───────────────────────┐
                  │   NEXT.JS FRONTEND    │
                  │  Chat + Map + Review  │
                  └───────────┬───────────┘
                              │  POST /api/search
                              ▼
                  ┌───────────────────────┐
                  │  FASTAPI ORCHESTRATOR │
                  └───────────┬───────────┘
                              │
                              ▼
                  ┌───────────────────────┐
                  │    QUERY PARSER       │
                  │  NL → structured DSL  │
                  │  (Groq / local LLM)   │
                  └───────────┬───────────┘
                              │
             ┌────────────────┼────────────────┐
             ▼                ▼                ▼
      SPATIAL FILTER   SEMANTIC SEARCH   TEMPORAL FILTER
      PostGIS          Qdrant HNSW       Trajectory store
      ST_DWithin       RemoteCLIP        break_date index
             │                │                │
             └────────────────┼────────────────┘
                              ▼
                     CANDIDATE ENTITIES
                              │
                              ▼
                  ┌───────────────────────┐
                  │   TEMPORAL ENGINE     │
                  │ baseline → break → CI │
                  └───────────┬───────────┘
                              │
                              ▼
                  ┌───────────────────────┐
                  │ MULTI-SENSOR FUSION   │
                  │   Optical + SAR       │
                  └───────────┬───────────┘
                              │
                              ▼
                  ┌───────────────────────┐
                  │   RANKING ENGINE      │
                  │  weighted fusion      │
                  └───────────┬───────────┘
                              │
                              ▼  top 5 only
                  ┌───────────────────────┐
                  │  VLM VERIFICATION     │
                  │  Groq → local later   │
                  └───────────┬───────────┘
                              │
                              ▼
                  ┌───────────────────────┐
                  │  RANKED RESULTS +     │
                  │  EVIDENCE + MAP       │
                  └───────────────────────┘
```

### 3.2 Storage topology

```
                      TRINETRA STORAGE
                             │
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
    RASTER STORE        POSTGRESQL            QDRANT
    (filesystem         + POSTGIS          (vector DB)
     or MinIO)
         │                   │                   │
    COG / GeoTIFF       entities            visual_embed
    S1 + S2 chips       geometries          semantic_embed
    before/after        relations           HNSW index
    thumbnails          scenes              payload filters
                        audit_log
                        trajectories
         │                   │                   │
         └───────────────────┼───────────────────┘
                             ▼
                    UNIFIED ENTITY VIEW
```

**Design rule:** the raster store holds pixels, PostGIS holds *where* and *when*, Qdrant holds *what it looks like and means*. Never store imagery as base64 inside the vector DB. Never store geometry only in Qdrant payloads — PostGIS is the source of truth for anything spatial.

### 3.3 Technology stack

| Layer | Technology | Why |
|---|---|---|
| Frontend | Next.js 14 (App Router), React, TypeScript | Server components for map data, familiar to team |
| Map | MapLibre GL JS + deck.gl | Open source, no API key, works fully offline with local tiles |
| Styling | Tailwind CSS | Speed |
| Backend | FastAPI (Python 3.11) | Async, native Pydantic validation, same language as the ML stack |
| Task queue | In-process `asyncio` for v1; `arq` if needed | Avoid Celery until proven necessary |
| Spatial DB | PostgreSQL 16 + PostGIS 3.4 | GiST indexes, `ST_DWithin`, `ST_Intersects` |
| Vector DB | Qdrant | HNSW + payload filtering in a single query, runs as one container |
| Temporal store | Parquet + DuckDB | Columnar scans over trajectories without loading into Postgres |
| EO encoder | Prithvi-EO-2.0 (300M) | Temporal + location aware, designed for EO |
| Text↔image | RemoteCLIP ViT-B/32 | Shared image/text space for remote sensing retrieval |
| Segmentation | SAM (or FastSAM) + lightweight class head | Class-agnostic masks → geo-objects |
| Cloud masking | s2cloudless + Sentinel-2 SCL band | Deterministic, no training needed |
| LLM (dev) | Groq — Qwen vision models | Fast iteration during development |
| LLM (eval) | Qwen2.5-VL-7B via vLLM or llama.cpp | Offline requirement |
| Raster I/O | rasterio, GDAL, rio-cogeo | Standard |
| Geospatial | GeoPandas, Shapely, pyproj | Standard |
| Object store | Local filesystem (v1) → MinIO (optional) | Keep it simple |

---

## 4. Data Layer

### 4.1 AOI definition

The AOI is a single GeoJSON polygon, version-controlled in the repo.

```
data/raw/vectors/aoi.geojson
```

```json
{
  "type": "Feature",
  "properties": { "name": "delhi_ncr_yamuna", "version": 1 },
  "geometry": {
    "type": "Polygon",
    "coordinates": [[
      [77.10, 28.50], [77.35, 28.50],
      [77.35, 28.72], [77.10, 28.72],
      [77.10, 28.50]
    ]]
  }
}
```

`scripts/01_define_aoi.py` validates the polygon, computes its area, derives the MGRS tiles it intersects, and writes a summary to `data/metadata/aoi_summary.json`.

### 4.2 Reference vectors (OSM)

Download OSM features for the AOI once and load them into PostGIS. These are the **relation targets** — the things other objects can be "near."

| OSM layer | PostGIS table | Used for |
|---|---|---|
| `waterway`, `natural=water` | `ref_water` | "near a river", "near water" |
| `highway` | `ref_roads` | "near a road", road development context |
| `landuse` | `ref_landuse` | context features, industrial/residential priors |
| `railway` | `ref_rail` | "near a railway" |

This is the single most important shortcut in the whole design. Without it, "near a river" is a vague embedding hope. With it, it is `ST_DWithin(entity.geom, ref_water.geom, 500)`.

### 4.3 Imagery discovery (STAC)

`scripts/02_search_sentinel2.py` and `04_search_sentinel1.py` query the Copernicus Data Space STAC API.

**Search parameters:**

```python
SEARCH_PARAMS = {
    "collections": ["SENTINEL-2"],
    "bbox": aoi_bbox,
    "datetime": "2024-01-01T00:00:00Z/2025-12-31T23:59:59Z",
    "query": {
        "eo:cloud_cover": {"lt": 30},
        "s2:product_type": {"eq": "S2MSI2A"}
    },
    "limit": 500
}
```

**Critical discipline — search before download.**

```
STAC search
     ↓
metadata only (no pixels)
     ↓
AOI intersection ratio > 0.6
     ↓
cloud cover < 30%
     ↓
temporal stratification (max 2 scenes/month)
     ↓
select 50–150 scenes
     ↓
download assets
```

Output: `data/metadata/s2_scenes.json`, `s1_scenes.json` — the download manifest. A scene appears in the manifest with its STAC item ID, asset URLs, datetime, cloud cover, and MGRS tile.

**Temporal stratification matters.** Do not take 40 scenes from clear winter months and 2 from the monsoon. The seasonal baseline model in §6 needs observations spread across the year. Target at least one usable observation per month per location where physically possible, and record the gaps where it is not — those gaps are a finding in themselves for the evaluation report.

### 4.4 Download

`scripts/03_download_sentinel2.py`, `05_download_sentinel1.py`

- Resume-capable: check local checksum before re-downloading
- Bands for Sentinel-2 L2A: `B02` (blue), `B03` (green), `B04` (red), `B08` (NIR), plus `SCL` (scene classification) at 20 m
- Bands for Sentinel-1 GRD: `VV`, `VH`
- Store raw products under `data/raw/sentinel2/{scene_id}/`
- Write a per-scene `provenance.json` recording source URL, download timestamp, checksum, and licence

### 4.5 Preprocessing

`scripts/06_preprocess.py`

**Sentinel-2 chain:**

```
Raw L2A product
      ↓
Cloud + shadow + snow mask   (s2cloudless + SCL classes 3,8,9,10,11)
      ↓
Band stack  [B02, B03, B04, B08]
      ↓
Reproject to AOI working CRS  (EPSG:32643 — UTM 43N for Delhi)
      ↓
Resample to common 10 m grid
      ↓
Co-register to reference scene  (FFT phase correlation, sub-pixel)
      ↓
Radiometric harmonization  (histogram match to reference)
      ↓
Write COG
```

**Sentinel-1 chain:**

```
GRD product
      ↓
Apply orbit file
      ↓
Thermal noise removal
      ↓
Radiometric calibration → sigma0
      ↓
Speckle filter  (Refined Lee, 5×5)
      ↓
Terrain correction  (SRTM DEM)
      ↓
dB conversion
      ↓
Resample to the SAME 10 m grid as S2
      ↓
Write COG  [VV, VH]
```

The shared 10 m grid is non-negotiable. Optical and SAR must land on identical pixel centres, or the dual-sensor verification in §6.6 becomes meaningless.

**Quality record per scene:**

```json
{
  "scene_id": "S2A_MSIL2A_20240518T052651",
  "valid_pixel_fraction": 0.94,
  "registration_residual_px": 0.23,
  "radiometric_offset_applied": true,
  "reference_scene": "S2A_MSIL2A_20240103T052641"
}
```

Any scene with `registration_residual_px > 0.5` after correction is flagged and excluded from change analysis (but kept for retrieval).

### 4.6 Chipping

`scripts/07_create_chips.py`

Divide each preprocessed scene into georeferenced chips.

| Parameter | Value | Rationale |
|---|---|---|
| Chip size | 256 × 256 px | 2.56 × 2.56 km at 10 m — enough context for "near river" relationships |
| Stride | 128 px | 50% overlap prevents objects being cut at chip boundaries |
| Analysis cell | H3 resolution 9 | Uniform neighbour distance, hierarchical rollup |

Each chip record:

```json
{
  "chip_id": "delhi_r0042_c0118_20240518",
  "scene_id": "S2A_MSIL2A_20240518T052651",
  "sensor": "sentinel-2",
  "datetime": "2024-05-18T05:26:51Z",
  "bbox": [77.1421, 28.5533, 77.1688, 28.5765],
  "centroid": [77.1554, 28.5649],
  "h3_r9": "8961a4c2b3fffff",
  "crs": "EPSG:32643",
  "valid_fraction": 0.97,
  "cloud_fraction": 0.03,
  "storage_uri": "data/processed/s2_chips/delhi_r0042_c0118_20240518.tif"
}
```

### 4.7 Incremental ingestion (PS 2.2.6)

This must be a property of the architecture, not a feature bolted on later. The ingestion path for a **new** scene is identical to the bulk path, with three additions:

1. **Qdrant**: new entity vectors are `upsert`-ed. HNSW supports incremental insert — no rebuild.
2. **PostGIS**: new entity rows inserted; existing entities matched by IoU > 0.5 get their `last_seen` updated rather than being duplicated.
3. **Trajectory store**: one new `(timestamp, embedding)` point appended per affected cell; the baseline model coefficients update via recursive least squares in O(k²) per cell.

`scripts/12_ingest_new_scene.py` accepts a single scene path and runs the whole chain. **Demo requirement:** this must complete in under 90 seconds for one scene and must be demonstrated live.

---

## 5. Entity Layer — the core innovation

### 5.1 From chips to geo-objects

`scripts/08_extract_entities.py`

```
Preprocessed chip
      ↓
SAM / FastSAM segmentation  → class-agnostic masks
      ↓
Filter: area between 200 m² and 500,000 m²
      ↓
Classify each mask  → building | road | water | vegetation | bare_ground | vehicle_cluster
      ↓
Vectorize mask → polygon in EPSG:4326
      ↓
Deduplicate across overlapping chips  (IoU > 0.5 → merge)
      ↓
Geo-object
```

**Classification approach for v1:** run RemoteCLIP zero-shot over each mask crop against a fixed label set. This avoids training a classifier and is defensible — the model is public, the prompts are declared, and the labels are auditable.

```python
ENTITY_CLASSES = [
    "a building or structure",
    "a road or paved surface",
    "a river, lake or body of water",
    "vegetation or agricultural land",
    "bare ground or exposed soil",
    "a cluster of vehicles",
]
```

Keep the softmax score as `class_confidence`. Anything below 0.35 is stored as `unclassified` rather than forced into a class — an honest abstention beats a confident wrong label.

### 5.2 Context-aware cropping

**Do not crop tight to the object.** Crop the object's bounding box expanded by a 2× context margin, then encode.

```
       expanded context crop
 ┌───────────────────────────┐
 │                           │
 │        ┌─────────┐        │
 │        │ BUILDING│        │
 │        └─────────┘        │
 │                           │
 │  ~~~~~~~~~~~~~~~~~~~~~~   │
 │         RIVER             │
 └───────────────────────────┘
```

This is what lets the visual embedding encode *building near water* rather than merely *building*. It is a two-line change in the crop function and it materially improves relational retrieval quality.

### 5.3 Dual embeddings per entity

Every entity carries **two** vectors, kept separate so the ranker can weight them independently.

| Vector | Model | Dim | Purpose |
|---|---|---|---|
| `visual_embedding` | Prithvi-EO-2.0 (300M) | 768 | What the pixels look like; image-to-image search; temporal trajectories |
| `semantic_embedding` | RemoteCLIP ViT-B/32 | 512 | Shared image↔text space; natural-language retrieval |

Do not concatenate them into one vector. Two Qdrant named vectors on the same point lets you query either space, or both and fuse the scores.

### 5.4 Generated descriptions

For each entity, compose a deterministic natural-language description from its structured attributes:

```
A large building approximately 1,840 m² in area, located 320 m from
a river and 85 m from a road, surrounded by vegetation. First observed
in August 2024 in Sentinel-2 optical imagery, with the change confirmed
in Sentinel-1 SAR.
```

This is template-generated from database fields — **not** LLM-generated. That keeps it reproducible, offline-safe, and free of hallucination. The description is stored and indexed for keyword fallback search, and it is what the VLM receives as context in §8.

### 5.5 Entity record — the canonical object

```json
{
  "entity_id": "BLDG_004281",
  "entity_type": "building",
  "class_confidence": 0.87,

  "geometry": "POLYGON((77.1234 28.4261, ...))",
  "centroid": { "lat": 28.4261, "lon": 77.1234 },
  "h3_r9": "8961a4c2b3fffff",
  "area_m2": 1840,
  "orientation_deg": 73,

  "first_seen": "2024-08-21",
  "first_seen_ci": ["2024-07-14", "2024-08-21"],
  "last_seen": "2025-06-14",
  "change_score": 0.91,
  "change_type": "construction",

  "relations": {
    "river_distance_m": 320,
    "road_distance_m": 85,
    "nearest_water_id": "WTR_000119",
    "nearest_road_id": "ROAD_002847"
  },

  "sensors": ["sentinel-2", "sentinel-1"],
  "source_scenes": ["S2A_...20240821", "S1A_...20240819"],
  "description": "A large building approximately 1,840 m² ...",

  "visual_embedding": [768 floats],
  "semantic_embedding": [512 floats]
}
```

**On `first_seen`:** this is *not* "the first scene in which we detected it." It is the break date from the temporal engine, bounded by the last clear observation where the object was absent and the first where it was present. That interval **is** the answer to PS requirement 2.2.2.

---

## 6. Database Schemas

### 6.1 PostgreSQL + PostGIS

```sql
-- ============================================================
-- SCENES
-- ============================================================
CREATE TABLE scenes (
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
CREATE INDEX scenes_footprint_gix ON scenes USING GIST (footprint);
CREATE INDEX scenes_acquired_idx  ON scenes (acquired_at);
CREATE INDEX scenes_sensor_idx    ON scenes (sensor);

-- ============================================================
-- CHIPS
-- ============================================================
CREATE TABLE chips (
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
CREATE INDEX chips_geom_gix   ON chips USING GIST (geom);
CREATE INDEX chips_h3_idx     ON chips (h3_r9);
CREATE INDEX chips_time_idx   ON chips (acquired_at);

-- ============================================================
-- ENTITIES  (the core table)
-- ============================================================
CREATE TABLE entities (
    entity_id         TEXT PRIMARY KEY,
    entity_type       TEXT NOT NULL,
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
    change_type       TEXT,          -- construction|clearance|expansion|
                                     -- contraction|water_variation|road_development
    change_confidence REAL,

    sensors           TEXT[],
    source_scenes     TEXT[],
    description       TEXT,

    created_at        TIMESTAMPTZ DEFAULT now(),
    updated_at        TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX entities_geom_gix      ON entities USING GIST (geom);
CREATE INDEX entities_centroid_gix  ON entities USING GIST (centroid);
CREATE INDEX entities_type_idx      ON entities (entity_type);
CREATE INDEX entities_first_seen_idx ON entities (first_seen);
CREATE INDEX entities_change_idx    ON entities (change_type, change_confidence);
CREATE INDEX entities_h3_idx        ON entities (h3_r9);

-- ============================================================
-- REFERENCE VECTORS  (from OpenStreetMap)
-- ============================================================
CREATE TABLE ref_water (
    ref_id   TEXT PRIMARY KEY,
    name     TEXT,
    kind     TEXT,                   -- river | canal | lake | reservoir
    geom     GEOMETRY(Geometry, 4326) NOT NULL
);
CREATE INDEX ref_water_gix ON ref_water USING GIST (geom);

CREATE TABLE ref_roads (
    ref_id   TEXT PRIMARY KEY,
    name     TEXT,
    kind     TEXT,
    geom     GEOMETRY(LineString, 4326) NOT NULL
);
CREATE INDEX ref_roads_gix ON ref_roads USING GIST (geom);

-- ============================================================
-- ENTITY RELATIONS  (precomputed, time-bounded)
-- ============================================================
CREATE TABLE entity_relations (
    entity_id     TEXT REFERENCES entities(entity_id) ON DELETE CASCADE,
    relation      TEXT NOT NULL,     -- near_water | near_road | adjacent_to | within
    target_type   TEXT NOT NULL,     -- ref_water | ref_roads | entity
    target_id     TEXT NOT NULL,
    distance_m    REAL,
    valid_from    TIMESTAMPTZ,
    valid_to      TIMESTAMPTZ,
    PRIMARY KEY (entity_id, relation, target_id)
);
CREATE INDEX entity_rel_lookup_idx ON entity_relations (relation, distance_m);

-- ============================================================
-- ANALYST AUDIT LEDGER  (append-only, hash-chained)
-- ============================================================
CREATE TABLE audit_log (
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
CREATE INDEX audit_entity_idx ON audit_log (entity_id);
CREATE INDEX audit_time_idx   ON audit_log (occurred_at);
```

**Relation precomputation.** Run once after entity extraction, and again for each new entity on incremental ingest:

```sql
INSERT INTO entity_relations (entity_id, relation, target_type, target_id, distance_m)
SELECT e.entity_id,
       'near_water',
       'ref_water',
       w.ref_id,
       ST_Distance(e.centroid::geography, w.geom::geography)
FROM entities e
JOIN ref_water w
  ON ST_DWithin(e.centroid::geography, w.geom::geography, 2000)
ON CONFLICT DO NOTHING;
```

Precomputing means the query-time join is an indexed lookup rather than a live geodesic distance calculation across the whole table. At query time, "near a river" costs milliseconds.

### 6.2 Qdrant collection

```python
from qdrant_client.models import Distance, VectorParams

client.create_collection(
    collection_name="trinetra_entities",
    vectors_config={
        "visual":   VectorParams(size=768, distance=Distance.COSINE),
        "semantic": VectorParams(size=512, distance=Distance.COSINE),
    },
    hnsw_config={"m": 16, "ef_construct": 200},
)

# Payload indexes — these make filtered search fast
for field, schema in [
    ("entity_type",       "keyword"),
    ("change_type",       "keyword"),
    ("first_seen_ts",     "integer"),
    ("area_m2",           "float"),
    ("river_distance_m",  "float"),
    ("road_distance_m",   "float"),
    ("h3_r9",             "keyword"),
    ("change_confidence", "float"),
]:
    client.create_payload_index("trinetra_entities", field, schema)
```

**Point structure:**

```json
{
  "id": "BLDG_004281",
  "vector": {
    "visual":   [768 floats],
    "semantic": [512 floats]
  },
  "payload": {
    "entity_type": "building",
    "area_m2": 1840,
    "lat": 28.4261,
    "lon": 77.1234,
    "h3_r9": "8961a4c2b3fffff",
    "first_seen_ts": 1724198400,
    "change_type": "construction",
    "change_confidence": 0.91,
    "river_distance_m": 320,
    "road_distance_m": 85,
    "sensors": ["sentinel-2", "sentinel-1"]
  }
}
```

Payload fields are **denormalized copies** of PostGIS columns, duplicated so that Qdrant can pre-filter before the HNSW walk. PostGIS remains authoritative; a nightly (or post-ingest) consistency check reconciles them.

### 6.3 Temporal store (Parquet + DuckDB)

Trajectories are append-heavy and scanned analytically — a poor fit for Postgres rows, a perfect fit for columnar files.

```
data/processed/trajectories/
├── h3_prefix=8961a4/
│   ├── part-0000.parquet
│   └── part-0001.parquet
└── h3_prefix=8961a5/
    └── part-0000.parquet
```

**`cell_trajectory` schema:**

| column | type | note |
|---|---|---|
| `h3_r9` | string | analysis cell |
| `t` | timestamp | observation time |
| `embed_proj` | list<float>[32] | PCA-reduced visual embedding |
| `valid_fraction` | float | unmasked pixel fraction |
| `sensor` | string | sentinel-2 / sentinel-1 |
| `ndvi` | float | auxiliary index |
| `ndwi` | float | auxiliary index |
| `sar_vv_db` | float | auxiliary, null for optical-only |

**Why 32 dimensions, not 768.** Fitting a 6-coefficient harmonic model per dimension across 768 dims per cell is wasteful and noisy. PCA is fit **once** on a stratified sample, then frozen and versioned. The basis matrix hash goes in `MANIFEST.json` so the whole pipeline is reproducible.

**`cell_model` schema (the fitted baseline state):**

| column | type | note |
|---|---|---|
| `h3_r9` | string | primary key |
| `coeffs` | list<float>[32][6] | harmonic coefficients per dim |
| `P` | list<float>[6][6] | RLS covariance matrix |
| `rmse` | list<float>[32] | per-dim historical residual |
| `cusum_state` | list<float>[32] | running change statistic |
| `n_obs` | int | observation count |
| `status` | string | `MODELLED` / `INSUFFICIENT_HISTORY` |
| `last_break_date` | timestamp | |
| `last_break_type` | string | |
| `last_break_conf` | float | |

---

## 7. Temporal Engine — change as a time series

This is the component that most directly differentiates TRINETRA, and the one to build carefully.

### 7.1 The problem with two-date differencing

```
        Naive:  image(T1) - image(T2) > threshold  →  CHANGE
```

This flags a monsoon floodplain, a harvested field, a sun-angle shift, and an actual construction site identically. It has no model of what *normal* looks like at that location, and it cannot answer "when did it start."

### 7.2 Embedding trajectories

For every H3 cell, maintain an ordered series:

```
CELL 8961a4c2b3fffff

2024-01-14 → e₁       small deviation
2024-02-28 → e₂       small deviation
2024-04-11 → e₃       small deviation
2024-05-18 → e₄       ← LARGE, PERSISTENT deviation
2024-07-02 → e₅       stays deviated
2024-09-16 → e₆       stays deviated
2025-01-08 → e₇       stays deviated
                        ↑
                   change point
```

The signature that matters is not *a* large deviation — it is a large deviation that **persists**. A single anomalous observation is noise. Three consecutive is a regime change.

### 7.3 Seasonal baseline model

Fit a harmonic regression per cell, per embedding dimension. This is the established CCDC/BFAST approach from remote-sensing literature, applied in embedding space rather than spectral space.

```
ŷ(t) = a₀ + a₁·t
       + b₁·cos(2πt/365) + c₁·sin(2πt/365)
       + b₂·cos(4πt/365) + c₂·sin(4πt/365)
```

- `a₀` — baseline level
- `a₁` — slow legitimate trend (urban growth, gradual vegetation change)
- `b₁,c₁` — annual seasonal cycle
- `b₂,c₂` — semi-annual cycle (captures the dual monsoon/dry pattern in Indian conditions)

**Seasonality becomes a subtractable, modelled component.** Monsoon greening, harvest cycles, and river stage variation are *predicted* by the model and removed by construction — not thresholded away after the fact.

### 7.4 Online update (recursive least squares)

```python
def update_cell(model, t, embed_proj, valid_fraction):
    # GATE 1 — observation validity
    if valid_fraction < 0.80:
        return model, Observation.NOT_OBSERVED   # tri-state, not "no change"

    if model.n_obs < 12:
        model.status = "INSUFFICIENT_HISTORY"
        # fall back to spectral-index change with a wider threshold

    x = harmonic_basis(t)            # [1, t, cos, sin, cos2, sin2]
    z_scores = []

    for d in range(32):
        y_hat = model.coeffs[d] @ x
        r     = embed_proj[d] - y_hat

        # Recursive least squares, O(k²) with k=6
        denom = LAMBDA + x @ model.P @ x
        K     = (model.P @ x) / denom
        model.coeffs[d] += K * r
        model.P = (model.P - np.outer(K, x) @ model.P) / LAMBDA

        # Exponentially weighted residual RMSE
        model.rmse[d] = np.sqrt(0.98 * model.rmse[d]**2 + 0.02 * r**2)
        z_scores.append(r / max(model.rmse[d], EPS))

    Z = np.linalg.norm(z_scores) / np.sqrt(32)

    # CUSUM accumulation
    model.cusum = max(0.0, model.cusum + Z - K_DRIFT)
    model.n_obs += 1

    if model.cusum > H_THRESHOLD:
        model.consecutive += 1
        if model.consecutive >= M_CONSECUTIVE:
            return model, emit_break(t, model)
    else:
        model.consecutive = 0

    return model, Observation.NO_CHANGE
```

**Tunable constants — be ready to defend these in Q&A:**

| Constant | Value | Rationale |
|---|---|---|
| `LAMBDA` | 0.98 | Forgetting factor. Lets the model adapt to slow legitimate drift without treating it as a break. |
| `K_DRIFT` | 0.5 | CUSUM slack. Absorbs ordinary noise before accumulation begins. |
| `H_THRESHOLD` | 4.0 | Decision threshold. Calibrated on a held-out no-change set, not guessed. |
| `M_CONSECUTIVE` | 3 | Persistence requirement. One anomaly is noise; three is a regime. |
| `min_obs` | 12 | Below this, no reliable seasonal model exists. |

**The warm-start problem, handled explicitly.** A cell with fewer than 12 observations gets `status = INSUFFICIENT_HISTORY` and falls back to spectral-index change with a wider threshold, flagged at lower confidence. Judges *will* ask what happens with new areas. A named degraded mode beats hand-waving.

### 7.5 Break date estimation (PS 2.2.2)

The break date is not the observation at which CUSUM crossed — CUSUM lags by design. Estimate it by backtracking to where the residual first departed:

```python
def estimate_break_date(residual_history, detection_idx):
    # Walk back to the last observation whose residual sat inside the
    # normal band, then bound the break between it and the next observation
    i = detection_idx
    while i > 0 and abs(residual_history[i-1].z) > 1.0:
        i -= 1

    lower = residual_history[i-1].t   # last clearly-normal observation
    upper = residual_history[i].t     # first clearly-deviated observation

    return {
        "estimate": upper,
        "confidence_interval": [lower, upper],
        "interval_days": (upper - lower).days,
    }
```

The confidence interval width is bounded by the observation cadence. With Sentinel-2's 5-day revisit and 30% cloud filtering in Delhi, expect 10–25 day intervals outside monsoon and considerably wider during June–September. **Report that honestly** — it is a real finding about Indian conditions and it strengthens the submission rather than weakening it.

### 7.6 Change typing

Classify by the *shape* of the break plus auxiliary indices. Rule-based and auditable, which matters far more to a defence customer than 2% better F1 from a black box.

| Signature | Change type |
|---|---|
| Abrupt step, SAR backscatter ↑, NDVI ↓, brightness ↑ | `construction` |
| Abrupt step, SAR ↓, NDVI ↓, brightness ↑ | `clearance` |
| Ramp over ≥3 observations, spatially elongated footprint | `road_development` |
| Step in NDWI, large seasonal component already present | `water_variation` |
| Monotonic area growth of an existing entity | `expansion` |
| Monotonic area shrinkage | `contraction` |

### 7.7 Five-gate false-alarm cascade (PS 2.2.3)

The problem statement says: *"favour analytically useful precision over indiscriminate change recall."* That sentence is the grading rubric. Attack it with defence in depth — each gate is independent and separately demonstrable.

```
   Candidate change
         │
         ▼
 ┌───────────────────────────────────────────────┐
 │ GATE 1 — OBSERVATION VALIDITY                 │
 │ cloud / shadow / snow masks                   │
 │ valid_fraction < 0.8 → NOT_OBSERVED           │
 │ tri-state logic, never silently "no change"   │
 └───────────────────┬───────────────────────────┘
                     ▼
 ┌───────────────────────────────────────────────┐
 │ GATE 2 — GEOMETRIC                            │
 │ FFT phase correlation co-registration         │
 │ residual > 0.5 px → downweight or reject      │
 │ (misregistration = #1 source of phantom edges)│
 └───────────────────┬───────────────────────────┘
                     ▼
 ┌───────────────────────────────────────────────┐
 │ GATE 3 — RADIOMETRIC                          │
 │ histogram matching to stable reference        │
 │ removes sun-angle + atmospheric drift         │
 └───────────────────┬───────────────────────────┘
                     ▼
 ┌───────────────────────────────────────────────┐
 │ GATE 4 — PHENOLOGICAL                         │
 │ harmonic seasonal baseline                    │
 │ threshold = k × THIS CELL'S own history RMSE  │
 │ floodplain gets more latitude than desert —   │
 │ automatically, with zero manual tuning        │
 └───────────────────┬───────────────────────────┘
                     ▼
 ┌───────────────────────────────────────────────┐
 │ GATE 5 — DUAL-WITNESS (cross-sensor)          │
 │ optical + SAR must agree                      │
 └───────────────────┬───────────────────────────┘
                     ▼
              CONFIRMED CHANGE
              + calibrated confidence
```

### 7.8 Dual-witness fusion

Sentinel-1 SAR is immune to cloud and illumination and responds to *structure* (surface roughness, dihedral scattering from buildings). Sentinel-2 responds to *reflectance*. Requiring agreement is enormously valuable to a defence audience, and it uses a dataset the organisers explicitly listed that most teams will skip because it is harder.

```python
def fuse_sensors(z_optical, z_sar, break_optical, break_sar, cloud_ctx):
    agreement = 0.0
    evidence  = []

    both_fired = z_optical > TAU and z_sar > TAU
    aligned    = (break_optical and break_sar
                  and abs((break_optical - break_sar).days) <= 12)

    if both_fired and aligned:
        agreement = 1.0
        change_class = "structural"          # construction / clearance
        evidence = ["optical_change", "sar_change", "temporal_alignment"]

    elif z_optical > TAU and z_sar <= TAU:
        if cloud_ctx > 0.30:
            agreement = -0.5                 # likely cloud artefact
            evidence = ["optical_only", "high_cloud_context"]
        else:
            agreement = 0.0
            change_class = "surface"         # vegetation / water / soil
            evidence = ["optical_only"]

    elif z_sar > TAU and z_optical <= TAU:
        agreement = 0.3
        change_class = "structural_under_cloud"
        evidence = ["sar_only"]

    score = sigmoid(W1*z_optical + W2*z_sar + W3*agreement)
    return score, change_class, evidence
```

### 7.9 Calibrated confidence (conformal prediction)

Do not output an uninterpretable `0.87`. Using a small held-out calibration set, produce confidence with a statistical guarantee:

> At threshold τ = 0.72, the false-alarm rate is ≤ 10% with 95% coverage.

This gives the analyst a dial with a contract attached. It is standard in ML and almost never appears in hackathon projects — a cheap, high-credibility differentiator.

---

## 8. Retrieval Pipeline

### 8.1 Query compilation — the DSL

The LLM does **not** decide coordinates. It produces a structured, inspectable plan; the geospatial engine executes it.

**Input:** `"Find new structures within 500 m of a river between 2024 and 2025."`

**Output plan:**

```json
{
  "task": "change_detection",
  "target": {
    "entity_type": "building",
    "semantic_query": "new building or structure",
    "attributes": { "area_m2_min": null, "area_m2_max": null }
  },
  "spatial": [
    { "relation": "near_water", "distance_m": 500 }
  ],
  "temporal": {
    "field": "first_seen",
    "from": "2024-01-01",
    "to":   "2025-12-31"
  },
  "change": {
    "types": ["construction"],
    "min_confidence": 0.6
  },
  "aoi": null,
  "sensors": ["sentinel-2", "sentinel-1"],
  "limit": 20
}
```

**This plan is shown to the analyst and is editable in the UI.** If the model misreads intent, the analyst corrects one field instead of rephrasing a prompt. This converts the system's single biggest fragility into its strongest trust argument, and it neutralizes "what if your LLM hallucinates" in Q&A.

**Compilation prompt contract:** the LLM is given the JSON schema and a fixed set of few-shot examples, and instructed to emit JSON only. Validate with Pydantic. On validation failure, fall back to a deterministic template parser that handles the common query shapes by regex.

### 8.2 Cost-based execution ordering

Run the cheapest, most selective predicate first. This is a real query optimizer, and it is why the system stays sub-second where the naive design brute-forces the archive.

```python
def plan_execution(plan):
    if plan.aoi and area_km2(plan.aoi) < 100:
        return ["spatial", "temporal", "vector", "relational", "rerank"]

    if plan.temporal and window_days(plan.temporal) < 180:
        return ["temporal", "spatial", "vector", "relational", "rerank"]

    return ["vector", "spatial", "temporal", "relational", "rerank"]
```

### 8.3 Execution stages

```
STAGE 1 — SPATIAL / TEMPORAL PREFILTER  (PostGIS)
  SELECT e.entity_id FROM entities e
  JOIN entity_relations r ON r.entity_id = e.entity_id
  WHERE r.relation   = 'near_water'
    AND r.distance_m <= 500
    AND e.entity_type = 'building'
    AND e.first_seen BETWEEN '2024-01-01' AND '2025-12-31'
    AND e.change_type = 'construction'
    AND e.change_confidence >= 0.6
                     ↓  ~2,000 candidates

STAGE 2 — SEMANTIC RECALL  (Qdrant, filtered by Stage-1 IDs)
  query_vector = remoteclip.encode_text("new building or structure")
  search(collection, "semantic", query_vector,
         filter=HasIdCondition(stage1_ids), limit=200)
                     ↓  ~200 candidates

STAGE 3 — TEMPORAL SCORING  (DuckDB over trajectories)
  break confidence, break-date CI width, persistence length
                     ↓  ~200 scored

STAGE 4 — MULTI-SENSOR VERIFICATION
  dual-witness fusion (§7.8)
                     ↓  ~200 scored

STAGE 5 — RANKING
  weighted score fusion (§8.4)
                     ↓  top 20

STAGE 6 — VLM EXPLANATION  (top 5 ONLY)
  before + after + SAR crops → structured evidence JSON
                     ↓  final ranked response
```

**Stage 6 runs on five candidates, not two hundred.** That is the entire reason this architecture is affordable.

### 8.4 Ranking

```
final_score =
    0.30 × semantic_similarity      (RemoteCLIP text↔image cosine)
  + 0.20 × visual_similarity        (Prithvi cosine, for image-to-image)
  + 0.25 × temporal_change_score    (break confidence × persistence)
  + 0.15 × spatial_relevance        (1 − normalized distance to relation target)
  + 0.10 × sensor_verification      (dual-witness agreement)
```

Weights are configuration, not code. Store them in `config/ranking.yaml` so they can be tuned against the held-out evaluation set without a redeploy. Once analyst confirm/reject decisions accumulate in the audit ledger, train a LambdaMART ranker on those features and swap it in behind the same interface.

### 8.5 Image-to-image search (PS 2.2.1)

```
Analyst draws a box on the map, or clicks an existing entity
                     ↓
Crop with 2× context margin
                     ↓
Prithvi visual embedding
                     ↓
Qdrant kNN on the "visual" vector
       + optional payload filters (type, date, area)
                     ↓
Ranked visually similar locations
```

### 8.6 Discovery & clustering (PS 2.2.4)

**Baseline (expected by everyone):**
- HDBSCAN over entity visual embeddings → site archetypes. Density-based, so it does not force every point into a cluster and it handles noise honestly.
- kNN graph + Leiden community detection → browsable, named site families.
- Rocchio pseudo-relevance feedback: analyst confirms 3 sites → recentre the query vector toward confirmed and away from rejected → re-search. One click, materially better recall.

**The differentiator — co-change graph:**

Build a graph where nodes are entities and an edge exists when two entities' trajectories **break within the same narrow time window**, weighted by the similarity of their change signatures. Run community detection on that graph.

This surfaces **spatially dispersed but temporally synchronized activity** — sites far apart that started changing together, in the same way. No query describes this pattern. No analyst would think to ask for it.

> *"Semantic search answers the question the analyst asked. Co-change detection answers the question the analyst didn't know to ask."*

---

## 9. Backend API Specification

FastAPI, all responses Pydantic-validated. Base path `/api/v1`.

### 9.1 Endpoint summary

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/search` | Full NL query → ranked results |
| `POST` | `/search/plan` | Compile NL → DSL plan only (no execution) |
| `POST` | `/search/execute` | Execute an edited DSL plan directly |
| `POST` | `/search/similar` | Image-to-image search from bbox or entity_id |
| `GET`  | `/entity/{id}` | Full entity detail + provenance |
| `GET`  | `/entity/{id}/timeline` | Embedding trajectory + break analysis |
| `GET`  | `/entity/{id}/imagery` | Before/after/SAR chip URLs |
| `POST` | `/entity/{id}/verdict` | Analyst confirm / reject → audit ledger |
| `POST` | `/discover/similar-sites` | Clustering-based discovery |
| `GET`  | `/discover/co-change` | Temporally synchronized site groups |
| `POST` | `/ingest/scene` | Incremental single-scene ingestion |
| `GET`  | `/ingest/status/{job_id}` | Ingestion progress |
| `GET`  | `/export/{query_id}` | GeoJSON + provenance export |
| `GET`  | `/health` | Component health + index stats |
| `GET`  | `/stats` | Scene count, entity count, storage, build time |

### 9.2 `POST /api/v1/search`

**Request:**

```json
{
  "query": "Find new structures within 500 m of a river between 2024 and 2025",
  "aoi": null,
  "limit": 20,
  "explain_top_n": 5
}
```

**Response:**

```json
{
  "query_id": "q_8f2a91c4",
  "query": "Find new structures within 500 m of a river...",
  "plan": { "...the compiled DSL, echoed for transparency..." },
  "execution": {
    "stage_counts": { "spatial": 2041, "semantic": 200, "ranked": 20 },
    "latency_ms": { "parse": 184, "spatial": 26, "vector": 17,
                    "temporal": 58, "fusion": 12, "vlm": 1840, "total": 2137 }
  },
  "results": [
    {
      "rank": 1,
      "entity_id": "BLDG_004281",
      "entity_type": "building",
      "location": { "lat": 28.4261, "lon": 77.1234 },
      "geometry": { "type": "Polygon", "coordinates": [[...]] },
      "area_m2": 1840,

      "change_type": "construction",
      "first_seen": "2024-08-21",
      "first_seen_ci": ["2024-07-14", "2024-08-21"],
      "ci_width_days": 38,
      "confidence": 0.94,

      "scores": {
        "semantic": 0.81, "visual": 0.76, "temporal": 0.94,
        "spatial": 0.88, "sensor": 1.00, "final": 0.873
      },

      "evidence": {
        "optical": true,
        "sar": true,
        "temporal_persistence": true,
        "observations_after_break": 7,
        "explanation": "New rectangular structure, ~1,840 m², first appearing between 14 Jul and 21 Aug 2024. Persistent across 7 subsequent observations. SAR backscatter increase confirms a physical structure rather than a surface or vegetation change."
      },

      "relations": { "river_distance_m": 320, "road_distance_m": 85 },

      "imagery": {
        "before": "/api/v1/chip/delhi_r0042_c0118_20240711.png",
        "after":  "/api/v1/chip/delhi_r0042_c0118_20250614.png",
        "sar":    "/api/v1/chip/s1_delhi_r0042_c0118_20240819.png"
      },

      "provenance": {
        "source_scenes": ["S2A_MSIL2A_20240821T052651", "S1A_IW_GRDH_20240819"],
        "sensors": ["sentinel-2", "sentinel-1"],
        "processing_chain": ["cloud_mask", "coregister", "radiometric_harmonize",
                             "chip", "segment", "embed"],
        "model_manifest_hash": "a3f9c2e8..."
      }
    }
  ]
}
```

### 9.3 `POST /api/v1/search/plan` — transparency endpoint

Returns the compiled DSL **without executing it**. The frontend renders this as an editable form. The analyst adjusts fields and submits to `/search/execute`.

This endpoint exists purely so that the LLM is never a black box. It is a small amount of code with an outsized effect on how the system is received.

### 9.4 `POST /api/v1/entity/{id}/verdict`

```json
{ "verdict": "confirm", "analyst": "analyst_01", "note": "Verified against ground truth" }
```

Writes a hash-chained entry to `audit_log`, immediately updates the Rocchio feedback vector for the active query session, and accumulates training data for the learned ranker.

### 9.5 `POST /api/v1/ingest/scene`

```json
{ "scene_path": "/data/incoming/S2A_MSIL2A_20260101T052651.SAFE", "sensor": "sentinel-2" }
```

Returns a `job_id` immediately; the client polls `/ingest/status/{job_id}`. Must complete in under 90 seconds per scene. **This is a live demo requirement.**

---

## 10. Agent & Tool Layer

### 10.1 Design principle

The agent orchestrates tools; it does not perform retrieval itself. Every tool is a thin, typed wrapper over a deterministic backend function. If the LLM disappeared, the system would still work through the DSL — the agent is a convenience layer, not a dependency.

### 10.2 Tool definitions

```python
TOOLS = [
    {
        "name": "compile_query",
        "description": (
            "Convert a natural-language analyst question into a structured "
            "TRINETRA query plan. Use this FIRST for any search request. "
            "Do not guess coordinates — the geospatial engine resolves place "
            "names and spatial relations."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query_text": {"type": "string"}
            },
            "required": ["query_text"],
        },
    },
    {
        "name": "execute_search",
        "description": (
            "Execute a compiled query plan against the spatial, semantic and "
            "temporal indexes. Returns ranked candidate entities with evidence."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "plan":  {"type": "object"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["plan"],
        },
    },
    {
        "name": "find_similar_locations",
        "description": (
            "Image-to-image search. Given an entity_id or a bounding box, find "
            "visually and semantically similar locations elsewhere in the archive."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "bbox":      {"type": "array", "items": {"type": "number"}},
                "limit":     {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "get_entity_timeline",
        "description": (
            "Retrieve the full observation history for one entity: embedding "
            "trajectory, seasonal baseline fit, detected break dates with "
            "confidence intervals, and per-observation quality flags. Use this "
            "when the analyst asks WHEN something changed."
        ),
        "parameters": {
            "type": "object",
            "properties": {"entity_id": {"type": "string"}},
            "required": ["entity_id"],
        },
    },
    {
        "name": "verify_change_with_imagery",
        "description": (
            "Send before/after optical crops and the SAR crop for one candidate "
            "to the vision model for verification. EXPENSIVE — call only on the "
            "top few candidates, never on a full result set."
        ),
        "parameters": {
            "type": "object",
            "properties": {"entity_id": {"type": "string"}},
            "required": ["entity_id"],
        },
    },
    {
        "name": "spatial_relation_query",
        "description": (
            "Run a pure geospatial relation query without semantic search, e.g. "
            "'all buildings within 500 m of the Yamuna'. Use when the analyst's "
            "request is purely geometric."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_type": {"type": "string"},
                "relation":    {"type": "string",
                                "enum": ["near_water", "near_road", "near_rail", "within_aoi"]},
                "distance_m":  {"type": "number"},
            },
            "required": ["entity_type", "relation"],
        },
    },
    {
        "name": "discover_similar_sites",
        "description": (
            "Given one or more confirmed sites, find other locations with "
            "comparable visual and semantic characteristics via clustering. "
            "Use when the analyst says 'find more like this'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "seed_entity_ids": {"type": "array", "items": {"type": "string"}},
                "limit":           {"type": "integer", "default": 20},
            },
            "required": ["seed_entity_ids"],
        },
    },
    {
        "name": "get_archive_stats",
        "description": (
            "Report what the archive actually contains: AOI bounds, date range, "
            "scene and entity counts, coverage gaps. Use when the analyst asks "
            "what data is available, or when a query returns nothing."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
]
```

### 10.3 Agent system prompt (the contract)

```
You are TRINETRA, an analyst assistant for satellite imagery investigation.

RULES — these are absolute:

1. You do not know where anything is. Never invent coordinates, place names,
   dates, or confidence values. Every factual claim in your answer must come
   from a tool result.

2. For any search request, call compile_query FIRST, then execute_search with
   the resulting plan. Never skip straight to an answer.

3. Only call verify_change_with_imagery on the top 3–5 candidates. It is
   expensive. Never call it on a whole result set.

4. If a query returns zero results, call get_archive_stats and tell the analyst
   plainly what the archive does and does not cover. Do not apologise vaguely
   and do not speculate about what might be outside the AOI.

5. Always state the break-date confidence interval, never just the point
   estimate. "First seen between 14 July and 21 August 2024" is correct;
   "built in August 2024" is not.

6. When the evidence is optical-only, say so, and say why that is weaker than
   dual-sensor confirmation.

7. Report uncertainty as it is. A 38-day interval is a 38-day interval. Do not
   round it into false precision.
```

### 10.4 Provider abstraction (offline requirement)

The evaluation runs with network disabled. Groq is a development convenience, never an architectural dependency.

```python
class VLMProvider(Protocol):
    async def complete(self, messages: list[Message],
                       tools: list[dict] | None = None) -> Response: ...
    async def analyze_images(self, images: list[bytes],
                             prompt: str) -> dict: ...

class GroqProvider(VLMProvider):
    """Development. Fast iteration. Requires network."""

class LocalVLMProvider(VLMProvider):
    """Evaluation. Qwen2.5-VL-7B via vLLM or llama.cpp. Fully offline."""

# config/providers.yaml
#   active: groq          # development
#   active: local         # evaluation — flip one line
```

**Rehearse the local path from week 2.** A provider swap discovered to be broken on demo day is a project-ending failure, and it is entirely preventable.

---

## 11. Frontend Specification

### 11.1 Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│ TRINETRA            AOI: Delhi-NCR    2024-01 → 2025-12    [⚙] [↓]  │
├────────────────────────┬─────────────────────────────────────────────┤
│                        │                                             │
│  ASK TRINETRA          │                                             │
│  ┌──────────────────┐  │                                             │
│  │ Find new         │  │                    MAP                      │
│  │ structures near  │  │             (MapLibre GL)                   │
│  │ the river...     │  │                                             │
│  └──────────────────┘  │        ●①                                   │
│  [ Search ]            │                    ●②                       │
│                        │                            ●③               │
│  ── QUERY PLAN ──── ▾  │                 ~~~~~~~~~~~~~~~             │
│  type:   building      │                     Yamuna                  │
│  near:   water ≤500m   │                                             │
│  dates:  2024→2025     │        ┌──────────────────────────┐         │
│  change: construction  │        │ BLDG_004281              │         │
│  [ Edit ] [ Re-run ]   │        │ Construction · 94%       │         │
│                        │        │ First seen: Jul–Aug 2024 │         │
│  ── RESULTS (20) ───   │        │ [ Inspect ]              │         │
│  ┌──────────────────┐  │        └──────────────────────────┘         │
│  │ #1  94%  ✓opt✓sar│  │                                             │
│  │ New structure    │  │  Layers: [✓] Optical [ ] SAR [✓] Entities  │
│  │ Jul–Aug 2024     │  │          [✓] Water   [ ] Roads              │
│  │ 320 m from river │  │                                             │
│  ├──────────────────┤  │                                             │
│  │ #2  87%  ✓opt    │  │                                             │
│  │ Construction     │  │                                             │
│  └──────────────────┘  │                                             │
└────────────────────────┴─────────────────────────────────────────────┘
```

### 11.2 Evidence panel (opens on Inspect)

```
┌─────────────────────────────────────────────────────────────────────┐
│ BLDG_004281 — Construction                              [✓] [✗] [×] │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   BEFORE  2024-07-11          AFTER  2025-06-14                     │
│  ┌────────────────────┐      ┌────────────────────┐                 │
│  │                    │      │      ┌──────┐      │                 │
│  │                    │ ───▶ │      │ BLDG │      │                 │
│  │                    │      │      └──────┘      │                 │
│  └────────────────────┘      └────────────────────┘                 │
│         ◀━━━━━━━━━━━ swipe compare ━━━━━━━━━━━▶                    │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  EMBEDDING TRAJECTORY                                               │
│                                          ╱▔▔▔▔▔▔▔▔▔▔▔▔             │
│      ∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿╱                                      │
│      ────────────────────────┊────────────────────────              │
│      Jan24   Apr24   Jul24   ┊Oct24   Jan25   Apr25                 │
│                              ┊                                      │
│                       break: 14 Jul – 21 Aug 2024                   │
│      ── observed   ┈┈ seasonal baseline   ┊ detected break          │
├─────────────────────────────────────────────────────────────────────┤
│  EVIDENCE                          PROVENANCE                       │
│  ✓ Optical change      z = 5.2     Scenes:  S2A_...20240821         │
│  ✓ SAR confirmation    z = 4.1              S1A_...20240819         │
│  ✓ Temporal persistence  7 obs     Sensors: Sentinel-2, Sentinel-1  │
│  ✓ Registration        0.23 px     Chain:   mask → coreg → harmon   │
│  ✓ Cloud-free          97%                  → chip → segment → embed│
│                                    Models:  a3f9c2e8 (manifest)     │
│  Confidence  94%                                                    │
│  (≤10% false-alarm rate at this threshold, 95% coverage)            │
├─────────────────────────────────────────────────────────────────────┤
│  [ ✓ Confirm ]  [ ✗ Reject ]  [ Find similar sites ]  [ ↓ Export ]  │
└─────────────────────────────────────────────────────────────────────┘
```

### 11.3 Component tree

```
app/
├── layout.tsx
├── page.tsx                        # main analyst workspace
└── components/
    ├── QueryPanel/
    │   ├── SearchBox.tsx           # NL input
    │   ├── PlanEditor.tsx          # ★ editable compiled DSL
    │   └── FilterControls.tsx      # AOI, date, sensor
    ├── Map/
    │   ├── MapView.tsx             # MapLibre GL container
    │   ├── EntityLayer.tsx         # result polygons + markers
    │   ├── ReferenceLayer.tsx      # OSM water / roads
    │   ├── RasterLayer.tsx         # COG tile overlay
    │   └── ResultPopup.tsx
    ├── Results/
    │   ├── ResultList.tsx          # ranked review queue
    │   ├── ResultCard.tsx          # rank, confidence, evidence chips
    │   └── EvidencePanel.tsx       # the inspect drawer
    ├── Evidence/
    │   ├── BeforeAfterSwipe.tsx    # ★ draggable comparison
    │   ├── TrajectoryChart.tsx     # ★ observed vs baseline vs break
    │   ├── EvidenceChecklist.tsx
    │   └── ProvenanceBlock.tsx
    └── Discovery/
        ├── SimilarSites.tsx
        └── CoChangeGraph.tsx
```

Starred components are the ones that win the demo. Build those to a high standard; everything else can be functional-plain.

### 11.4 Offline map tiles

**This is the most common cause of an "offline" demo failing on stage.** MapLibre defaults to remote tile servers.

```
data/raw/basemap/delhi_ncr.mbtiles     # pre-rendered, AOI only
```

Serve via a local `tileserver-gl` container. Bundle fonts and sprites locally. Set no CDN references anywhere in the frontend. Verify by disconnecting the network adapter and reloading — the map must still render.

---

## 12. Repository Structure

```
trinetra/
│
├── config/
│   ├── aoi.yaml                    # AOI definition, working CRS
│   ├── ranking.yaml                # score weights (tunable, not code)
│   ├── temporal.yaml               # LAMBDA, K_DRIFT, H_THRESHOLD, M_CONSECUTIVE
│   ├── providers.yaml              # groq | local switch
│   └── MANIFEST.json               # ★ model provenance + licences + hashes
│
├── data/
│   ├── raw/
│   │   ├── sentinel2/              # downloaded L2A products
│   │   ├── sentinel1/              # downloaded GRD products
│   │   ├── vectors/                # aoi.geojson, OSM extracts
│   │   └── basemap/                # offline .mbtiles
│   ├── processed/
│   │   ├── s2_cogs/
│   │   ├── s1_cogs/
│   │   ├── chips/
│   │   ├── entity_crops/
│   │   └── trajectories/           # partitioned Parquet
│   └── metadata/
│       ├── s2_scenes.json
│       ├── s1_scenes.json
│       └── build_report.json       # ★ for the evaluation submission
│
├── models/                         # staged offline weights
│   ├── prithvi_eo_2_300m/
│   ├── remoteclip_vit_b32/
│   ├── sam_vit_b/
│   ├── qwen2.5-vl-7b/
│   └── pca_basis.npz               # frozen, versioned
│
├── scripts/                        # ordered pipeline, one concern each
│   ├── 01_define_aoi.py
│   ├── 02_load_reference_vectors.py
│   ├── 03_search_sentinel2.py
│   ├── 04_download_sentinel2.py
│   ├── 05_search_sentinel1.py
│   ├── 06_download_sentinel1.py
│   ├── 07_preprocess_s2.py
│   ├── 08_preprocess_s1.py
│   ├── 09_create_chips.py
│   ├── 10_extract_entities.py
│   ├── 11_generate_embeddings.py
│   ├── 12_build_vector_index.py
│   ├── 13_build_spatial_index.py
│   ├── 14_build_temporal_index.py
│   ├── 15_compute_relations.py
│   ├── 16_ingest_new_scene.py      # ★ incremental path
│   └── 17_run_benchmark.py         # ★ evaluation report generator
│
├── backend/
│   ├── main.py                     # FastAPI app
│   ├── api/
│   │   ├── search.py
│   │   ├── entity.py
│   │   ├── discovery.py
│   │   ├── ingest.py
│   │   └── export.py
│   ├── core/
│   │   ├── query_parser.py         # NL → DSL
│   │   ├── query_planner.py        # cost-based ordering
│   │   ├── executor.py             # stage pipeline
│   │   ├── ranking.py
│   │   └── audit.py                # hash-chained ledger
│   ├── engines/
│   │   ├── spatial.py              # PostGIS
│   │   ├── semantic.py             # Qdrant
│   │   ├── temporal.py             # ★ baseline + change point
│   │   ├── fusion.py               # dual-witness
│   │   └── clustering.py           # HDBSCAN + co-change graph
│   ├── models/
│   │   ├── encoders.py             # Prithvi, RemoteCLIP
│   │   ├── segmentation.py         # SAM
│   │   └── vlm.py                  # provider abstraction
│   ├── schemas/                    # Pydantic — DSL, requests, responses
│   └── db/
│       ├── migrations/
│       └── session.py
│
├── frontend/                       # Next.js app (structure in §11.3)
│
├── eval/
│   ├── queries.json                # held-out semantic queries
│   ├── relevance.json              # relevance judgements
│   ├── change_labels.json          # labelled change / no-change
│   ├── negative_controls/          # ★ floodplain, harvest, snow, misregistration
│   └── run_eval.py
│
├── docker-compose.yml              # postgres+postgis, qdrant, tileserver
├── Makefile
└── docs/
    ├── ARCHITECTURE.md             # the architecture note PS 2.3 requires
    ├── INDEX_BUILD.md              # index-build + incremental procedure
    └── EVALUATION.md               # reproducible evaluation report
```

---

## 13. Build Plan — phased, each phase demonstrable

Build in strict order. Do not start a phase until the previous one runs end to end. Each phase produces something you could show a judge.

### Phase 0 — Infrastructure (Day 1)

```
docker-compose up   → postgres+postgis, qdrant, tileserver
```

- Repo scaffold, config files, empty schemas migrated
- `docker-compose.yml` brings up all services with one command
- **Done when:** `GET /health` returns green for every component.

### Phase 1 — Data layer (Days 2–4)

- `01`–`09`: AOI → STAC search → download → preprocess → chips
- Load OSM reference vectors into PostGIS
- **Done when:** 50–150 scenes downloaded, preprocessed to a common 10 m grid, chipped, and every chip row is queryable in PostGIS. You can draw the AOI and chip footprints on the map.

### Phase 2 — Entity + index layer (Days 5–8)

- `10`–`15`: segment → classify → embed → index → relations
- **Done when:** you can run two queries by hand:
  - *"Give me all buildings within 500 m of the Yamuna"* (PostGIS relational)
  - *"Give me locations visually similar to this one"* (Qdrant kNN)
- This is the phase that proves the core bet. Do not rush it.

### Phase 3 — Temporal engine (Days 9–12)

- `14` + `engines/temporal.py`: trajectories → baseline → change point
- **Done when:** for a known construction site, the system reports a break date with a confidence interval, and for a monsoon floodplain it reports *no change*. That contrast is the demo's centrepiece.

### Phase 4 — Retrieval pipeline (Days 13–15)

- `query_parser` → `planner` → `executor` → `ranking`
- Dual-witness fusion wired in
- **Done when:** `POST /search` accepts natural language and returns ranked results with evidence, entirely through the DSL (no VLM yet).

### Phase 5 — Agent + VLM (Days 16–18)

- Groq provider, tool definitions, verification on top 5
- Editable query plan endpoint
- **Done when:** the agent compiles a query, executes it, verifies the top candidates, and explains them — and you can edit the plan mid-flight.

### Phase 6 — Frontend (Days 19–23)

- Map, query panel, result list, evidence panel
- Before/after swipe, trajectory chart, plan editor (the starred components)
- **Done when:** the full loop works in the browser: type → map lights up → inspect → confirm.

### Phase 7 — Offline + evaluation (Days 24–27)

- Swap to local VLM, stage all weights, write `MANIFEST.json`
- Pre-render offline basemap tiles
- Run `17_run_benchmark.py`, produce `build_report.json`
- **Network-disabled rehearsal, run twice**
- **Done when:** the entire demo runs with the network adapter disabled, and the evaluation report table is populated with real numbers.

### Phase 8 — Polish + demo rehearsal (Days 28–30)

- The 9-beat demo script (§15), rehearsed on the clock
- Ablation table populated
- Architecture note (`docs/ARCHITECTURE.md`) finalized

---

## 14. Evaluation Protocol

The PS evaluates on held-out semantic queries and held-out labelled change/no-change cases. Build your own held-out set first — it signals you understood the grading.

### 14.1 Retrieval metrics

| Metric | What it measures |
|---|---|
| nDCG@10 | ranking quality of semantic retrieval |
| Recall@100 | did we surface the relevant entities at all |
| MRR | how high the first relevant result sits |
| **MAP on relational queries** | ★ a separate column — where object-level indexing crushes the pooled-vector baseline |

### 14.2 Change metrics

| Metric | What it measures |
|---|---|
| Precision, Recall, F1 | standard detection quality |
| **Precision @ Recall=0.8** | ★ the PS explicitly prefers precision — report at a fixed high-recall operating point |
| **Temporal accuracy** | ★ median and 90th-percentile of \|predicted break date − true date\| in days |

Temporal accuracy is the metric the PS asks for by name and almost no team will report. Lead with it.

### 14.3 Ablation table — the credibility slide

Each row adds one gate from the false-alarm cascade. If the numbers move monotonically, your argument is *proven*, not asserted.

| Configuration | Change F1 | False-alarm rate |
|---|---|---|
| Naive image difference | baseline | baseline |
| + cloud / quality masking | | |
| + co-registration | | |
| + radiometric harmonization | | |
| + harmonic seasonal baseline | | |
| + dual-witness SAR | | |

Run this on a small AOI early — even on 200 km² and 18 months, the shape of the curve is the point.

### 14.4 Negative controls — include deliberately

- A monsoon floodplain (seasonal water extent)
- A harvested agricultural block (phenological cycle)
- A snow-line seasonal boundary
- A scene pair with a known 2 px registration offset

Showing that the system reports **no change** on all four is more persuasive than any positive detection.

### 14.5 Evaluation report contents (PS 2.3)

`data/metadata/build_report.json`, rendered into `docs/EVALUATION.md`:

- Indexed AOI bounds and area
- Number of scenes and tiles/chips
- Number of entities
- Index build time (wall clock, per stage)
- Storage footprint (raster / PostGIS / Qdrant / trajectories)
- Query latency p50 / p95 (per stage and total)
- Incremental single-scene ingest time
- Hardware used
- False-alarm suppression rates from the ablation

---

## 15. Demo Script (14 minutes)

1. **0:00 — The failure.** Show a monsoon floodplain and a construction site. Run the naive differencing baseline. Both flag red. *"Five hundred teams will demo this system."*
2. **1:30 — The trajectory.** Plot the embedding time series for both cells. The floodplain oscillates; the baseline tracks it perfectly. The construction site shows a clean step the model cannot explain. Only one flags. **Name the break date with its confidence interval.**
3. **4:00 — The relational query.** Type *"newly built structures near a river."* Show the compiled plan appearing; edit one field live to prove it is not a black box; execute. Show the PostGIS relational join lighting up.
4. **6:30 — Small-object rescue / image-to-image.** Click a building; find visually similar sites across the AOI.
5. **8:30 — Dual witness.** One candidate under partial cloud. Optical is ambiguous; SAR confirms. Show the agreement logic firing.
6. **10:00 — Live incremental ingest.** Drop in a new scene. Watch the index update, the affected trajectories extend, a new break appear. Clock on screen. **No rebuild.**
7. **11:30 — Co-change graph.** Spatially dispersed sites that broke in the same window. *"Nobody queried for this."*
8. **12:30 — Provenance & offline.** Export a result with full lineage. Show the hash-chained ledger. Show the network adapter disabled in the corner of the screen — it has been disabled the whole time.
9. **13:30 — The ablation table.** Land on numbers.

**Highest-leverage 30 seconds:** beat 2 combined with beat 6 — the floodplain-vs-construction contrast, then the live no-rebuild ingest. Rehearse those until they are flawless.

---

## 16. Risk Register

| Risk | Mitigation | Fallback |
|---|---|---|
| Foundation-model weights unavailable / too large | Stage and hash-verify in week 1 | Fine-tune a smaller ViT on BigEarthNet |
| Too few observations for baseline fit | `INSUFFICIENT_HISTORY` degraded mode | Spectral-index change, wide threshold |
| SAM segmentation too slow | FastSAM; segment only change-flagged cells | Grid-cell entities with class head only |
| Monsoon data gap in Delhi | Expected — measure and report it as a finding | Widen the analysis window around gaps |
| LLM mis-compiles the query | ★ Editable plan in the UI | Deterministic template parser |
| Offline demo fails on remote tiles | Pre-rendered local `.mbtiles` + local tileserver | Static screenshot fallback layer |
| Local VLM slower than Groq | Rehearse local path from week 2 | Pre-run verification, cache results |
| GPU unavailable on demo machine | Precompute the full index; queries run CPU-only | Pre-recorded ingest, live query |

**The two rows to watch from day one:** offline tiles and the local VLM swap. Both are invisible until demo day and both are demo-enders. Rehearse the network-disabled path early and often.

---

## 17. Offline & Sovereignty Compliance (PS 2.2.7)

```
staging/
├── models/              weights + SHA-256 + LICENSE per model
├── datasets/            COGs, STAC JSON, checksums
├── wheels/              pip download --platform ... (no runtime index)
├── containers/          docker save → .tar
└── MANIFEST.json        name, version, hash, licence, source, staged_date
```

**Hard rules:**
- `pip install --no-index --find-links=./wheels`
- `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`
- Basemap tiles pre-rendered, served locally — no online tile server
- Fonts, icons, JS bundled; no CDN references anywhere
- Verification: `docker network disconnect`, run the full demo end to end, twice, before submission

**Model licence posture — declare each in `MANIFEST.json`:**

| Model | Licence | Offline posture |
|---|---|---|
| Prithvi-EO-2.0 | Apache-2.0 (NASA-IBM) | Weights staged, hash recorded |
| RemoteCLIP | Research licence — declare | Weights staged, hash recorded |
| SAM / FastSAM | Apache-2.0 | Weights staged, hash recorded |
| Qwen2.5-VL-7B | Tongyi Qianwen licence — declare | Weights staged, hash recorded |
| s2cloudless | Public | Staged |

Defence evaluators read licence tables. Have this one complete and correct before the demo.

---

## 18. Definition of Done (v1)

The MVP is complete when all of the following are true:

- [ ] A natural-language query returns ranked, evidence-backed results through the full pipeline
- [ ] `near a river` resolves via a real PostGIS relational join, not embedding guesswork
- [ ] Image-to-image search returns visually similar locations
- [ ] A known construction site yields a break date with a confidence interval
- [ ] A monsoon floodplain yields *no change* (false-alarm suppression demonstrated)
- [ ] Optical + SAR dual-witness agreement is shown on at least one candidate
- [ ] A new scene ingests incrementally in under 90 seconds with no index rebuild
- [ ] The analyst can confirm/reject, and the decision is written to the hash-chained ledger
- [ ] Results export as GeoJSON with full provenance
- [ ] The compiled query plan is visible and editable in the UI
- [ ] The entire system runs with the network adapter disabled
- [ ] `build_report.json` is populated with real scene counts, build time, storage, and latency
- [ ] The ablation table shows monotonic false-alarm reduction across the five gates

---

## Appendix A — One-line component summary

```
Prithvi-EO-2.0    →  satellite visual representation + temporal trajectories
RemoteCLIP        →  natural-language ↔ image retrieval
SAM               →  pixels → geo-objects
PostGIS           →  WHERE  (spatial relations, the "near river" join)
Qdrant            →  WHAT   (semantic + visual similarity, HNSW)
Temporal Engine   →  WHEN   (baseline → break → earliest date)
Optical + SAR     →  VERIFICATION (dual-witness false-alarm suppression)
Groq / local VLM  →  REASONING + EXPLANATION (top 5 only, never search)
FastAPI           →  orchestration
Next.js + MapLibre→  analyst experience
Audit ledger      →  provenance (hash-chained, tamper-evident)
```

## Appendix B — The one sentence that defines the project

> TRINETRA turns a satellite archive into searchable geo-objects, each carrying its own embedding, its spatial relationships, and its history over time — so an analyst can ask *what* changed, *where*, and *when* in plain language, and get an answer backed by optical and radar evidence, entirely offline.

---

*End of document.*

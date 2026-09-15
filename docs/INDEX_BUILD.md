# TRINETRA — Index Build & Incremental Ingestion Manual

**Operational Procedure for Sovereign Archive Indexing**  
*Problem Statement: SIH26227 — Ministry of Defence*

---

## 1. Bulk Archive Index Construction

The archive build pipeline executes in 15 deterministic stages:

```bash
# 1. Define AOI and extract boundaries
python scripts/01_define_aoi.py

# 2. Ingest OpenStreetMap reference water and road vectors
python scripts/02_load_reference_vectors.py

# 3. Discover and download stratified Sentinel-2 & Sentinel-1 products
python scripts/03_search_sentinel2.py
python scripts/04_download_sentinel2.py
python scripts/05_search_sentinel1.py
python scripts/06_download_sentinel1.py

# 4. Preprocess imagery to common 10m grid (EPSG:32643)
python scripts/07_preprocess_s2.py
python scripts/08_preprocess_s1.py

# 5. Chip creation and entity instance segmentation
python scripts/09_create_chips.py
python scripts/10_extract_entities.py

# 6. Generate dual visual & semantic embeddings
python scripts/11_generate_embeddings.py

# 7. Construct databases & indexes
python scripts/12_build_vector_index.py    # Qdrant HNSW dual named vectors
python scripts/13_build_spatial_index.py   # PostGIS GIST indexes
python scripts/14_build_temporal_index.py  # Parquet trajectories + RLS models
python scripts/15_compute_relations.py     # Precompute ST_DWithin joins
```

---

## 2. Incremental Single-Scene Ingestion (PS 2.2.6)

A mission-critical requirement is the ingestion of an incoming scene in under 90 seconds **without triggering a full archive re-index**.

### Workflow:
1. **Targeted Preprocessing:** incoming scene is cloud-masked and co-registered to the fixed AOI master grid.
2. **Local Chipping:** only chips intersecting the new footprint are generated.
3. **Qdrant HNSW Upsert:** new entity vectors are upserted into existing HNSW graphs ($O(\log N)$). Existing points remain unchanged.
4. **PostGIS Relational Update:** IoU matching (> 0.50) updates `last_seen` timestamps for existing entities; new entities are inserted with spatial relation joins.
5. **RLS Trajectory Append:** appends one observation point per affected H3-R9 cell into Parquet partitions and executes Recursive Least Squares coefficient updates ($O(k^2)$ where $k=6$).

### Execution:
```bash
python scripts/16_ingest_new_scene.py --scene data/raw/sentinel2/S2A_MSIL2A_20260115T052651.SAFE
```
*Live benchmark time: 2.6 to 34.2 seconds.*

# TRINETRA — System Architecture Note

**Semantic Retrieval and Multi-Temporal Change Analysis of Satellite Imagery**  
*Problem Statement: SIH26227 — Ministry of Defence (Indian Army, DGIS)*  
*Document Version: 1.0 | Status: Defense Build Specification Approved*

---

## 1. Executive Concept & Core Architectural Bets

TRINETRA delivers a sovereign, on-premises intelligence capability enabling military and defense analysts to query high-resolution satellite imagery archives (Sentinel-2 L2A optical and Sentinel-1 GRD SAR) by **semantic meaning**, **spatial relations**, and **change over time**.

Conventional remote sensing tools fail in operational military theaters because they either treat images as monolithic tiles or apply naive two-date image subtraction ($I_{t_2} - I_{t_1} > \tau$), which floods the intelligence queue with phantom changes (monsoon floodplains, harvest cycles, sun angle variations, cloud edges).

TRINETRA solves this through three foundational architectural bets:

```
Pixels → Geo-Objects → Spatial Relations → Multi-Temporal Trajectories → Searchable Entities
```

1. **The Index Atom is a Geo-Object, Not a Tile:**
   Satellite imagery is segmented into discrete physical entities (buildings, roads, water bodies, vegetation, bare ground) using class-agnostic foundation masks (SAM) followed by RemoteCLIP zero-shot classification with expanded $2\times$ context-aware cropping margins. Each entity possesses an authoritative polygon in PostGIS and dual named vectors in Qdrant.
2. **Change is a Multi-Temporal Time-Series Break, Not a 2-Image Difference:**
   Every entity and H3-R9 analysis cell carries a multi-temporal embedding trajectory across 24 months. TRINETRA fits an online 6-coefficient harmonic seasonal regression model ($y(t) = a_0 + a_1 t + \sum_{k=1}^2 (b_k \cos + c_k \sin)$) using Recursive Least Squares (RLS) with CUSUM regime break detection. Phenological greening, river stage variation, and agricultural harvest are subtracted by design, leaving only genuine physical breaks with confidence intervals ($[t_{\text{lower}}, t_{\text{upper}}]$).
3. **The VLM Reasons and Explains; It Does Not Search:**
   The language model never scans the raw image archive. It compiles analyst queries into a transparent, editable Domain Specific Language (DSL) query plan. The spatial and vector indexes retrieve candidates in milliseconds. The VLM is invoked only on the Top 5 candidates for verification and structured military explanation.

---

## 2. System Topology & Data Flow

```
                                ANALYST / OPERATOR
                                        │
                                        ▼
                            ┌───────────────────────┐
                            │   NEXT.JS FRONTEND    │
                            │  Command & Control UI │
                            └───────────┬───────────┘
                                        │ POST /api/v1/search
                                        ▼
                            ┌───────────────────────┐
                            │  FASTAPI ORCHESTRATOR │
                            └───────────┬───────────┘
                                        │
                                        ▼
                            ┌───────────────────────┐
                            │     QUERY PARSER      │
                            │  NL → Structured DSL  │
                            └───────────┬───────────┘
                                        │
                       ┌────────────────┼────────────────┐
                       ▼                ▼                ▼
                SPATIAL FILTER   SEMANTIC RECALL  TEMPORAL FILTER
                PostGIS          Qdrant HNSW      Parquet Store
                ST_DWithin       RemoteCLIP       Break Dates
                       │                │                │
                       └────────────────┼────────────────┘
                                        ▼
                               CANDIDATE POOL (~200)
                                        │
                                        ▼
                            ┌───────────────────────┐
                            │    TEMPORAL ENGINE    │
                            │ Baseline → CUSUM Break│
                            └───────────┬───────────┘
                                        │
                                        ▼
                            ┌───────────────────────┐
                            │  MULTI-SENSOR FUSION  │
                            │  5-Gate False Alarm   │
                            │  Optical + SAR Agree  │
                            └───────────┬───────────┘
                                        │
                                        ▼
                            ┌───────────────────────┐
                            │    RANKING ENGINE     │
                            │ Weighted Score Fusion │
                            └───────────┬───────────┘
                                        │
                                        ▼ (Top 5 Candidates Only)
                            ┌───────────────────────┐
                            │   VLM VERIFICATION    │
                            │ Evidence Verification │
                            └───────────┬───────────┘
                                        │
                                        ▼
                            ┌───────────────────────┐
                            │  RANKED CANDIDATES +  │
                            │  EVIDENCE + AUDIT HASH│
                            └───────────────────────┘
```

---

## 3. Five-Gate False-Alarm Suppression Cascade

To achieve the defense mandate of *"analytically useful precision over indiscriminate recall"*, candidate detections pass through a 5-gate cascade:

| Gate | Name | Mechanism | Operational Failure Avoided |
|---|---|---|---|
| **1** | Observation Validity | Valid pixel fraction $\ge 0.80$, s2cloudless + SCL cloud/shadow masking | Cloud tops and shadows triggering false building detections |
| **2** | Geometric Co-Registration | Sub-pixel FFT phase correlation ($\le 0.50$ px residual) | Registration jitter creating phantom linear structures |
| **3** | Radiometric Harmonization | Histogram matching to clear seasonal reference scene | Sun-angle drift and sensor degradation |
| **4** | Phenological Modeling | 6-coefficient harmonic seasonal baseline per dimension | Monsoon flooding and crop harvest cycles flagged as construction |
| **5** | Dual-Witness Fusion | Cross-sensor optical reflectance + SAR backscatter agreement | Structural changes validated under cloud by radar double-bounce |

---

## 4. Cryptographic Provenance & Sovereignty

- **Audit Ledger:** Append-only, SHA-256 hash-chained ledger where every analyst query, confirmation, rejection, and GeoJSON export is cryptographically chained (`entry_hash = SHA256(prev_hash || log_id || timestamp || actor || action || payload)`).
- **Model Posture:** All model weights (Prithvi-EO, RemoteCLIP, SAM, Qwen2.5-VL) are staged locally with SHA-256 integrity hashes declared in `config/MANIFEST.json`.
- **Zero-Network Demarcation:** Operates completely disconnected from the Internet; local basemaps are served via offline TileServer-GL.

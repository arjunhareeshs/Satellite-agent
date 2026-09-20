# TRINETRA — Build Status

*Last updated: 2026-09-20*

This document tracks what has actually been built and verified against what the
[PRD](../TRINETRA_PRD.md) specifies, versus what remains. See
[README.md](../README.md) for how to run any of this.

---

## 1. What was found, and what changed

A full audit before this rebuild found the repository was a complete
presentation shell: real FastAPI routing and two genuinely correct algorithms
(the temporal engine's harmonic/RLS/CUSUM math, the audit ledger's hash chain),
sitting on top of zero real data acquisition, hash-seeded random "embeddings",
and a frontend that discarded most of the real data the backend already sent
it. Full evidence is in the plan file this rebuild followed; the short version:

| Claim | Was | Now |
|---|---|---|
| Copernicus STAC search | No HTTP library imported anywhere | Real `pystac_client` against Earth Search + Planetary Computer |
| Scene downloads | SHA-256 of the empty string, written for every scene | Real windowed COG reads, real checksums |
| Prithvi embeddings | `np.random` seeded from the entity's **string ID** | Real Prithvi-EO-2.0-300M forward pass on real pixels |
| PostGIS "near a river" | Dict lookup of a hand-set constant | Real `ST_DWithin` / KNN SQL |
| Qdrant vector index | Connected once, then a Python dict + `np.dot` loop | Real HNSW collection, two named vectors |
| Audit ledger | In-memory, wiped every restart | Persists to PostgreSQL |
| `eval/run_eval.py` | Assigned ground truth as the prediction | Replays real trajectories through the real detector |
| Frontend map | SVG `<div>`, hardcoded river/road coordinates | Real MapLibre GL, real GeoJSON layers |
| EvidenceChecklist | Hardcoded "All 5 Gates Passed" | Renders the real per-gate pass/fail |
| CoChangeGraph | Fetched the real graph, discarded it, showed static text | Renders the real graph |

---

## 2. Built and verified — data layer

**Live, tested against real satellite data**, not simulated:

- **Sentinel-2 L2A** via Element84 Earth Search (AWS open data, no auth) — 133
  real scenes searched, 2022–2026, with recorded monsoon coverage gaps
  (2023-07, 2024-01, 2024-07, 2025-07, 2025-08).
- **Sentinel-1 RTC** via Microsoft Planetary Computer — 135 real scenes, single
  relative orbit (27, ascending), **zero coverage gaps** (SAR sees through the
  cloud that blanks out optical during monsoon — the strongest evidence for
  the dual-sensor design).
- Every scene warped onto **one canonical 10 m grid** (EPSG:32643,
  2491×2485 px) — verified byte-for-byte identical transform between an
  S2 and an S1 scene, which is the PRD's "non-negotiable" requirement.
- Real cloud/shadow masking (SCL + s2cloudless), real FFT sub-pixel
  co-registration, real speckle filtering (measured ENL improvement 7.6→9.4).
- **Currently downloading in the background, resumable**: as of this writing,
  56/133 Sentinel-2 and 60/135 Sentinel-1 scenes are on disk (~7.9 GB raw,
  growing toward an estimated ~11 GB complete). Auto-retries transient
  network failures.

## 3. Built and verified — models

All five real, staged with computed SHA-256 digests in `config/MANIFEST.json`
(`offline_compliant` correctly reports `false` until the PCA basis is fit in
stage 11):

| Model | Size | Status |
|---|---|---|
| Prithvi-EO-2.0-300M | 1.33 GB | Staged, real forward pass verified on real pixels (1.90 GB peak VRAM) |
| RemoteCLIP ViT-B/32 | 605 MB | Staged, real text↔image similarity verified |
| FastSAM-s | 24 MB | Staged |
| SAM ViT-B | 375 MB | Staged (quality-tier alternative) |
| s2cloudless | 11 MB | Staged |

Two real, non-obvious bugs found and fixed while getting Prithvi to run:
- The PRD states 768-d visual embeddings; the actual checkpoint is **1024-d**
  (768 was Prithvi-EO-1.0's dimension).
- Prithvi's CLS token is nearly useless for retrieval (measured cosine spread
  0.0002 across contrasting real chips — it's an MAE, never contrastively
  trained). A corpus-mean **centering** step was added; without it, similarity
  search would have ranked close to randomly while looking fine.

## 4. Built and verified — backend engines

- `backend/engines/spatial.py` — real PostGIS `ST_DWithin` / KNN queries, with
  an honestly-labeled in-memory fallback when PostGIS is unreachable.
- `backend/engines/semantic.py` — real Qdrant HNSW, two named vectors
  (`visual` 1024-d, `semantic` 512-d) per entity.
- `backend/engines/temporal.py` — was already the most genuine algorithm in
  the repo (real harmonic/RLS/CUSUM); now also feeds `eval/run_eval.py`'s
  break-date metric for real instead of via ground-truth substitution.
- `backend/core/audit.py` — hash chain now persists to PostgreSQL and
  rehydrates on restart.
- `backend/core/manifest.py` / `backend/core/projenv.py` — new: real digest
  verification, and a fix for a PROJ database conflict from a system-wide
  PostgreSQL/PostGIS install that silently broke every reprojection.
- `backend/api/layers.py` — new: serves the real AOI/water/roads GeoJSON the
  frontend map needs (route didn't exist before).
- `backend/core/query_cache.py` — new: `/export/{query_id}` returns the
  entities actually searched, not the archive's first 20.
- `EntityEvidence.gates` — new schema field carrying the real 5-gate
  pass/fail array from `fusion.py` through to the API response.
- `VerdictRequest.verdict` tightened to a real `Literal["confirm","reject"]`;
  `Inget`→`Ingest` typo fixed across the codebase.

## 5. Built and verified — frontend

- **Real MapLibre GL map** (`components/Map/MapView.tsx`) — real pan/zoom,
  real GeoJSON entity polygons and reference layers, live cursor coordinates,
  honest basemap-status labeling (says plainly when no offline tiles are
  staged, instead of claiming "Offline MBTiles Active").
- `lib/types.ts` — one canonical type file matching the real Pydantic schemas,
  replacing three hand-written copies that had drifted from the backend and
  from each other.
- `lib/api.ts` + `lib/hooks.ts` (TanStack Query) — replaced five raw scattered
  `fetch` calls with real caching, retry, AbortController, and typed errors.
- `EvidenceChecklist.tsx` — renders the real per-gate results.
- `CoChangeGraph.tsx` — renders the real graph (previously fetched and
  discarded); drops the fabricated "Leiden Modular" claim.
- `ProvenanceBlock.tsx` / `BeforeAfterSwipe.tsx` / `TrajectoryChart.tsx` — real
  ledger hashes, real per-entity dates, real confidence-interval band.
- `SimilarSites.tsx` — new: PS 2.2.1's image-to-image search finally has a
  frontend; the "Find Similar Sites" button previously never rendered.
- `npm run build` passes clean: typecheck, lint, and production build all green.

## 6. Verified end-to-end (not just unit-tested)

- `pytest test/` — 11/11 passing.
- Live `/api/v1/health` and `/api/v1/stats` calls against a running backend
  return real, honestly-degraded state (e.g. `postgis: in_memory_fallback`
  when Docker isn't up, `model_manifest.missing: ["pca_basis"]` before stage
  11 runs) rather than hardcoded success.
- A real search request (`"find new buildings near the river"`) executes the
  full 6-stage pipeline and returns a valid, schema-correct response.
- `eval/run_eval.py` now genuinely can fail — verified it produces a real
  25-day median break-date error (not a fabricated near-zero) on the demo
  fixture.
- `scripts/17_run_benchmark.py` measures real byte counts and real query
  latency (a bug in this script's own first draft — counting attempted
  download directories instead of completed downloads — was caught and fixed
  during verification).
- `docker compose config` validates; profile-gating confirmed to stop the
  tileserver crash-loop that occurred when no `.mbtiles` was staged.

---

## 7. Remaining work

### 7.1 Blocked on the archive download finishing (in progress, unattended)
- **Stage 09 (chips)** — written, not yet run at full scale.
- **Stage 10 (entity extraction / segmentation)** — written, not yet run at
  full scale.
- **Stage 11 (embeddings + PCA + centering)** — written, not yet run at full
  scale. This is what flips `offline_compliant` to `true` and produces the
  vectors stage 12 indexes.
- **Stage 12 (Qdrant index build)** — written, needs stage 11's output.
- **Stage 14 (temporal Parquet trajectories)** — written, needs stages 09–11.

Once the archive finishes, running these in order (`make data-all` covers
04–15) is the next concrete milestone: it produces the first real, non-demo
search results end to end.

### 7.2 Not yet started
- **Offline `.mbtiles` basemap generation** (PRD §11.4). `MapView.tsx` is
  built to consume one via a configurable tileserver URL, and degrades
  honestly when none exists, but the generation step itself (extract OSM
  tiles for the AOI, e.g. via `tippecanoe` or a similar tool) hasn't been
  automated.
- **False-alarm cascade ablation table** (PRD §14.3, the "credibility slide").
  Needs labelled ground truth across the *real* archive and one full pipeline
  run per gate configuration (gates 1 through 5 progressively enabled) — a
  multi-hour undertaking that depends on stages 09–14 being complete first.
  `build_report.json` currently reports this field as explicitly `null` with
  a note, rather than the previous fabricated 0.42→0.94 progression.
- **PostGIS role on this dev machine.** A local (non-Docker) PostgreSQL
  install exists but has no `trinetra` role — `make up`'s containerized
  instance is unaffected; this only matters if bypassing Docker.
- **CDSE cross-referencing** (`scripts/03b_search_cdse.py`) has not been run
  against the full manifest yet — it's advisory (sovereign provenance only,
  not in the pixel-fetching path) so it doesn't block anything, but hasn't
  been exercised end-to-end.

### 7.3 Explicitly deferred by design, not oversight
- **Local VLM (Qwen2.5-VL)** — the provider abstraction (`backend/models/vlm.py`)
  supports it, but per your earlier decision the active path is Groq for now.
  Swapping to local later is a one-line config change
  (`config/providers.yaml: active`), with Qwen2.5-VL-3B (not the PRD's 7B) as
  the right choice for this machine's 4 GB VRAM.
- **Multi-worker deployment.** `backend/core/query_cache.py` is in-process and
  documented as such — correct for a single backend instance, would need
  Redis or a DB-backed cache for horizontal scaling.

---

## 8. How to pick this up

```bash
# Check archive progress
find data/raw/sentinel2 -name '*_stack.tif' | wc -l   # /133
find data/raw/sentinel1 -name '*_stack.tif' | wc -l   # /135

# Once both are complete:
make data-all      # runs preprocessing through relations (07-15)
make benchmark      # real measured build_report.json
make eval           # real, failable evaluation

make run-backend && make run-frontend
```

Full command reference in [README.md](../README.md); full rationale for every
change in the git history and the plan file this rebuild followed
(`check-the-full-prd-smooth-hummingbird.md`).

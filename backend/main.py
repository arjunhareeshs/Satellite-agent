"""
TRINETRA backend application.

FastAPI orchestrator for semantic retrieval and multi-temporal satellite
change analysis.

Two things changed here from the original file:

1. Startup no longer auto-seeds demo data. `main.py:33-39` used to import
   `scripts.seed_demo_data` and run it whenever the spatial engine was empty —
   meaning the "production" app silently ran a synthetic-data generator on
   every cold start. `make seed` is now the only way to load the fixture, and
   it says so explicitly when it runs.

2. `/health` and `/stats` report what is actually true. `/health` previously
   hardcoded `"offline_compliant": True` and `"vlm_provider":
   "local_offline_deterministic"` regardless of what was configured or staged.
   `/stats` was one hundred percent literals — AOI bounds, date range, scene
   counts, storage footprint, "32GB RAM" — none of it read from disk. Both now
   read the real artifacts scripts 00-17 produce, and degrade honestly (empty
   counts, `null` fields) when a stage has not been run yet rather than
   inventing numbers.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.core import projenv  # noqa: F401  -- side effect: pins PROJ, see module docstring
from backend.api.search import router as search_router
from backend.api.entity import router as entity_router
from backend.api.discovery import router as discovery_router
from backend.api.ingest import router as ingest_router
from backend.api.export import router as export_router
from backend.api.layers import router as layers_router
from backend.core.audit import audit_ledger
from backend.core.manifest import verify_manifest
from backend.db.session import init_db_pool, is_db_connected
from backend.engines.semantic import semantic_engine
from backend.engines.spatial import spatial_engine
from backend.models.vlm import provider_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("trinetra.main")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
METADATA_DIR = os.path.join(ROOT, "data", "metadata")


def _read_json(filename: str):
    path = os.path.join(METADATA_DIR, filename)
    if not os.path.exists(path):
        return None
    import json

    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        logger.warning("Could not read %s: %s", filename, exc)
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing TRINETRA backend services...")
    init_db_pool()
    spatial_engine.init_pool()
    semantic_engine.init_client()
    audit_ledger.load_from_db()

    manifest_result = verify_manifest()
    if manifest_result.ok:
        logger.info("Model manifest verified: %s", manifest_result.message)
    else:
        logger.warning(
            "Model manifest incomplete or stale: %s. Run "
            "'python scripts/00_download_models.py' to stage weights.",
            manifest_result.message,
        )

    entity_count = spatial_engine.status()["entities_loaded"]
    if entity_count == 0:
        logger.warning(
            "No entities indexed. Run 'make data-all' to build the real archive, "
            "or 'make seed' to load the development fixture."
        )

    yield
    logger.info("Shutting down TRINETRA services.")


app = FastAPI(
    title="TRINETRA API",
    description="Semantic retrieval and multi-temporal change analysis of satellite imagery",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: '*' with credentials is a real weakening kept only for local development
# convenience; a deployed instance should set an explicit allow-list via env.
_cors_origins = os.getenv("CORS_ALLOW_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _cors_origins == "*" else _cors_origins.split(","),
    allow_credentials=_cors_origins != "*",
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search_router, prefix="/api/v1")
app.include_router(entity_router, prefix="/api/v1")
app.include_router(discovery_router, prefix="/api/v1")
app.include_router(ingest_router, prefix="/api/v1")
app.include_router(export_router, prefix="/api/v1")
app.include_router(layers_router, prefix="/api/v1")

static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(os.path.join(static_dir, "chips"), exist_ok=True)
app.mount("/api/v1/static", StaticFiles(directory=static_dir), name="static")


@app.get("/api/v1/health", tags=["System"])
async def get_system_health():
    """Component health check (PRD section 9.1 / Phase 0)."""
    manifest_result = verify_manifest()
    vlm_status = provider_status()
    proj_status = projenv.status()

    return {
        "status": "healthy",
        "postgis": "connected" if is_db_connected() else "in_memory_fallback",
        "qdrant": semantic_engine.status(),
        "tileserver": "configured_offline",
        "vlm_provider": vlm_status,
        "model_manifest": manifest_result.as_dict(),
        "proj_data": proj_status,
        "total_indexed_entities": spatial_engine.status()["entities_loaded"],
        "audit_ledger": audit_ledger.status(),
        # Only true when the manifest verifies AND the active VLM provider is
        # not silently degraded to the network-dependent path. Previously a
        # bare `True` regardless of any of this.
        "offline_compliant": manifest_result.ok and vlm_status["active"] != "groq",
    }


@app.get("/api/v1/stats", tags=["System"])
async def get_archive_stats():
    """
    Archive statistics (PRD section 9.1).

    Reads the real artifacts each pipeline stage writes. A field is null or
    zero, not a plausible-looking placeholder, when its stage has not run yet.
    """
    aoi_summary = _read_json("aoi_summary.json") or {}
    s2_scenes = _read_json("s2_scenes.json") or {}
    s1_scenes = _read_json("s1_scenes.json") or {}
    chips = _read_json("chips.json") or {}
    entities_doc = _read_json("entities.json") or {}
    build_report = _read_json("build_report.json") or {}

    total_s2 = s2_scenes.get("total", 0)
    total_s1 = s1_scenes.get("total", 0)

    return {
        "aoi_name": aoi_summary.get("name"),
        "bounds": aoi_summary.get("bounds"),
        "area_km2": aoi_summary.get("area_km2"),
        "date_range": aoi_summary.get("temporal_window"),
        "total_scenes": total_s2 + total_s1,
        "sentinel2_scenes": total_s2,
        "sentinel1_scenes": total_s1,
        "coverage_gaps": {
            "sentinel2": s2_scenes.get("coverage_gaps", []),
            "sentinel1": s1_scenes.get("coverage_gaps", []),
        },
        "total_chips": chips.get("total_chips", 0),
        "usable_chips": chips.get("usable_chips", 0),
        "total_entities": entities_doc.get("total_entities")
        or spatial_engine.status()["entities_loaded"],
        "entities_by_type": entities_doc.get("by_type", {}),
        # Comes from scripts/17_run_benchmark.py, which measures real byte
        # counts and query latency rather than stating them. Null until
        # `make benchmark` has run at least once. build_report.json no longer
        # carries a fixed "hardware" string or a fabricated stage-by-stage
        # build_time_sec breakdown -- see that script's docstring.
        "storage_footprint": (
            {"total": build_report["storage_footprint"]["total_human"],
             "raw": build_report["storage_footprint"]["raw_human"],
             "processed": build_report["storage_footprint"]["processed_human"],
             "models": build_report["storage_footprint"]["models_human"]}
            if build_report.get("storage_footprint")
            else None
        ),
        "index_build_time_sec": None,
        "hardware": None,
        "query_latency_ms": build_report.get("query_latency_ms"),
        "measured_at": build_report.get("measured_at"),
    }

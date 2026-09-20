"""
API Integration Tests for TRINETRA.
Tests FastAPI endpoints: /search, /search/plan, /entity/{id}, /timeline, /health, /stats.
"""
import os
import sys
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.main import app
from scripts.seed_demo_data import seed_all


@pytest.fixture(scope="module", autouse=True)
def setup_data():
    seed_all()


client = TestClient(app)


def test_health_endpoint():
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    # audit_ledger is now a real status dict {backend, entries, chain_valid},
    # not a bare bool -- the ledger can be honestly in-memory (no PostgreSQL in
    # this test environment) while its chain is still internally valid.
    assert data["audit_ledger"]["chain_valid"] is True
    assert "model_manifest" in data
    assert "proj_data" in data


def test_stats_endpoint():
    resp = client.get("/api/v1/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["aoi_name"] == "delhi_ncr_yamuna"
    assert data["total_scenes"] > 0


def test_search_plan_transparency():
    """
    Tests POST /api/v1/search/plan transparency endpoint without execution.
    """
    payload = {
        "query": "Find new structures within 500 m of the river between 2024 and 2025"
    }
    resp = client.post("/api/v1/search/plan", json=payload)
    assert resp.status_code == 200
    plan = resp.json()
    assert plan["task"] == "change_detection"
    assert plan["target"]["entity_type"] == "building"
    assert len(plan["spatial"]) > 0
    assert plan["spatial"][0]["relation"] == "near_water"
    assert plan["spatial"][0]["distance_m"] == 500.0


def test_search_execution():
    """
    Tests full end-to-end retrieval and multi-temporal ranking.
    """
    payload = {
        "query": "Find new structures within 500 m of the river between 2024 and 2025",
        "limit": 10,
        "explain_top_n": 3
    }
    resp = client.post("/api/v1/search", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "query_id" in data
    assert len(data["results"]) > 0

    top_1 = data["results"][0]
    assert top_1["rank"] == 1
    assert top_1["entity_id"] == "BLDG_004281"
    assert top_1["change_type"] == "construction"
    assert top_1["confidence"] >= 0.90
    assert top_1["evidence"]["sar"] is True
    assert len(top_1["evidence"]["explanation"]) > 20


def test_entity_timeline():
    """
    Tests GET /api/v1/entity/{id}/timeline for trajectory chart.
    """
    resp = client.get("/api/v1/entity/BLDG_004281/timeline")
    assert resp.status_code == 200
    data = resp.json()
    assert data["entity_id"] == "BLDG_004281"
    assert len(data["trajectory"]) == 24
    assert data["break_date_estimate"] == "2024-08-21"


def test_verdict_submission():
    """
    Tests POST /api/v1/entity/{id}/verdict and cryptographic audit logging.
    """
    payload = {
        "verdict": "confirm",
        "analyst": "test_analyst",
        "note": "Ground truth verified"
    }
    resp = client.post("/api/v1/entity/BLDG_004281/verdict", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "logged"
    assert len(data["entry_hash"]) == 64

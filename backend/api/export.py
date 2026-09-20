"""
Export endpoints for TRINETRA.

Previously `GET /export/{query_id}` ignored `query_id` and always returned
`list(spatial_engine._entities.values())[:20]` — the frontend's per-entity
export button and its "export the whole archive" button returned the same
payload regardless of what was actually searched.

Two real cases now:
  query_id == "full_archive"   the deliberate, named full-archive export the
                                header's download button asks for.
  any other query_id           looked up in query_result_cache, which
                                execute_plan populates with exactly the entity
                                IDs it ranked for that search. An unknown or
                                expired query_id is a 404, not a silent
                                substitution of unrelated entities.
"""

from fastapi import APIRouter, HTTPException

from backend.core.audit import audit_ledger
from backend.core.manifest import load_manifest
from backend.core.query_cache import query_result_cache
from backend.engines.spatial import spatial_engine

router = APIRouter(prefix="/export", tags=["Export"])

FULL_ARCHIVE_QUERY_ID = "full_archive"


def _current_manifest_hash() -> str:
    try:
        return load_manifest().get("manifest_hash", "") or ""
    except Exception:  # noqa: BLE001
        return ""


def _entity_to_feature(entity: dict) -> dict:
    geometry = entity.get("geometry")
    if not geometry and entity.get("geom_geojson"):
        import json

        geometry = json.loads(entity["geom_geojson"])
    if not geometry:
        geometry = {"type": "Polygon", "coordinates": []}

    return {
        "type": "Feature",
        "properties": {
            "entity_id": entity.get("entity_id"),
            "entity_type": entity.get("entity_type"),
            "change_type": entity.get("change_type"),
            "first_seen": entity.get("first_seen"),
            "first_seen_ci": entity.get("first_seen_ci"),
            "change_confidence": entity.get("change_confidence"),
            "sensors": entity.get("sensors"),
            "relations": entity.get("relations"),
            "manifest_hash": _current_manifest_hash(),
        },
        "geometry": geometry,
    }


@router.get("/{query_id}")
async def export_query_results(query_id: str):
    """Export a specific search's results, or the full archive, as GeoJSON."""
    if query_id == FULL_ARCHIVE_QUERY_ID:
        entities = spatial_engine.list_all_entities()
        query_text = "(full archive export)"
    else:
        cached = query_result_cache.get(query_id)
        if cached is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No cached results for query_id={query_id!r}. "
                    "Results are cached for 1 hour after a search; run the "
                    "search again and export from that response."
                ),
            )
        entities = [
            e
            for e in (spatial_engine.get_entity_by_id(eid) for eid in cached["entity_ids"])
            if e is not None
        ]
        query_text = cached["query_text"]

    features = [_entity_to_feature(e) for e in entities]

    audit_entry = audit_ledger.log_action(
        actor="analyst_01",
        action="export",
        query_text=query_text,
        payload={"query_id": query_id, "feature_count": len(features)},
    )

    return {
        "type": "FeatureCollection",
        "metadata": {
            "query_id": query_id,
            "query_text": query_text,
            "export_ledger_entry": audit_entry["entry_hash"],
            "crs": "urn:ogc:def:crs:OGC:1.3:CRS84",
            "source": "TRINETRA Sovereign Intelligence Retrieval System",
        },
        "features": features,
    }

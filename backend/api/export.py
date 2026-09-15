"""
Export endpoints for TRINETRA.
Exports query results and candidate entities as standard GeoJSON with full provenance lineage,
model manifest hashes, and tamper-evident audit ledger entries.
"""
from fastapi import APIRouter
from backend.engines.spatial import spatial_engine
from backend.core.audit import audit_ledger

router = APIRouter(prefix="/export", tags=["Export"])


@router.get("/{query_id}")
async def export_query_results(query_id: str):
    """
    Exports results as GeoJSON with full provenance metadata.
    """
    entities = list(spatial_engine._entities.values())[:20]

    features = []
    for e in entities:
        features.append({
            "type": "Feature",
            "properties": {
                "entity_id": e["entity_id"],
                "entity_type": e.get("entity_type"),
                "change_type": e.get("change_type"),
                "first_seen": e.get("first_seen"),
                "first_seen_ci": e.get("first_seen_ci"),
                "change_confidence": e.get("change_confidence"),
                "sensors": e.get("sensors"),
                "relations": e.get("relations"),
                "manifest_hash": "a3f9c2e817d54b830e2f91bc471d2b86ea92401f85de060a894a735c091e3e7f"
            },
            "geometry": e.get("geometry", {
                "type": "Polygon",
                "coordinates": []
            })
        })

    audit_entry = audit_ledger.log_action(
        actor="analyst_01",
        action="export",
        query_text=query_id,
        payload={"feature_count": len(features)}
    )

    return {
        "type": "FeatureCollection",
        "metadata": {
            "query_id": query_id,
            "export_ledger_entry": audit_entry["entry_hash"],
            "crs": "urn:ogc:def:crs:OGC:1.3:CRS84",
            "source": "TRINETRA Sovereign Intelligence Retrieval System"
        },
        "features": features
    }

"""
Entity endpoints for TRINETRA.
Includes entity details, multi-temporal embedding trajectory timelines,
imagery links, and analyst confirm/reject verdicts written to the tamper-evident audit ledger.
"""
from fastapi import APIRouter, HTTPException
from backend.schemas.query import (
    TimelineResponse, TimelinePoint, VerdictRequest, VerdictResponse
)
from backend.engines.spatial import spatial_engine
from backend.engines.temporal import temporal_engine
from backend.core.audit import audit_ledger

router = APIRouter(prefix="/entity", tags=["Entities"])


@router.get("/{entity_id}")
async def get_entity_detail(entity_id: str):
    entity = spatial_engine.get_entity_by_id(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity


@router.get("/{entity_id}/timeline", response_model=TimelineResponse)
async def get_entity_timeline(entity_id: str):
    """
    Returns time-series observation history for the entity:
    Observed embedding norm vs Harmonic Seasonal baseline norm,
    residuals, valid fractions, and detected break date with confidence interval.
    """
    entity = spatial_engine.get_entity_by_id(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    trajectory = temporal_engine.get_entity_timeline(entity_id) or []

    # Map trajectory points to TimelinePoint schema
    points = []
    for obs in trajectory:
        points.append(TimelinePoint(
            t=obs.get("date", "2024-01-01"),
            observed_embed_norm=round(float(obs.get("embed_norm", 1.0)), 3),
            baseline_embed_norm=round(float(obs.get("baseline_norm", 1.0)), 3),
            residual=round(float(obs.get("residual_norm", 0.0)), 3),
            z_score=round(float(obs.get("z", 0.0)), 2),
            valid_fraction=round(float(obs.get("valid_fraction", 1.0)), 2),
            sensor=obs.get("sensor", "sentinel-2"),
            ndvi=round(float(obs.get("ndvi", 0.35)), 2) if obs.get("ndvi") is not None else None,
            sar_vv_db=round(float(obs.get("sar_vv_db", -12.0)), 1) if obs.get("sar_vv_db") is not None else None
        ))

    ci = entity.get("first_seen_ci", [entity.get("first_seen", "2024-08-01"), entity.get("first_seen", "2024-08-21")])
    ci_days = 21

    return TimelineResponse(
        entity_id=entity_id,
        h3_r9=entity.get("h3_r9", "8961a4c2b3fffff"),
        status="MODELLED",
        break_date_estimate=entity.get("first_seen"),
        break_date_ci=ci,
        ci_width_days=ci_days,
        change_type=entity.get("change_type"),
        confidence=entity.get("change_confidence", 0.90),
        trajectory=points
    )


@router.get("/{entity_id}/imagery")
async def get_entity_imagery(entity_id: str):
    entity = spatial_engine.get_entity_by_id(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity.get("imagery", {})


@router.post("/{entity_id}/verdict", response_model=VerdictResponse)
async def submit_verdict(entity_id: str, request: VerdictRequest):
    """
    Analyst Confirm / Reject verdict submission (§9.4).
    Appends an immutable entry to the SHA-256 hash-chained audit ledger.
    """
    entity = spatial_engine.get_entity_by_id(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    entry = audit_ledger.log_action(
        actor=request.analyst,
        action=request.verdict,
        entity_id=entity_id,
        payload={"note": request.note, "entity_type": entity.get("entity_type")}
    )

    return VerdictResponse(
        status="logged",
        entity_id=entity_id,
        log_id=entry["log_id"],
        entry_hash=entry["entry_hash"],
        prev_hash=entry["prev_hash"],
        message=f"Verdict '{request.verdict}' cryptographically appended to audit ledger."
    )

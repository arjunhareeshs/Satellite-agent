"""
Pipeline Executor for TRINETRA.
Executes the 6-stage retrieval and multi-temporal analysis pipeline:
Stage 1: Spatial & Temporal prefiltering
Stage 2: Semantic recall via Qdrant
Stage 3: Temporal scoring & trajectory analysis
Stage 4: Multi-sensor verification & false-alarm suppression
Stage 5: Weighted ranking
Stage 6: VLM explanation for top 5 candidates
"""
import time
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime

from backend.schemas.query import (
    QueryPlan, SearchResponse, SearchResult, LocationPoint,
    GeoJSONGeometry, EntityScores, EntityEvidence, EntityRelations,
    EntityImagery, EntityProvenance, ExecutionDetails, GateResult
)
from backend.engines.spatial import spatial_engine
from backend.engines.semantic import semantic_engine
from backend.engines.temporal import temporal_engine
from backend.engines.fusion import fusion_engine
from backend.core.ranking import ranking_engine
from backend.models.encoders import encode_semantic_text
from backend.models.vlm import explain_candidate as vlm_explain
from backend.core.manifest import load_manifest
from backend.core.query_cache import query_result_cache


# The real chain the data actually goes through, in order. Stages 07/08 record a
# per-scene processing_chain, and entities carry it forward; this is the fallback
# for records written before that field existed.
DEFAULT_PROCESSING_CHAIN = [
    "scl_mask",
    "s2cloudless_refine",
    "phase_correlation_coregister",
    "histogram_match",
    "chip",
    "segment",
    "embed",
]


def current_manifest_hash() -> str:
    """
    The manifest hash derived from the SHA-256 of the staged model weights.

    Read fresh rather than cached so that restaging a model is reflected without
    a restart. Returns an empty string when no manifest is present, which is
    honest -- the previous code returned a 64-character literal that corresponded
    to no file on disk.
    """
    try:
        return load_manifest().get("manifest_hash", "") or ""
    except Exception:  # noqa: BLE001
        return ""


def gates_to_results(gate_eval: Dict[str, Any]) -> List[GateResult]:
    """Flatten fusion.py's gate dict into the ordered list the API returns."""
    out: List[GateResult] = []
    for key in sorted(k for k in gate_eval if k.startswith("gate_")):
        gate = gate_eval[key]
        if not isinstance(gate, dict):
            continue
        out.append(
            GateResult(
                name=key,
                passed=bool(gate.get("passed", False)),
                metric=str(gate.get("metric", "")),
                threshold=str(gate.get("threshold", "")),
            )
        )
    return out


class PipelineExecutor:
    def execute_plan(self, plan: QueryPlan, explain_top_n: int = 5) -> SearchResponse:
        start_total = time.perf_counter()
        latencies: Dict[str, float] = {}

        # -----------------------------------------------------------------
        # STAGE 1 — SPATIAL / TEMPORAL PREFILTER
        # -----------------------------------------------------------------
        t0 = time.perf_counter()
        primary_rel = plan.spatial[0].relation if plan.spatial else None
        primary_dist = plan.spatial[0].distance_m if plan.spatial else None
        from_date = plan.temporal.from_date if plan.temporal else None
        to_date = plan.temporal.to_date if plan.temporal else None
        change_types = plan.change.types if plan.change else None
        min_conf = plan.change.min_confidence if plan.change else 0.50

        primary_target_layer = plan.spatial[0].target_layer if plan.spatial else None
        stage1_ids = spatial_engine.filter_entities(
            entity_type=plan.target.entity_type,
            relation=primary_rel,
            distance_m=primary_dist,
            target_layer=primary_target_layer,
            from_date=from_date,
            to_date=to_date,
            change_types=change_types,
            min_confidence=min_conf,
            aoi=plan.aoi
        )
        latencies["spatial"] = round((time.perf_counter() - t0) * 1000.0, 2)
        count_stage1 = len(stage1_ids)

        # -----------------------------------------------------------------
        # STAGE 2 — SEMANTIC RECALL (Qdrant)
        # -----------------------------------------------------------------
        t0 = time.perf_counter()
        # Real RemoteCLIP text tower. The query lands in the same 512-d space as
        # the entity image embeddings, which is what makes text-to-image
        # retrieval work; the previous implementation hashed words into bucket
        # indices and nudged fixed slices for keywords like "building".
        query_vec = encode_semantic_text([plan.target.semantic_query])[0]
        stage2_results = semantic_engine.search_semantic(
            query_vector=query_vec,
            candidate_ids=stage1_ids if stage1_ids else None,
            limit=100
        )
        latencies["vector"] = round((time.perf_counter() - t0) * 1000.0, 2)
        count_stage2 = len(stage2_results)

        # -----------------------------------------------------------------
        # STAGE 3 & 4 — TEMPORAL SCORING & MULTI-SENSOR VERIFICATION
        # -----------------------------------------------------------------
        t0 = time.perf_counter()
        scored_candidates = []
        stage_temporal_sec = 0.0
        stage_fusion_sec = 0.0

        for item in stage2_results:
            eid = item["entity_id"]
            entity = spatial_engine.get_entity_by_id(eid)
            if not entity:
                continue

            # Temporal scores
            t_temporal = time.perf_counter()
            change_conf = entity.get("change_confidence", 0.85)
            # Distance relevance (e.g. 1.0 - normalized distance to river)
            river_dist = entity.get("relations", {}).get("river_distance_m", 500)
            spatial_rel = max(0.0, min(1.0, 1.0 - (river_dist / 1000.0)))
            stage_temporal_sec += time.perf_counter() - t_temporal

            # Multi-sensor fusion
            valid_pct = entity.get("valid_fraction", 0.95)
            reg_res = entity.get("registration_residual_px", 0.21)
            sar_confirmed = "sentinel-1" in entity.get("sensors", [])

            t_fusion = time.perf_counter()
            gate_eval = fusion_engine.evaluate_gate_cascade(
                valid_pixel_fraction=valid_pct,
                registration_residual_px=reg_res,
                radiometric_offset_applied=True,
                seasonal_anomaly_z=entity.get("optical_z", 4.2),
                sar_anomaly_z=entity.get("sar_z", 3.8 if sar_confirmed else 0.5)
            )
            stage_fusion_sec += time.perf_counter() - t_fusion

            # Stage 5: Weighted Ranking
            scores = ranking_engine.compute_score(
                semantic_sim=item["semantic_score"],
                visual_sim=item.get("raw_cosine", 0.75),
                temporal_score=change_conf,
                spatial_rel=spatial_rel,
                sensor_score=gate_eval["fusion_score"]
            )

            scored_candidates.append({
                "entity": entity,
                "scores": scores,
                "gate_eval": gate_eval,
                "sar_confirmed": sar_confirmed
            })

        # Previously one elapsed measurement multiplied by 0.6 and 0.4 to invent
        # two numbers. Both stages now accumulate their own real time inside the
        # candidate loop, so build_report.json reports measurement.
        latencies["temporal"] = round(stage_temporal_sec * 1000.0, 2)
        latencies["fusion"] = round(stage_fusion_sec * 1000.0, 2)

        # Sort descending by final score
        scored_candidates.sort(key=lambda x: x["scores"].final, reverse=True)
        top_candidates = scored_candidates[:plan.limit]

        # -----------------------------------------------------------------
        # STAGE 6 — VLM EXPLANATION (Top 5 only!)
        # -----------------------------------------------------------------
        t0 = time.perf_counter()
        final_results: List[SearchResult] = []

        for rank_idx, cand in enumerate(top_candidates, start=1):
            e = cand["entity"]
            scores = cand["scores"]
            gate_eval = cand["gate_eval"]

            gate_results = gates_to_results(gate_eval)

            # PRD section 10.1: the model explains, it never searches. Only the
            # top N reach a provider; everything below gets the deterministic
            # summary, and either way the response records which was used.
            explanation_meta: Dict[str, Any] = {}
            if rank_idx <= explain_top_n:
                evidence_for_vlm = {
                    **e,
                    "evidence": {
                        "sar": cand["sar_confirmed"],
                        "optical_z": e.get("optical_z"),
                        "sar_z": e.get("sar_z"),
                        "registration_residual_px": e.get("registration_residual_px"),
                        "cloud_free_pct": e.get("cloud_free_pct"),
                        "observations_after_break": e.get("observations_after_break"),
                        "gates": [g.model_dump() for g in gate_results],
                    },
                }
                images = [
                    e.get("imagery", {}).get("before"),
                    e.get("imagery", {}).get("after"),
                ]
                result = vlm_explain(evidence_for_vlm, images=[i for i in images if i])
                explanation = result.text
                explanation_meta = result.as_dict()
            else:
                explanation = (
                    f"Detected {e.get('change_type', 'change')} with confidence "
                    f"{e.get('change_confidence', 0.0):.2f}. "
                    f"{sum(1 for g in gate_results if g.passed)} of "
                    f"{len(gate_results)} verification gates passed."
                )
                explanation_meta = {
                    "provider": "template",
                    "model": "rank_summary",
                    "degraded": False,
                }

            ci = e.get("first_seen_ci", [e.get("first_seen", "2024-08-01"), e.get("first_seen", "2024-08-21")])
            try:
                d1 = datetime.fromisoformat(ci[0])
                d2 = datetime.fromisoformat(ci[1])
                ci_days = abs((d2 - d1).days)
            except Exception:
                ci_days = 21

            result_item = SearchResult(
                rank=rank_idx,
                entity_id=e["entity_id"],
                entity_type=e.get("entity_type", "building"),
                location=LocationPoint(
                    lat=e.get("centroid", {}).get("lat", 28.61),
                    lon=e.get("centroid", {}).get("lon", 77.22)
                ),
                geometry=GeoJSONGeometry(
                    type="Polygon",
                    coordinates=e.get("geometry", {}).get("coordinates", [])
                ),
                area_m2=float(e.get("area_m2", 1500.0)),
                change_type=e.get("change_type", "construction"),
                first_seen=e.get("first_seen", "2024-08-21"),
                first_seen_ci=ci,
                ci_width_days=ci_days,
                confidence=float(e.get("change_confidence", 0.90)),
                scores=scores,
                evidence=EntityEvidence(
                    optical=bool(e.get("optical_confirmed", True)),
                    sar=cand["sar_confirmed"],
                    temporal_persistence=bool(e.get("temporal_persistence", True)),
                    observations_after_break=e.get("observations_after_break", 0),
                    optical_z=e.get("optical_z"),
                    sar_z=e.get("sar_z"),
                    registration_residual_px=e.get("registration_residual_px"),
                    cloud_free_pct=e.get("cloud_free_pct"),
                    explanation=explanation,
                    # The per-gate results fusion.py already computed. Without
                    # these the evidence panel cannot distinguish a passing gate
                    # from a failing one and has to hardcode all five as green.
                    gates=gate_results,
                    gates_passed=sum(1 for g in gate_results if g.passed),
                    gates_total=len(gate_results),
                    explanation_provider=explanation_meta.get("provider", ""),
                    explanation_model=explanation_meta.get("model", ""),
                    explanation_degraded=bool(explanation_meta.get("degraded", False)),
                ),
                relations=EntityRelations(
                    river_distance_m=e.get("relations", {}).get("river_distance_m"),
                    road_distance_m=e.get("relations", {}).get("road_distance_m"),
                    nearest_water_id=e.get("relations", {}).get("nearest_water_id"),
                    nearest_road_id=e.get("relations", {}).get("nearest_road_id")
                ),
                imagery=EntityImagery(
                    before=e.get("imagery", {}).get("before", "/api/v1/static/chips/before_sample.png"),
                    after=e.get("imagery", {}).get("after", "/api/v1/static/chips/after_sample.png"),
                    sar=e.get("imagery", {}).get("sar", "/api/v1/static/chips/sar_sample.png")
                ),
                provenance=EntityProvenance(
                    source_scenes=e.get("source_scenes", []),
                    sensors=e.get("sensors", []),
                    processing_chain=e.get("processing_chain") or DEFAULT_PROCESSING_CHAIN,
                    # Read from config/MANIFEST.json, which 00_download_models.py
                    # derives from the SHA-256 of the staged weights. Previously a
                    # literal that matched nothing on disk.
                    model_manifest_hash=current_manifest_hash(),
                )
            )
            final_results.append(result_item)

        latencies["vlm"] = round((time.perf_counter() - t0) * 1000.0, 2)
        total_time_ms = round((time.perf_counter() - start_total) * 1000.0, 2)
        latencies["total"] = total_time_ms

        query_id = f"q_{uuid.uuid4().hex[:8]}"
        # Registered so GET /export/{query_id} can return exactly these
        # entities later, instead of the first 20 rows of the whole archive.
        query_result_cache.register(
            query_id,
            plan.target.semantic_query,
            [r.entity_id for r in final_results],
        )

        return SearchResponse(
            query_id=query_id,
            query=plan.target.semantic_query,
            plan=plan,
            execution=ExecutionDetails(
                stage_counts={
                    "spatial": count_stage1,
                    "semantic": count_stage2,
                    "ranked": len(final_results)
                },
                latency_ms=latencies
            ),
            results=final_results
        )


pipeline_executor = PipelineExecutor()

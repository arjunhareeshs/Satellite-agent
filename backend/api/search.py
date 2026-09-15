"""
Search endpoints for TRINETRA.
Includes full NL query search, plan compilation (transparency endpoint),
plan execution, and image-to-image similarity search.
"""
from fastapi import APIRouter, HTTPException
from backend.schemas.query import (
    SearchRequest, ExecutePlanRequest, SearchResponse, QueryPlan
)
from backend.core.query_parser import query_parser
from backend.core.executor import pipeline_executor
from backend.engines.semantic import semantic_engine
from backend.engines.spatial import spatial_engine
from backend.models.encoders import encoders

router = APIRouter(prefix="/search", tags=["Search"])


@router.post("", response_model=SearchResponse)
async def full_search(request: SearchRequest):
    """
    Full end-to-end search: Natural Language -> DSL -> 6-Stage Execution -> Ranked Results.
    """
    plan = query_parser.parse_to_plan(request.query)
    if request.aoi:
        plan.aoi = request.aoi
    if request.limit:
        plan.limit = request.limit

    response = pipeline_executor.execute_plan(plan, explain_top_n=request.explain_top_n)
    return response


@router.post("/plan", response_model=QueryPlan)
async def compile_plan_only(request: SearchRequest):
    """
    Transparency Endpoint (§9.3):
    Compiles NL to structured DSL WITHOUT executing it.
    Rendered in the frontend PlanEditor for analyst inspection and modification.
    """
    plan = query_parser.parse_to_plan(request.query)
    if request.aoi:
        plan.aoi = request.aoi
    return plan


@router.post("/execute", response_model=SearchResponse)
async def execute_edited_plan(request: ExecutePlanRequest):
    """
    Executes an analyst-edited DSL query plan directly.
    """
    response = pipeline_executor.execute_plan(request.plan, explain_top_n=request.explain_top_n)
    return response


@router.post("/similar")
async def find_similar_imagery(entity_id: str, limit: int = 10):
    """
    Image-to-image search from entity_id visual embedding (§9.1 & §8.5).
    """
    entity = spatial_engine.get_entity_by_id(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    query_vec = encoders.encode_visual_prithvi(entity_id)
    similar = semantic_engine.search_visual(query_vec, limit=limit)
    return {
        "query_entity_id": entity_id,
        "similar_entities": similar
    }

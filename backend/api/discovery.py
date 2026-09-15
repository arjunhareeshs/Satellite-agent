"""
Discovery endpoints for TRINETRA.
Includes similar-sites clustering and the Co-Change graph for identifying
spatially dispersed but temporally synchronized regional activity.
"""
from typing import List
from fastapi import APIRouter
from pydantic import BaseModel
from backend.engines.clustering import clustering_engine
from backend.engines.spatial import spatial_engine
from backend.engines.semantic import semantic_engine

router = APIRouter(prefix="/discover", tags=["Discovery"])


class SimilarSitesRequest(BaseModel):
    seed_entity_ids: List[str]
    limit: int = 15


@router.post("/similar-sites")
async def discover_similar_sites(request: SimilarSitesRequest):
    all_entities = list(spatial_engine._entities.values())
    results = clustering_engine.cluster_similar_sites(
        seed_entity_ids=request.seed_entity_ids,
        entities=all_entities,
        vectors=semantic_engine._vectors_visual,
        limit=request.limit
    )
    return {
        "seeds": request.seed_entity_ids,
        "clusters": results
    }


@router.get("/co-change")
async def get_co_change_graph(max_window_days: int = 21):
    """
    Co-Change Graph (§8.6):
    Surfaces groups of sites that started changing at the same time across the AOI.
    """
    all_entities = list(spatial_engine._entities.values())
    graph = clustering_engine.build_co_change_graph(
        entities=all_entities,
        max_window_days=max_window_days
    )
    return graph

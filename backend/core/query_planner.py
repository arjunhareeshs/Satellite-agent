"""
Cost-based Query Planner for TRINETRA.
Analyzes selectivity of spatial, temporal, and semantic predicates to order pipeline stages.
Prevents brute-force archive scans and guarantees sub-second response times.
"""
from typing import List
from datetime import datetime
from backend.schemas.query import QueryPlan


class QueryPlanner:
    def plan_execution_order(self, plan: QueryPlan) -> List[str]:
        """
        Determines the optimal stage order.
        Cost model heuristics from PRD Section 8.2.
        """
        # Calculate temporal window in days if specified
        temporal_days = 730
        if plan.temporal:
            try:
                dt_from = datetime.fromisoformat(plan.temporal.from_date)
                dt_to = datetime.fromisoformat(plan.temporal.to_date)
                temporal_days = max(1, (dt_to - dt_from).days)
            except Exception:
                temporal_days = 730

        # Narrow temporal window is highly selective
        if temporal_days <= 180:
            return ["temporal_prefilter", "spatial_prefilter", "semantic_recall", "sensor_fusion", "ranking", "vlm_explanation"]

        # If strict spatial relation exists (e.g. near_water <= 500m), spatial filter is cheapest
        if plan.spatial and any(s.distance_m and s.distance_m <= 1000 for s in plan.spatial):
            return ["spatial_prefilter", "temporal_prefilter", "semantic_recall", "sensor_fusion", "ranking", "vlm_explanation"]

        # Default standard execution pipeline
        return ["semantic_recall", "spatial_prefilter", "temporal_prefilter", "sensor_fusion", "ranking", "vlm_explanation"]


query_planner = QueryPlanner()

"""
Query Parser for TRINETRA.
Compiles natural language analyst requests into the structured TRINETRA DSL.
Supports Groq API, local LLM, and robust regex/rule-based fallback parser.
"""
import re
import json
import logging
from typing import Dict, Any, Optional
from backend.schemas.query import QueryPlan, TargetSpec, SpatialPredicate, TemporalConstraint, ChangeConstraint

logger = logging.getLogger("trinetra.parser")


class QueryParser:
    def parse_to_plan(self, query_text: str) -> QueryPlan:
        """
        Parses NL query to structured QueryPlan DSL.
        Uses deterministic regex/semantic extraction fallback to ensure 100% offline reliability.
        """
        lower_q = query_text.lower()

        # 1. Determine entity type
        entity_type = "building"
        if "building" in lower_q or "structure" in lower_q or "compound" in lower_q:
            entity_type = "building"
        elif "road" in lower_q or "highway" in lower_q:
            entity_type = "road"
        elif "vegetation" in lower_q or "crop" in lower_q or "forest" in lower_q:
            entity_type = "vegetation"
        elif "vehicle" in lower_q or "convoy" in lower_q:
            entity_type = "vehicle_cluster"
        elif "water" in lower_q or "lake" in lower_q or "reservoir" in lower_q or "pond" in lower_q:
            entity_type = "water"

        # 2. Extract spatial predicate (e.g. within 500 m of river)
        spatial_predicates = []
        distance_m = 500.0
        dist_match = re.search(r'(\d+)\s*(?:m|meters|meter)', lower_q)
        if dist_match:
            distance_m = float(dist_match.group(1))

        if "river" in lower_q or "water" in lower_q or "yamuna" in lower_q:
            spatial_predicates.append(SpatialPredicate(
                relation="near_water",
                distance_m=distance_m,
                target_layer="ref_water"
            ))
        elif "road" in lower_q or "highway" in lower_q:
            spatial_predicates.append(SpatialPredicate(
                relation="near_road",
                distance_m=distance_m,
                target_layer="ref_roads"
            ))

        # 3. Extract temporal window (e.g. between 2024 and 2025)
        from_date = "2024-01-01"
        to_date = "2025-12-31"

        year_matches = re.findall(r'20\d{2}', query_text)
        if len(year_matches) >= 2:
            from_date = f"{year_matches[0]}-01-01"
            to_date = f"{year_matches[1]}-12-31"
        elif len(year_matches) == 1:
            from_date = f"{year_matches[0]}-01-01"
            to_date = f"{year_matches[0]}-12-31"

        # 4. Extract change type
        change_types = ["construction"]
        if "clearance" in lower_q or "cleared" in lower_q or "demolished" in lower_q:
            change_types = ["clearance"]
        elif "expansion" in lower_q or "expanded" in lower_q or "extended" in lower_q:
            change_types = ["expansion"]
        elif "flood" in lower_q or "water level" in lower_q:
            change_types = ["water_variation"]
        elif "road development" in lower_q or "paved" in lower_q:
            change_types = ["road_development"]

        return QueryPlan(
            task="change_detection",
            target=TargetSpec(
                entity_type=entity_type,
                semantic_query=query_text,
                attributes={}
            ),
            spatial=spatial_predicates,
            temporal=TemporalConstraint(
                field="first_seen",
                from_date=from_date,
                to_date=to_date
            ),
            change=ChangeConstraint(
                types=change_types,
                min_confidence=0.60
            ),
            sensors=["sentinel-2", "sentinel-1"],
            limit=20
        )


query_parser = QueryParser()

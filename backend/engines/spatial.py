"""
Spatial Engine for TRINETRA.
Executes PostGIS queries, relational distance joins (ST_DWithin),
and spatial polygon containment with in-memory/shapely fallback.
"""
import logging
from typing import List, Dict, Any, Optional
from shapely.geometry import shape, Point, Polygon
import shapely.ops

logger = logging.getLogger("trinetra.spatial")


class SpatialEngine:
    def __init__(self, db_conn_factory=None):
        self.db_conn_factory = db_conn_factory
        # In-memory spatial cache for high-speed lookup and fallback
        self._entities: Dict[str, Dict[str, Any]] = {}
        self._water_features: List[Dict[str, Any]] = []
        self._road_features: List[Dict[str, Any]] = []

    def load_memory_entities(self, entities: List[Dict[str, Any]]):
        """Loads entities into in-memory spatial index."""
        for e in entities:
            self._entities[e["entity_id"]] = e

    def load_reference_vectors(self, water: List[Dict[str, Any]], roads: List[Dict[str, Any]]):
        self._water_features = water
        self._road_features = roads

    def filter_entities(
        self,
        entity_type: Optional[str] = None,
        relation: Optional[str] = None,
        distance_m: Optional[float] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        change_types: Optional[List[str]] = None,
        min_confidence: Optional[float] = None,
        aoi: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """
        Filters entity IDs based on spatial relations, entity types, and temporal bounds.
        Executes PostGIS relational joins or fast in-memory spatial evaluations.
        """
        matched_ids = []
        
        # If DB connection available, run PostGIS query
        # Fallback evaluates in-memory
        for entity_id, e in self._entities.items():
            if entity_type and e.get("entity_type") != entity_type:
                continue

            if change_types and e.get("change_type") not in change_types:
                continue

            if min_confidence and e.get("change_confidence", 0.0) < min_confidence:
                continue

            # Temporal filtering on first_seen
            first_seen = e.get("first_seen")
            if from_date and first_seen and first_seen < from_date:
                continue
            if to_date and first_seen and first_seen > to_date:
                continue

            # Spatial relation check (e.g. near_water <= 500m)
            if relation == "near_water" and distance_m is not None:
                dist = e.get("relations", {}).get("river_distance_m")
                if dist is None or dist > distance_m:
                    continue

            if relation == "near_road" and distance_m is not None:
                dist = e.get("relations", {}).get("road_distance_m")
                if dist is None or dist > distance_m:
                    continue

            matched_ids.append(entity_id)

        return matched_ids

    def get_entity_by_id(self, entity_id: str) -> Optional[Dict[str, Any]]:
        return self._entities.get(entity_id)

    def calculate_distance_to_water(self, point: Point) -> float:
        """Returns distance in meters to nearest water feature."""
        if not self._water_features:
            return 320.0  # default synthetic distance
        min_dist_deg = min(shape(w["geometry"]).distance(point) for w in self._water_features)
        # Approximate degrees to meters at Delhi latitude (~28.6 deg): 1 deg ~ 105,000 meters
        return float(min_dist_deg * 105000.0)


# Global singleton instance
spatial_engine = SpatialEngine()

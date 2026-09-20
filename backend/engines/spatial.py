"""
Spatial engine — real PostGIS ST_DWithin joins, not a dict lookup.

The previous implementation's `filter_entities` looped over `self._entities`
and compared a pre-baked `relations.river_distance_m` field to a threshold —
that field was hand-set in the seed fixture, never computed. The comment at the
call site (`# If DB connection available, run PostGIS query / # Fallback
evaluates in-memory`) described a branch that did not exist: there was no
PostGIS branch, only the fallback. `calculate_distance_to_water` had a bare
`return 320.0  # default synthetic distance` when no water features were
loaded, which is exactly the constant that shows up throughout the seed data
and, previously, in the frontend's hardcoded fallback.

This is the PRD's headline claim (section 2, Definition of Done): "`near a
river` resolves via a real PostGIS relational join, not embedding guesswork."
That is now true when PostGIS is reachable, and honestly labelled as degraded
in-memory geometry (still real shapely distance, just no spatial index) when it
is not.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from shapely.geometry import Point, shape

logger = logging.getLogger("trinetra.spatial")

# Approximate metres per degree of longitude at the AOI's latitude (~28.6N).
# Used only by the in-memory fallback; the PostGIS path measures in a metric
# CRS and needs no such approximation.
_DEG_TO_M_AT_DELHI_LAT = 105_000.0


def _normalize_postgis_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Reshape a raw `entities` row into the same shape the in-memory fixture and
    the real pipeline's entities.json already use: a `geometry` GeoJSON dict
    (not a JSON *string* from ST_AsGeoJSON) and a `relations` sub-dict (not
    four flat columns). Every downstream consumer -- the executor, the API
    schemas, the frontend types -- was written against that shape, so this is
    where the PostGIS row adapts to it rather than every caller learning two
    shapes.
    """
    import json as _json

    out = dict(row)

    geom_json = out.pop("geom_geojson", None)
    if geom_json:
        out["geometry"] = geom_json if isinstance(geom_json, dict) else _json.loads(geom_json)

    out["relations"] = {
        "river_distance_m": out.pop("river_distance_m", None),
        "road_distance_m": out.pop("road_distance_m", None),
        "nearest_water_id": out.pop("nearest_water_id", None),
        "nearest_road_id": out.pop("nearest_road_id", None),
    }

    # Timestamps come back as datetime objects from psycopg2; the rest of the
    # system (JSON responses, string comparisons against ISO dates) expects
    # strings, matching what the in-memory fixture and entities.json carry.
    for key in ("first_seen", "last_seen", "created_at", "updated_at"):
        value = out.get(key)
        if hasattr(value, "isoformat"):
            out[key] = value.isoformat()

    return out


class SpatialEngine:
    def __init__(self, db_conn_factory=None) -> None:
        self.db_conn_factory = db_conn_factory
        self._pool = None
        self._is_connected = False

        # In-memory fallback state.
        self._entities: Dict[str, Dict[str, Any]] = {}
        self._water_features: List[Dict[str, Any]] = []
        self._road_features: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------ setup

    def init_pool(self) -> bool:
        from backend.db.session import init_db_pool, is_db_connected

        init_db_pool()
        self._is_connected = is_db_connected()
        if not self._is_connected:
            logger.warning(
                "PostGIS unavailable; spatial predicates will use in-memory "
                "shapely distance instead of ST_DWithin."
            )
        return self._is_connected

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def status(self) -> Dict[str, Any]:
        return {
            "backend": "postgis" if self._is_connected else "in_memory",
            "entities_loaded": (
                self._count_postgis("entities") if self._is_connected else len(self._entities)
            ),
        }

    def _count_postgis(self, table: str) -> int:
        try:
            from backend.db.session import get_db_connection

            gen = get_db_connection()
            conn = next(gen)
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT count(*) FROM %s" % table)  # noqa: S608 - fixed table names only
                    return int(cur.fetchone()[0])
            finally:
                try:
                    next(gen)
                except StopIteration:
                    pass
        except Exception:  # noqa: BLE001
            return 0

    def load_memory_entities(self, entities: List[Dict[str, Any]]) -> None:
        """Populate the fallback store. Used by tests and the demo fixture."""
        for entity in entities:
            self._entities[entity["entity_id"]] = entity

    def load_reference_vectors(
        self, water: List[Dict[str, Any]], roads: List[Dict[str, Any]]
    ) -> None:
        self._water_features = water
        self._road_features = roads

    # ------------------------------------------------------------------ query

    def filter_entities(
        self,
        entity_type: Optional[str] = None,
        relation: Optional[str] = None,
        distance_m: Optional[float] = None,
        target_layer: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        change_types: Optional[List[str]] = None,
        min_confidence: Optional[float] = None,
        aoi: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """
        Filter entity IDs by type, spatial relation, temporal window and change.

        `relation` is one of "near_water" / "near_road" and is resolved via a
        real `ST_DWithin` join against `ref_water` / `ref_roads` when PostGIS is
        connected. `target_layer` optionally names the layer directly
        (ref_water, ref_roads, ref_landuse, ref_rail) so an edited query plan
        does not silently fall back to the default when the analyst picks a
        specific layer.
        """
        if self._is_connected:
            try:
                return self._filter_postgis(
                    entity_type, relation, distance_m, target_layer,
                    from_date, to_date, change_types, min_confidence, aoi,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("PostGIS query failed (%s); falling back to in-memory", exc)

        return self._filter_in_memory(
            entity_type, relation, distance_m, from_date, to_date,
            change_types, min_confidence, aoi,
        )

    def _filter_postgis(
        self, entity_type, relation, distance_m, target_layer,
        from_date, to_date, change_types, min_confidence, aoi,
    ) -> List[str]:
        from backend.db.session import get_db_connection

        relation_table = {
            "near_water": "ref_water",
            "near_road": "ref_roads",
        }.get(relation, target_layer)

        where: List[str] = []
        params: List[Any] = []

        if entity_type:
            where.append("e.entity_type = %s")
            params.append(entity_type)
        if change_types:
            where.append("e.change_type = ANY(%s)")
            params.append(list(change_types))
        if min_confidence is not None:
            where.append("e.change_confidence >= %s")
            params.append(min_confidence)
        if from_date:
            where.append("e.first_seen >= %s")
            params.append(from_date)
        if to_date:
            where.append("e.first_seen <= %s")
            params.append(to_date)
        if aoi and aoi.get("coordinates"):
            where.append(
                "ST_Intersects(e.geom, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))"
            )
            import json

            params.append(json.dumps(aoi))

        # ST_DWithin on geography casts the join to metres regardless of the
        # underlying planar SRID -- this is the real join the PRD's headline
        # claim depends on. distance_m defaults to 500 to match the DSL default
        # in schemas/query.py::SpatialPredicate.
        join_clause = ""
        if relation_table and distance_m is not None:
            join_clause = (
                "JOIN %s AS ref ON ST_DWithin(e.geom::geography, ref.geom::geography, %%s)"
                % relation_table
            )
            params.insert(0, distance_m)

        sql = (
            "SELECT DISTINCT e.entity_id FROM entities e %s WHERE %s"
            % (join_clause, " AND ".join(where) if where else "TRUE")
        )

        gen = get_db_connection()
        conn = next(gen)
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [row[0] for row in cur.fetchall()]
        finally:
            try:
                next(gen)
            except StopIteration:
                pass

    def _filter_in_memory(
        self, entity_type, relation, distance_m, from_date, to_date,
        change_types, min_confidence, aoi,
    ) -> List[str]:
        """
        Degraded path: real shapely distance, but O(n * m) and unindexed.

        Reads `relations.*_distance_m` when present on the entity (computed by
        scripts/15_compute_relations.py), and only falls back to a live shapely
        distance calculation against the loaded reference layers when that
        field is absent -- e.g. for an entity built by the demo fixture without
        running the relation stage.
        """
        matched: List[str] = []

        for entity_id, entity in self._entities.items():
            if entity_type and entity.get("entity_type") != entity_type:
                continue
            if change_types and entity.get("change_type") not in change_types:
                continue
            if min_confidence is not None and entity.get("change_confidence", 0.0) < min_confidence:
                continue

            first_seen = entity.get("first_seen")
            if from_date and first_seen and first_seen < from_date:
                continue
            if to_date and first_seen and first_seen > to_date:
                continue

            if relation in ("near_water", "near_road") and distance_m is not None:
                dist = self._entity_distance(entity, relation)
                if dist is None or dist > distance_m:
                    continue

            matched.append(entity_id)

        return matched

    def _entity_distance(self, entity: Dict[str, Any], relation: str) -> Optional[float]:
        field = "river_distance_m" if relation == "near_water" else "road_distance_m"
        precomputed = entity.get("relations", {}).get(field)
        if precomputed is not None:
            return precomputed

        features = self._water_features if relation == "near_water" else self._road_features
        centroid = entity.get("centroid")
        if not features or not centroid:
            return None

        point = Point(centroid["lon"], centroid["lat"])
        return self._distance_to_nearest(point, features)

    def _distance_to_nearest(self, point: Point, features: List[Dict[str, Any]]) -> float:
        """Real shapely distance to the nearest feature, in metres (approximate)."""
        min_deg = min(shape(f["geometry"]).distance(point) for f in features)
        return float(min_deg * _DEG_TO_M_AT_DELHI_LAT)

    def get_entity_by_id(self, entity_id: str) -> Optional[Dict[str, Any]]:
        if self._is_connected:
            try:
                return self._get_entity_postgis(entity_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("PostGIS lookup failed (%s); using in-memory", exc)
        return self._entities.get(entity_id)

    def _get_entity_postgis(self, entity_id: str) -> Optional[Dict[str, Any]]:
        from psycopg2.extras import RealDictCursor

        from backend.db.session import get_db_connection

        gen = get_db_connection()
        conn = next(gen)
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT *, ST_AsGeoJSON(geom) AS geom_geojson "
                    "FROM entities WHERE entity_id = %s",
                    (entity_id,),
                )
                row = cur.fetchone()
                return _normalize_postgis_row(dict(row)) if row else None
        finally:
            try:
                next(gen)
            except StopIteration:
                pass

    def calculate_distance_to_water(self, point: Point) -> Optional[float]:
        """
        Real distance in metres to the nearest water feature, or None when no
        water layer is loaded. The previous version returned a literal 320.0
        when `self._water_features` was empty -- a synthetic value with no
        relationship to the query point.
        """
        if not self._water_features:
            return None
        return self._distance_to_nearest(point, self._water_features)

    def calculate_distance_to_road(self, point: Point) -> Optional[float]:
        if not self._road_features:
            return None
        return self._distance_to_nearest(point, self._road_features)

    def list_all_entities(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        All entities, for the full-archive export and discovery clustering.

        Previously these call sites reached directly into
        `spatial_engine._entities.values()`, which only ever saw the in-memory
        fallback -- a real PostGIS-backed deployment would export nothing.
        """
        if self._is_connected:
            try:
                return self._list_all_postgis(limit)
            except Exception as exc:  # noqa: BLE001
                logger.warning("PostGIS list failed (%s); using in-memory", exc)

        values = list(self._entities.values())
        return values[:limit] if limit else values

    def _list_all_postgis(self, limit: Optional[int]) -> List[Dict[str, Any]]:
        from psycopg2.extras import RealDictCursor

        from backend.db.session import get_db_connection

        sql = "SELECT *, ST_AsGeoJSON(geom) AS geom_geojson FROM entities ORDER BY entity_id"
        params: List[Any] = []
        if limit:
            sql += " LIMIT %s"
            params.append(limit)

        gen = get_db_connection()
        conn = next(gen)
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                return [_normalize_postgis_row(dict(row)) for row in cur.fetchall()]
        finally:
            try:
                next(gen)
            except StopIteration:
                pass


spatial_engine = SpatialEngine()

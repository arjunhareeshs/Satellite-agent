from typing import List, Optional, Dict, Any, Union, Literal
from pydantic import BaseModel, Field
from datetime import datetime


class TargetSpec(BaseModel):
    entity_type: str = Field(..., description="Target class, e.g. building, road, water, vegetation, bare_ground")
    semantic_query: str = Field(..., description="Query for RemoteCLIP semantic embedding, e.g. 'new building or structure'")
    attributes: Dict[str, Any] = Field(default_factory=dict, description="e.g. area_m2_min, area_m2_max")


class SpatialPredicate(BaseModel):
    relation: str = Field(..., description="near_water | near_road | near_rail | within_aoi")
    distance_m: Optional[float] = Field(500.0, description="Proximity threshold in meters")
    target_layer: Optional[str] = Field(None, description="ref_water | ref_roads")


class TemporalConstraint(BaseModel):
    field: str = Field("first_seen", description="first_seen | last_seen | change_date")
    from_date: str = Field(..., alias="from", description="YYYY-MM-DD")
    to_date: str = Field(..., alias="to", description="YYYY-MM-DD")

    class Config:
        populate_by_name = True


class ChangeConstraint(BaseModel):
    types: List[str] = Field(default_factory=lambda: ["construction"], description="construction, clearance, road_development, expansion, water_variation")
    min_confidence: float = Field(0.60, ge=0.0, le=1.0)


class QueryPlan(BaseModel):
    task: str = Field("change_detection", description="change_detection | search | similar")
    target: TargetSpec
    spatial: List[SpatialPredicate] = Field(default_factory=list)
    temporal: Optional[TemporalConstraint] = None
    change: Optional[ChangeConstraint] = None
    aoi: Optional[Dict[str, Any]] = None
    sensors: List[str] = Field(default_factory=lambda: ["sentinel-2", "sentinel-1"])
    limit: int = Field(20, ge=1, le=100)


class SearchRequest(BaseModel):
    query: str
    aoi: Optional[Dict[str, Any]] = None
    limit: int = 20
    explain_top_n: int = 5


class ExecutePlanRequest(BaseModel):
    plan: QueryPlan
    limit: int = 20
    explain_top_n: int = 5


class LocationPoint(BaseModel):
    lat: float
    lon: float


class GeoJSONGeometry(BaseModel):
    type: str = "Polygon"
    coordinates: List[Any]


class EntityScores(BaseModel):
    semantic: float = 0.0
    visual: float = 0.0
    temporal: float = 0.0
    spatial: float = 0.0
    sensor: float = 0.0
    final: float = 0.0


class GateResult(BaseModel):
    """
    One gate of the five-gate false-alarm cascade (PRD section 7.7).

    fusion.py has always computed these -- `passed`, the measured `metric`, and
    the `threshold` it was tested against -- and executor.py has always consumed
    the result. But only the aggregate fusion_score survived into the response,
    so the frontend had no per-gate truth to render and displayed five
    unconditional green checks with a hardcoded "All 5 Gates Passed" heading.
    Carrying the gates through is what lets the evidence panel be honest.
    """

    name: str
    passed: bool
    metric: str = ""
    threshold: str = ""


class EntityEvidence(BaseModel):
    optical: bool = True
    sar: bool = False
    temporal_persistence: bool = True
    observations_after_break: int = 0
    optical_z: Optional[float] = 0.0
    sar_z: Optional[float] = 0.0
    registration_residual_px: Optional[float] = 0.18
    cloud_free_pct: Optional[float] = 96.5
    explanation: str = ""

    gates: List[GateResult] = Field(default_factory=list)
    gates_passed: int = 0
    gates_total: int = 0

    # How the explanation above was produced, so the UI can label template
    # output as a template rather than presenting it as model reasoning.
    explanation_provider: str = ""
    explanation_model: str = ""
    explanation_degraded: bool = False


class EntityRelations(BaseModel):
    river_distance_m: Optional[float] = None
    road_distance_m: Optional[float] = None
    nearest_water_id: Optional[str] = None
    nearest_road_id: Optional[str] = None


class EntityImagery(BaseModel):
    before: str
    after: str
    sar: Optional[str] = None


class EntityProvenance(BaseModel):
    source_scenes: List[str] = Field(default_factory=list)
    sensors: List[str] = Field(default_factory=list)
    processing_chain: List[str] = Field(default_factory=list)
    model_manifest_hash: str = ""


class SearchResult(BaseModel):
    rank: int
    entity_id: str
    entity_type: str
    location: LocationPoint
    geometry: GeoJSONGeometry
    area_m2: float
    change_type: str
    first_seen: str
    first_seen_ci: List[str]
    ci_width_days: int
    confidence: float
    scores: EntityScores
    evidence: EntityEvidence
    relations: EntityRelations
    imagery: EntityImagery
    provenance: EntityProvenance


class ExecutionDetails(BaseModel):
    stage_counts: Dict[str, int]
    latency_ms: Dict[str, float]


class SearchResponse(BaseModel):
    query_id: str
    query: str
    plan: QueryPlan
    execution: ExecutionDetails
    results: List[SearchResult]


class TimelinePoint(BaseModel):
    t: str
    observed_embed_norm: float
    baseline_embed_norm: float
    residual: float
    z_score: float
    valid_fraction: float
    sensor: str
    ndvi: Optional[float] = None
    sar_vv_db: Optional[float] = None


class TimelineResponse(BaseModel):
    entity_id: str
    h3_r9: str
    status: str
    break_date_estimate: Optional[str] = None
    break_date_ci: Optional[List[str]] = None
    ci_width_days: Optional[int] = None
    change_type: Optional[str] = None
    confidence: float = 0.0
    trajectory: List[TimelinePoint]


class VerdictRequest(BaseModel):
    # Previously a bare str, so any string was accepted and written to the
    # audit ledger verbatim -- a typo'd verdict became a permanent, hash-chained
    # ledger entry with no way to distinguish it from a real confirm/reject.
    verdict: Literal["confirm", "reject"]
    analyst: str = Field("analyst_01")
    note: Optional[str] = ""


class VerdictResponse(BaseModel):
    status: str
    entity_id: str
    log_id: int
    entry_hash: str
    prev_hash: Optional[str] = None
    message: str


class IngestRequest(BaseModel):
    scene_path: str
    sensor: str = "sentinel-2"


class IngestResponse(BaseModel):
    job_id: str
    status: str
    estimated_duration_sec: int = 45
    message: str


class ArchiveStatsResponse(BaseModel):
    aoi_name: str
    bounds: Dict[str, float]
    date_range: Dict[str, str]
    total_scenes: int
    sentinel2_scenes: int
    sentinel1_scenes: int
    total_chips: int
    total_entities: int
    storage_footprint: Dict[str, str]
    index_build_time_sec: float
    hardware: str

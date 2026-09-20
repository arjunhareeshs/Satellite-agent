/**
 * Types matching backend/schemas/query.py, hand-authored against the live
 * Pydantic models rather than generated from an OpenAPI schema.
 *
 * This replaces three separate hand-transcribed copies that had already
 * drifted from the backend and from each other:
 *   - ResultCard.tsx's `SearchResultItem` (missing `geometry` entirely --
 *     the backend always sends a Polygon and the map discarded it)
 *   - PlanEditor.tsx's `QueryPlanDSL` (missing `aoi` and `sensors`, so an
 *     analyst's plan edit silently dropped both on re-execute)
 *   - TrajectoryChart.tsx's `TrajectoryPoint` (a partial, ad-hoc subset)
 *
 * One file, one shape, every field the backend actually returns. When the
 * backend's OpenAPI schema stabilizes, `make types` can replace this with a
 * generated file without changing any import site, since every export here
 * is named to match a backend model 1:1.
 */

// ---------------------------------------------------------------- query DSL

export interface TargetSpec {
  entity_type: string;
  semantic_query: string;
  attributes: Record<string, unknown>;
}

export interface SpatialPredicate {
  relation: string; // near_water | near_road | near_rail | within_aoi
  distance_m?: number | null;
  target_layer?: string | null; // ref_water | ref_roads
}

export interface TemporalConstraint {
  field: string; // first_seen | last_seen | change_date
  from: string; // YYYY-MM-DD (backend alias for from_date)
  to: string; // YYYY-MM-DD (backend alias for to_date)
}

export interface ChangeConstraint {
  types: string[];
  min_confidence: number;
}

export interface QueryPlan {
  task: string; // change_detection | search | similar
  target: TargetSpec;
  spatial: SpatialPredicate[];
  temporal?: TemporalConstraint | null;
  change?: ChangeConstraint | null;
  aoi?: Record<string, unknown> | null;
  sensors: string[];
  limit: number;
}

export interface SearchRequest {
  query: string;
  aoi?: Record<string, unknown> | null;
  limit?: number;
  explain_top_n?: number;
}

export interface ExecutePlanRequest {
  plan: QueryPlan;
  limit?: number;
  explain_top_n?: number;
}

// ---------------------------------------------------------------- entities

export interface LocationPoint {
  lat: number;
  lon: number;
}

export interface GeoJSONGeometry {
  type: string;
  coordinates: unknown[];
}

export interface EntityScores {
  semantic: number;
  visual: number;
  temporal: number;
  spatial: number;
  sensor: number;
  final: number;
}

/** One gate of the five-gate false-alarm cascade (PRD section 7.7). */
export interface GateResult {
  name: string;
  passed: boolean;
  metric: string;
  threshold: string;
}

export interface EntityEvidence {
  optical: boolean;
  sar: boolean;
  temporal_persistence: boolean;
  observations_after_break: number;
  optical_z?: number | null;
  sar_z?: number | null;
  registration_residual_px?: number | null;
  cloud_free_pct?: number | null;
  explanation: string;
  /** Real per-gate results. Render these instead of hardcoding "All 5 Gates Passed". */
  gates: GateResult[];
  gates_passed: number;
  gates_total: number;
  /** How `explanation` was produced -- label template output as a template, not a model. */
  explanation_provider: string;
  explanation_model: string;
  explanation_degraded: boolean;
}

export interface EntityRelations {
  river_distance_m?: number | null;
  road_distance_m?: number | null;
  nearest_water_id?: string | null;
  nearest_road_id?: string | null;
}

export interface EntityImagery {
  before: string;
  after: string;
  sar?: string | null;
}

export interface EntityProvenance {
  source_scenes: string[];
  sensors: string[];
  processing_chain: string[];
  model_manifest_hash: string;
}

export interface SearchResult {
  rank: number;
  entity_id: string;
  entity_type: string;
  location: LocationPoint;
  /** Real GeoJSON polygon. Draw this on the map -- do not fall back to a marker only. */
  geometry: GeoJSONGeometry;
  area_m2: number;
  change_type: string;
  first_seen: string;
  first_seen_ci: string[];
  ci_width_days: number;
  confidence: number;
  scores: EntityScores;
  evidence: EntityEvidence;
  relations: EntityRelations;
  imagery: EntityImagery;
  provenance: EntityProvenance;
}

export interface ExecutionDetails {
  stage_counts: Record<string, number>;
  latency_ms: Record<string, number>;
}

export interface SearchResponse {
  query_id: string;
  query: string;
  plan: QueryPlan;
  execution: ExecutionDetails;
  results: SearchResult[];
}

// ---------------------------------------------------------------- timeline

export interface TimelinePoint {
  t: string;
  observed_embed_norm: number;
  baseline_embed_norm: number;
  residual: number;
  z_score: number;
  valid_fraction: number;
  sensor: string;
  ndvi?: number | null;
  sar_vv_db?: number | null;
}

export interface TimelineResponse {
  entity_id: string;
  h3_r9: string;
  status: string;
  break_date_estimate?: string | null;
  break_date_ci?: [string, string] | string[] | null;
  ci_width_days?: number | null;
  change_type?: string | null;
  confidence: number;
  trajectory: TimelinePoint[];
}

// ---------------------------------------------------------------- verdict / export

export type Verdict = 'confirm' | 'reject';

export interface VerdictRequest {
  verdict: Verdict;
  analyst?: string;
  note?: string | null;
}

export interface VerdictResponse {
  status: string;
  entity_id: string;
  log_id: number;
  entry_hash: string;
  prev_hash?: string | null;
  message: string;
}

// ---------------------------------------------------------------- system

export interface ModelManifestStatus {
  ok: boolean;
  checked: number;
  missing: string[];
  mismatched: string[];
  unhashed: string[];
  manifest_hash_ok: boolean;
  message: string;
}

export interface VlmProviderStatus {
  configured: string;
  active: string;
  degraded: boolean;
}

export interface QdrantStatus {
  backend: 'qdrant' | 'in_memory';
  host: string;
  collection: string;
  points_count?: number;
  vectors?: string[];
  error?: string;
}

export interface AuditLedgerStatus {
  backend: 'postgresql' | 'in_memory';
  entries: number;
  chain_valid: boolean;
}

export interface ProjDataStatus {
  applied: string | null;
  inherited_proj_lib: string | null;
  inherited_proj_data: string | null;
  overridden: boolean;
}

export interface HealthStatus {
  status: string;
  postgis: 'connected' | 'in_memory_fallback';
  qdrant: QdrantStatus;
  tileserver: string;
  vlm_provider: VlmProviderStatus;
  model_manifest: ModelManifestStatus;
  proj_data: ProjDataStatus;
  total_indexed_entities: number;
  audit_ledger: AuditLedgerStatus;
  offline_compliant: boolean;
}

export interface ArchiveStats {
  aoi_name: string | null;
  bounds: { min_lon: number; min_lat: number; max_lon: number; max_lat: number } | null;
  area_km2: number | null;
  date_range: { start: string; end: string } | null;
  total_scenes: number;
  sentinel2_scenes: number;
  sentinel1_scenes: number;
  coverage_gaps: { sentinel2: string[]; sentinel1: string[] };
  total_chips: number;
  usable_chips: number;
  total_entities: number;
  entities_by_type: Record<string, number>;
  storage_footprint: { total: string; raw: string; processed: string; models: string } | null;
  index_build_time_sec: number | null;
  hardware: string | null;
  query_latency_ms?: { n_queries: number; p50_ms: number; p95_ms: number; min_ms: number; max_ms: number } | null;
  measured_at?: string | null;
}

// ---------------------------------------------------------------- entity detail

/**
 * `GET /entity/{id}` has no `response_model` on the backend -- it returns
 * whatever dict shape the entity actually has, which differs slightly between
 * the in-memory fixture, the real pipeline's entities.json, and a PostGIS row
 * (normalized by `_normalize_postgis_row` to match the other two). This type
 * is the common, reliable subset; treat anything beyond it as unknown.
 */
export interface EntityRecord {
  entity_id: string;
  entity_type: string;
  class_confidence?: number;
  geometry?: GeoJSONGeometry;
  centroid?: LocationPoint;
  h3_r9?: string;
  area_m2?: number;
  orientation_deg?: number;
  first_seen?: string;
  first_seen_ci?: string[];
  last_seen?: string;
  change_type?: string;
  change_confidence?: number;
  sensors?: string[];
  source_scenes?: string[];
  description?: string;
  relations?: EntityRelations;
  imagery?: EntityImagery;
  [key: string]: unknown;
}

// ---------------------------------------------------------------- discovery

export interface SimilarSitesResponse {
  query_entity_id?: string;
  seeds?: string[];
  similar_entities?: Array<{
    entity_id: string;
    visual_score?: number;
    semantic_score?: number;
    raw_cosine: number;
    payload: Record<string, unknown>;
  }>;
  clusters?: unknown[];
}

export interface CoChangeNode {
  id: string;
  type: string;
  change_type?: string;
  first_seen?: string;
  location?: LocationPoint;
  area_m2?: number;
}

export interface CoChangeEdge {
  source: string;
  target: string;
  delta_days: number;
  weight: number;
  common_window: string;
}

export interface CoChangeGraph {
  nodes: CoChangeNode[];
  edges: CoChangeEdge[];
  clusters_count: number;
  description?: string;
}

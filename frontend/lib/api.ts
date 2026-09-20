/**
 * The single typed API client.
 *
 * Before this existed there were five raw `fetch` calls scattered across
 * page.tsx, EvidencePanel.tsx and CoChangeGraph.tsx, with no base URL constant,
 * no timeout, no AbortController, and error handling that was `console.error`
 * in every case. A failed request was visually indistinguishable from an empty
 * result set, and the verdict POST did not check `res.ok` at all — so a 404
 * still flipped the UI to a green "Verdict logged (Hashed to Ledger)".
 *
 * Everything goes through `request()` below, which:
 *   - resolves the base URL from NEXT_PUBLIC_API_URL rather than hardcoding it
 *   - enforces a timeout and threads through an external AbortSignal
 *   - raises a typed ApiError carrying the status and FastAPI's `detail`
 *   - refuses to silently coerce an error body into an empty result
 */

import type {
  ArchiveStats,
  CoChangeGraph,
  EntityRecord,
  ExecutePlanRequest,
  HealthStatus,
  QueryPlan,
  SearchRequest,
  SearchResponse,
  SimilarSitesResponse,
  TimelineResponse,
  VerdictRequest,
  VerdictResponse,
} from './types';

/**
 * Empty string means "same origin", which is what we want in the browser: the
 * Next rewrite in next.config.js proxies /api/v1/* to the backend, so relative
 * URLs work in dev and in a container without a rebuild. Server-side rendering
 * has no origin, so it needs the absolute URL.
 */
export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? (typeof window === 'undefined' ? 'http://localhost:8000' : '');

const API_PREFIX = '/api/v1';
const DEFAULT_TIMEOUT_MS = 30_000;

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;
  readonly path: string;

  constructor(message: string, status: number, path: string, detail?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.path = path;
    this.detail = detail;
  }

  /** True when retrying could plausibly succeed. */
  get isRetryable(): boolean {
    return this.status === 0 || this.status === 408 || this.status >= 500;
  }

  /** True when the backend is not reachable at all, rather than refusing. */
  get isOffline(): boolean {
    return this.status === 0;
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, signal, timeoutMs = DEFAULT_TIMEOUT_MS } = options;
  const url = `${API_BASE}${API_PREFIX}${path}`;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  // Honour a caller's signal (React Query passes one) alongside our timeout, so
  // switching entities quickly cancels the in-flight request instead of letting
  // a slow response overwrite a newer one.
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener('abort', () => controller.abort(), { once: true });
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (err) {
    clearTimeout(timeout);
    if ((err as Error)?.name === 'AbortError') {
      throw new ApiError('Request timed out or was cancelled', 408, path);
    }
    throw new ApiError('Cannot reach the TRINETRA backend', 0, path, err);
  } finally {
    clearTimeout(timeout);
  }

  if (!response.ok) {
    let detail: unknown;
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload?.detail ?? payload;
      if (typeof detail === 'string') message = detail;
    } catch {
      // Non-JSON error body; the status line is all we have.
    }
    throw new ApiError(message, response.status, path, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/* -------------------------------------------------------------------- routes */

export const api = {
  health: (signal?: AbortSignal) =>
    request<HealthStatus>('/health', { signal, timeoutMs: 5_000 }),

  stats: (signal?: AbortSignal) => request<ArchiveStats>('/stats', { signal }),

  search: (body: SearchRequest, signal?: AbortSignal) =>
    request<SearchResponse>('/search', { method: 'POST', body, signal, timeoutMs: 60_000 }),

  /** Compile a query to a plan without executing it — the transparency endpoint. */
  compilePlan: (body: SearchRequest, signal?: AbortSignal) =>
    request<QueryPlan>('/search/plan', { method: 'POST', body, signal }),

  executePlan: (body: ExecutePlanRequest, signal?: AbortSignal) =>
    request<SearchResponse>('/search/execute', {
      method: 'POST',
      body,
      signal,
      timeoutMs: 60_000,
    }),

  /** Image-to-image search. `entity_id` and `limit` are query params, not a body. */
  similar: (entityId: string, limit = 10, signal?: AbortSignal) =>
    request<SimilarSitesResponse>(
      `/search/similar?entity_id=${encodeURIComponent(entityId)}&limit=${limit}`,
      { method: 'POST', signal },
    ),

  entity: (entityId: string, signal?: AbortSignal) =>
    request<EntityRecord>(`/entity/${encodeURIComponent(entityId)}`, { signal }),

  timeline: (entityId: string, signal?: AbortSignal) =>
    request<TimelineResponse>(`/entity/${encodeURIComponent(entityId)}/timeline`, { signal }),

  verdict: (entityId: string, body: VerdictRequest, signal?: AbortSignal) =>
    request<VerdictResponse>(`/entity/${encodeURIComponent(entityId)}/verdict`, {
      method: 'POST',
      body,
      signal,
    }),

  coChange: (maxWindowDays = 21, signal?: AbortSignal) =>
    request<CoChangeGraph>(`/discover/co-change?max_window_days=${maxWindowDays}`, { signal }),

  similarSites: (seedEntityIds: string[], limit = 15, signal?: AbortSignal) =>
    request<SimilarSitesResponse>('/discover/similar-sites', {
      method: 'POST',
      body: { seed_entity_ids: seedEntityIds, limit },
      signal,
    }),

  /** Reference vector layers for the map, served as GeoJSON. */
  referenceLayer: (layer: 'water' | 'roads' | 'landuse' | 'rail' | 'aoi', signal?: AbortSignal) =>
    request<GeoJSON.FeatureCollection>(`/layers/${layer}`, { signal }),

  exportUrl: (queryId: string) =>
    `${API_BASE}${API_PREFIX}/export/${encodeURIComponent(queryId)}`,

  staticUrl: (path: string) => {
    if (!path) return '';
    if (path.startsWith('http')) return path;
    return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;
  },
};

export default api;

'use client';

/**
 * TanStack Query wrappers around the API client.
 *
 * These replace five raw `fetch` calls that were scattered across page.tsx,
 * EvidencePanel.tsx and CoChangeGraph.tsx with no shared caching, no
 * AbortController (the timeline fetch in particular would race and leak on
 * rapid entity switching), and error handling that was uniformly
 * `console.error` -- a failed request was visually indistinguishable from an
 * empty result set.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError } from './api';
import type {
  ExecutePlanRequest,
  HealthStatus,
  SearchRequest,
  SearchResponse,
  VerdictRequest,
} from './types';

export function useHealth() {
  return useQuery<HealthStatus>({
    queryKey: ['health'],
    queryFn: ({ signal }) => api.health(signal),
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}

export function useStats() {
  return useQuery({
    queryKey: ['stats'],
    queryFn: ({ signal }) => api.stats(signal),
    staleTime: 60_000,
  });
}

export function useTimeline(entityId: string | null) {
  return useQuery({
    queryKey: ['timeline', entityId],
    queryFn: ({ signal }) => api.timeline(entityId as string, signal),
    enabled: !!entityId,
  });
}

export function useCoChangeGraph(maxWindowDays: number, enabled: boolean) {
  return useQuery({
    queryKey: ['co-change', maxWindowDays],
    queryFn: ({ signal }) => api.coChange(maxWindowDays, signal),
    enabled,
  });
}

export function useSearch() {
  return useMutation<SearchResponse, ApiError, SearchRequest>({
    mutationFn: (body) => api.search(body),
  });
}

export function useExecutePlan() {
  return useMutation<SearchResponse, ApiError, ExecutePlanRequest>({
    mutationFn: (body) => api.executePlan(body),
  });
}

export function useVerdict(entityId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: VerdictRequest) => api.verdict(entityId, body),
    onSuccess: () => {
      // A confirm/reject changes the audit ledger's entry count; invalidate
      // rather than assume the cached health snapshot is still accurate.
      queryClient.invalidateQueries({ queryKey: ['health'] });
    },
  });
}

export function useSimilarSites(entityId: string | null) {
  return useMutation({
    mutationFn: (id: string) => api.similar(id),
  });
}

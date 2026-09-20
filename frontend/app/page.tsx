'use client';

import React, { useEffect, useState } from 'react';
import { Header } from '../components/Header';
import { SearchBox } from '../components/QueryPanel/SearchBox';
import { PlanEditor } from '../components/QueryPanel/PlanEditor';
import { ResultList } from '../components/Results/ResultList';
import { MapView } from '../components/Map/MapView';
import { EvidencePanel } from '../components/Evidence/EvidencePanel';
import { CoChangeGraph } from '../components/Discovery/CoChangeGraph';
import { SimilarSites } from '../components/Discovery/SimilarSites';
import { AlertTriangle, WifiOff } from 'lucide-react';
import type { QueryPlan, SearchResult, SimilarSitesResponse } from '@/lib/types';
import { useExecutePlan, useSearch, useStats } from '@/lib/hooks';
import { api, ApiError } from '@/lib/api';

const DEFAULT_QUERY = 'Find new structures within 500 m of the river between 2024 and 2025';

export default function Home() {
  const [results, setResults] = useState<SearchResult[]>([]);
  const [currentPlan, setCurrentPlan] = useState<QueryPlan | null>(null);
  const [selectedEntity, setSelectedEntity] = useState<SearchResult | null>(null);
  const [isEvidenceOpen, setIsEvidenceOpen] = useState(false);
  const [isCoChangeOpen, setIsCoChangeOpen] = useState(false);
  const [latencyMs, setLatencyMs] = useState<number | undefined>(undefined);

  const [similarState, setSimilarState] = useState<{
    isOpen: boolean;
    isLoading: boolean;
    data: SimilarSitesResponse | null;
    error: string | null;
  }>({ isOpen: false, isLoading: false, data: null, error: null });

  const stats = useStats();
  const searchMutation = useSearch();
  const executeMutation = useExecutePlan();

  const isLoading = searchMutation.isPending || executeMutation.isPending;
  // Whichever mutation last ran carries the current error, if any. Previously
  // every failure path here was `console.error` -- a failed request and an
  // empty result set were visually identical.
  const activeError = searchMutation.error ?? executeMutation.error ?? null;

  const applyResponse = (data: Awaited<ReturnType<typeof api.search>>) => {
    setResults(data.results);
    setCurrentPlan(data.plan);
    setLatencyMs(data.execution?.latency_ms?.total);
    if (data.results.length > 0) setSelectedEntity(data.results[0]);
  };

  const handleSearch = (queryText: string) => {
    searchMutation.mutate(
      { query: queryText, limit: 20, explain_top_n: 5 },
      { onSuccess: applyResponse }
    );
  };

  // Run the default demo query once on mount. Intentionally empty deps: this
  // fires exactly once regardless of handleSearch's identity changing on
  // later renders, matching the original "search on load" behaviour.
  useEffect(() => {
    handleSearch(DEFAULT_QUERY);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleExecutePlan = (editedPlan: QueryPlan) => {
    executeMutation.mutate(
      { plan: editedPlan, limit: editedPlan.limit, explain_top_n: 5 },
      {
        onSuccess: (data) => {
          setResults(data.results);
          // Previously the response's plan was discarded here, so the
          // PlanEditor could drift from what the backend actually executed
          // (e.g. after query_parser normalizes a date or a relation).
          setCurrentPlan(data.plan);
          setLatencyMs(data.execution?.latency_ms?.total);
          if (data.results.length > 0) setSelectedEntity(data.results[0]);
        },
      }
    );
  };

  const handleSelectEntity = (entity: SearchResult) => {
    setSelectedEntity(entity);
    setIsEvidenceOpen(true);
  };

  const handleFindSimilar = async (entityId: string) => {
    setSimilarState({ isOpen: true, isLoading: true, data: null, error: null });
    try {
      const data = await api.similar(entityId);
      setSimilarState({ isOpen: true, isLoading: false, data, error: null });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Similar-site search failed.';
      setSimilarState({ isOpen: true, isLoading: false, data: null, error: message });
    }
  };

  const handleLocateSimilar = (entityId: string) => {
    const match = results.find((r) => r.entity_id === entityId);
    if (match) {
      handleSelectEntity(match);
      setSimilarState((s) => ({ ...s, isOpen: false }));
    }
    // If it's not in the current result set, it stays listed but unselectable
    // from here -- re-hydrating a full SearchResult for an arbitrary entity_id
    // would need a dedicated backend shape this endpoint doesn't return yet.
  };

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-command-bg">
      <Header
        onOpenCoChange={() => setIsCoChangeOpen(true)}
        entityCount={results.length}
      />

      {!stats.isLoading && stats.isError && (
        <div className="flex items-center gap-2 px-4 py-1.5 bg-red-950/60 border-b border-red-900 text-red-300 text-xs font-mono">
          <WifiOff className="w-3.5 h-3.5" />
          Cannot reach the TRINETRA backend. Is it running? (`make run-backend`)
        </div>
      )}

      <div className="flex-1 flex flex-col md:flex-row overflow-hidden p-3 gap-3">
        <div className="w-full md:w-[420px] lg:w-[460px] flex flex-col gap-3 overflow-hidden flex-shrink-0">
          <SearchBox onSearch={handleSearch} isLoading={isLoading} />

          {activeError && (
            <div className="flex items-start gap-2 p-2.5 rounded bg-red-950/40 border border-red-900/50 text-red-300 text-xs font-mono">
              <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <span>
                {activeError instanceof ApiError && activeError.isOffline
                  ? 'Cannot reach the backend.'
                  : activeError.message}
              </span>
            </div>
          )}

          {currentPlan && (
            <PlanEditor
              initialPlan={currentPlan}
              onExecutePlan={handleExecutePlan}
              isLoading={isLoading}
            />
          )}

          <ResultList
            results={results}
            selectedId={selectedEntity?.entity_id}
            onSelect={handleSelectEntity}
            latencyMs={latencyMs}
          />
        </div>

        <div className="flex-1 flex flex-col h-full rounded-lg overflow-hidden border border-command-cardBorder">
          <MapView
            entities={results}
            selectedEntity={selectedEntity}
            onSelectEntity={handleSelectEntity}
            bounds={stats.data?.bounds}
          />
        </div>
      </div>

      {isEvidenceOpen && selectedEntity && (
        <EvidencePanel
          entity={selectedEntity}
          onClose={() => setIsEvidenceOpen(false)}
          onFindSimilar={handleFindSimilar}
        />
      )}

      <SimilarSites
        isOpen={similarState.isOpen}
        isLoading={similarState.isLoading}
        data={similarState.data}
        error={similarState.error}
        onClose={() => setSimilarState((s) => ({ ...s, isOpen: false }))}
        onLocate={handleLocateSimilar}
      />

      <CoChangeGraph
        isOpen={isCoChangeOpen}
        onClose={() => setIsCoChangeOpen(false)}
      />
    </div>
  );
}

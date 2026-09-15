'use client';

import React, { useState, useEffect } from 'react';
import { Header } from '../components/Header';
import { SearchBox } from '../components/QueryPanel/SearchBox';
import { PlanEditor, QueryPlanDSL } from '../components/QueryPanel/PlanEditor';
import { ResultList } from '../components/Results/ResultList';
import { SearchResultItem } from '../components/Results/ResultCard';
import { MapView } from '../components/Map/MapView';
import { EvidencePanel } from '../components/Evidence/EvidencePanel';
import { CoChangeGraph } from '../components/Discovery/CoChangeGraph';

export default function Home() {
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [currentPlan, setCurrentPlan] = useState<QueryPlanDSL | null>(null);
  const [selectedEntity, setSelectedEntity] = useState<SearchResultItem | null>(null);
  const [isEvidenceOpen, setIsEvidenceOpen] = useState(false);
  const [isCoChangeOpen, setIsCoChangeOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [latencyMs, setLatencyMs] = useState<number | undefined>(undefined);

  // Initial query search on mount
  useEffect(() => {
    handleSearch("Find new structures within 500 m of the river between 2024 and 2025");
  }, []);

  const handleSearch = async (queryText: string) => {
    setIsLoading(true);
    try {
      const res = await fetch('/api/v1/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: queryText,
          limit: 20,
          explain_top_n: 5
        })
      });

      if (!res.ok) {
        throw new Error(`Server returned status ${res.status}`);
      }

      const data = await res.json();
      setResults(data.results || []);
      setCurrentPlan(data.plan || null);
      setLatencyMs(data.execution?.latency_ms?.total);

      // Automatically select top-1 candidate for immediate inspection
      if (data.results && data.results.length > 0) {
        setSelectedEntity(data.results[0]);
      }
    } catch (err) {
      console.error("Search failed:", err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleExecutePlan = async (editedPlan: QueryPlanDSL) => {
    setIsLoading(true);
    try {
      const res = await fetch('/api/v1/search/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plan: editedPlan,
          limit: 20,
          explain_top_n: 5
        })
      });

      if (!res.ok) {
        throw new Error(`Server returned status ${res.status}`);
      }

      const data = await res.json();
      setResults(data.results || []);
      setLatencyMs(data.execution?.latency_ms?.total);

      if (data.results && data.results.length > 0) {
        setSelectedEntity(data.results[0]);
      }
    } catch (err) {
      console.error("Plan execution failed:", err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSelectEntity = (entity: SearchResultItem) => {
    setSelectedEntity(entity);
    setIsEvidenceOpen(true);
  };

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-command-bg">
      {/* Top Telemetry Header */}
      <Header
        onOpenCoChange={() => setIsCoChangeOpen(true)}
        entityCount={results.length}
      />

      {/* Main Command & Control Workspace */}
      <div className="flex-1 flex flex-col md:flex-row overflow-hidden p-3 gap-3">
        {/* Left Side: Intelligence Retrieval & Review Queue (~420px) */}
        <div className="w-full md:w-[420px] lg:w-[460px] flex flex-col gap-3 overflow-hidden flex-shrink-0">
          {/* Natural Language Query Box */}
          <SearchBox onSearch={handleSearch} isLoading={isLoading} />

          {/* Transparency Form / Plan Editor */}
          {currentPlan && (
            <PlanEditor
              initialPlan={currentPlan}
              onExecutePlan={handleExecutePlan}
              isLoading={isLoading}
            />
          )}

          {/* Ranked Review Queue */}
          <ResultList
            results={results}
            selectedId={selectedEntity?.entity_id}
            onSelect={handleSelectEntity}
            latencyMs={latencyMs}
          />
        </div>

        {/* Center / Right: Interactive Map Surface */}
        <div className="flex-1 flex flex-col h-full rounded-lg overflow-hidden border border-command-cardBorder">
          <MapView
            entities={results}
            selectedEntity={selectedEntity}
            onSelectEntity={handleSelectEntity}
          />
        </div>
      </div>

      {/* Evidence Inspector Drawer (Opens on candidate select) */}
      {isEvidenceOpen && selectedEntity && (
        <EvidencePanel
          entity={selectedEntity}
          onClose={() => setIsEvidenceOpen(false)}
        />
      )}

      {/* Synchronized Co-Change Graph Modal */}
      <CoChangeGraph
        isOpen={isCoChangeOpen}
        onClose={() => setIsCoChangeOpen(false)}
      />
    </div>
  );
}

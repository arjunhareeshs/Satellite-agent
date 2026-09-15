'use client';

import React, { useState, useEffect } from 'react';
import { SearchResultItem } from '../Results/ResultCard';
import { BeforeAfterSwipe } from './BeforeAfterSwipe';
import { TrajectoryChart, TrajectoryPoint } from './TrajectoryChart';
import { EvidenceChecklist } from './EvidenceChecklist';
import { ProvenanceBlock } from './ProvenanceBlock';
import { Check, X, Download, Share2, Compass, CheckCircle2, Shield } from 'lucide-react';

interface EvidencePanelProps {
  entity: SearchResultItem | null;
  onClose: () => void;
  onFindSimilar?: (entityId: string) => void;
}

export const EvidencePanel: React.FC<EvidencePanelProps> = ({ entity, onClose, onFindSimilar }) => {
  const [trajectory, setTrajectory] = useState<TrajectoryPoint[]>([]);
  const [verdictStatus, setVerdictStatus] = useState<string | null>(null);
  const [isLoadingTimeline, setIsLoadingTimeline] = useState(false);

  useEffect(() => {
    if (!entity) return;
    setVerdictStatus(null);
    setIsLoadingTimeline(true);

    // Fetch entity timeline from backend
    fetch(`/api/v1/entity/${entity.entity_id}/timeline`)
      .then(res => res.json())
      .then(data => {
        if (data.trajectory) {
          setTrajectory(data.trajectory);
        }
      })
      .catch(err => {
        console.error("Failed to fetch timeline:", err);
      })
      .finally(() => {
        setIsLoadingTimeline(false);
      });
  }, [entity]);

  if (!entity) return null;

  const handleVerdict = async (verdict: 'confirm' | 'reject') => {
    try {
      const res = await fetch(`/api/v1/entity/${entity.entity_id}/verdict`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          verdict,
          analyst: 'analyst_01',
          note: `Analyst decision: ${verdict.toUpperCase()}`
        })
      });
      const data = await res.json();
      setVerdictStatus(verdict);
    } catch (err) {
      console.error("Failed to submit verdict:", err);
    }
  };

  return (
    <div className="fixed inset-y-0 right-0 w-full sm:w-[580px] lg:w-[680px] bg-command-bg border-l border-command-cardBorder shadow-2xl z-50 flex flex-col overflow-hidden animate-in slide-in-from-right duration-200">
      {/* Drawer Header */}
      <div className="p-4 border-b border-command-cardBorder bg-command-sidebar flex items-center justify-between">
        <div>
          <div className="flex items-center space-x-2">
            <span className="font-mono text-base font-bold text-slate-100">{entity.entity_id}</span>
            <span className="text-xs uppercase font-mono px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800 font-semibold">
              {entity.change_type}
            </span>
            <span className="text-xs font-mono font-bold text-emerald-400 bg-emerald-950 px-2 py-0.5 rounded border border-emerald-900">
              {Math.round(entity.confidence * 100)}% Conf
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1 font-sans">
            {entity.evidence.explanation || "Persistent multi-temporal structural regime break detected."}
          </p>
        </div>

        <button
          type="button"
          onClick={onClose}
          className="w-7 h-7 rounded-full bg-slate-800 hover:bg-slate-700 text-slate-300 flex items-center justify-center transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Drawer Scrollable Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* 1. Before/After Swipe */}
        <BeforeAfterSwipe
          beforeUrl={entity.imagery.before}
          afterUrl={entity.imagery.after}
          sarUrl={entity.imagery.sar}
          beforeDate="2024-07-11"
          afterDate="2025-06-14"
        />

        {/* 2. Trajectory Chart */}
        {isLoadingTimeline ? (
          <div className="h-44 bg-command-card border border-command-cardBorder rounded-lg flex items-center justify-center text-xs font-mono text-slate-500">
            <span className="inline-block w-4 h-4 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin mr-2" />
            Loading 24-Month Embedding Trajectory...
          </div>
        ) : (
          <TrajectoryChart
            trajectory={trajectory}
            breakDate={entity.first_seen}
            breakDateCi={entity.first_seen_ci}
            ciWidthDays={entity.ci_width_days}
          />
        )}

        {/* 3. Evidence Checklist */}
        <EvidenceChecklist
          opticalZ={entity.evidence.optical_z}
          sarZ={entity.evidence.sar_z}
          residualPx={entity.evidence.registration_residual_px}
          cloudFreePct={entity.evidence.cloud_free_pct}
          confidence={entity.confidence}
          sarConfirmed={entity.evidence.sar}
        />

        {/* 4. Provenance Block */}
        <ProvenanceBlock
          sourceScenes={entity.provenance.source_scenes}
          sensors={entity.provenance.sensors}
          processingChain={entity.provenance.processing_chain}
          manifestHash={entity.provenance.model_manifest_hash}
        />
      </div>

      {/* Drawer Action Bar */}
      <div className="p-3.5 border-t border-command-cardBorder bg-command-sidebar flex items-center justify-between gap-2">
        <div className="flex items-center space-x-2">
          {verdictStatus ? (
            <div className="flex items-center space-x-1.5 px-3 py-1.5 rounded bg-emerald-950 border border-emerald-800 text-emerald-400 text-xs font-mono">
              <CheckCircle2 className="w-4 h-4" />
              <span>Verdict: {verdictStatus.toUpperCase()} (Hashed to Ledger)</span>
            </div>
          ) : (
            <>
              <button
                type="button"
                onClick={() => handleVerdict('confirm')}
                className="flex items-center space-x-1.5 px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-slate-950 text-xs font-mono font-bold transition-colors shadow"
              >
                <Check className="w-3.5 h-3.5 text-slate-950" />
                <span>Confirm</span>
              </button>

              <button
                type="button"
                onClick={() => handleVerdict('reject')}
                className="flex items-center space-x-1.5 px-3 py-1.5 rounded bg-rose-950/80 hover:bg-rose-900 text-rose-300 border border-rose-800 text-xs font-mono transition-colors"
              >
                <X className="w-3.5 h-3.5" />
                <span>Reject</span>
              </button>
            </>
          )}
        </div>

        <div className="flex items-center space-x-2">
          {onFindSimilar && (
            <button
              type="button"
              onClick={() => onFindSimilar(entity.entity_id)}
              className="flex items-center space-x-1 px-2.5 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-mono transition-colors"
            >
              <Compass className="w-3.5 h-3.5 text-cyan-400" />
              <span className="hidden sm:inline">Similar Sites</span>
            </button>
          )}

          <a
            href={`/api/v1/export/${entity.entity_id}`}
            target="_blank"
            className="flex items-center space-x-1 px-2.5 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-mono transition-colors"
          >
            <Download className="w-3.5 h-3.5 text-slate-300" />
            <span>Export</span>
          </a>
        </div>
      </div>
    </div>
  );
};

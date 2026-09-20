'use client';

import React, { useState } from 'react';
import type { SearchResult } from '@/lib/types';
import { useHealth, useTimeline, useVerdict } from '@/lib/hooks';
import { api } from '@/lib/api';
import { BeforeAfterSwipe } from './BeforeAfterSwipe';
import { TrajectoryChart } from './TrajectoryChart';
import { EvidenceChecklist } from './EvidenceChecklist';
import { ProvenanceBlock } from './ProvenanceBlock';
import { Check, X, Download, Compass, CheckCircle2, AlertTriangle } from 'lucide-react';

/**
 * Rewired against real endpoints via lib/hooks.ts instead of raw `fetch`.
 *
 * Fixes made here, each tied to a real bug found in the previous version:
 *   - timeline fetch had no AbortController, so switching entities quickly
 *     could let a stale response overwrite the newer selection
 *   - the verdict POST never checked `res.ok`, so a 404 still flipped the UI
 *     to "Verdict logged (Hashed to Ledger)"
 *   - `entry_hash`/`log_id` from the verdict response were fetched and
 *     discarded (`const data = await res.json()` then never read) -- now
 *     passed to ProvenanceBlock, which previously showed the same hardcoded
 *     hash for every entity because nothing real was ever supplied
 *   - before/after dates were the literals "2024-07-11" / "2025-06-14"
 *     regardless of which entity was open -- now the entity's own dates
 *   - EvidenceChecklist now receives the real `gates` array and `confidence`
 */

interface EvidencePanelProps {
  entity: SearchResult | null;
  onClose: () => void;
  onFindSimilar?: (entityId: string) => void;
}

export const EvidencePanel: React.FC<EvidencePanelProps> = ({ entity, onClose, onFindSimilar }) => {
  const [analyst] = useState('analyst_01'); // no auth system yet; kept as one place to change
  const [lastVerdict, setLastVerdict] = useState<{ verdict: string; entryHash: string } | null>(null);

  const timeline = useTimeline(entity?.entity_id ?? null);
  const health = useHealth();
  const verdictMutation = useVerdict(entity?.entity_id ?? '');

  if (!entity) return null;

  const handleVerdict = (verdict: 'confirm' | 'reject') => {
    verdictMutation.mutate(
      { verdict, analyst, note: `Analyst decision: ${verdict.toUpperCase()}` },
      {
        onSuccess: (data) => {
          setLastVerdict({ verdict, entryHash: data.entry_hash });
        },
        // onError deliberately does nothing beyond leaving lastVerdict unset --
        // the mutation's own isError/error state below renders the failure,
        // instead of the previous silent console.error-and-move-on.
      }
    );
  };

  const beforeIso = entity.first_seen_ci?.[0] ?? entity.first_seen;
  const afterIso = entity.first_seen_ci?.[1] ?? entity.first_seen;

  return (
    <div className="fixed inset-y-0 right-0 w-full sm:w-[580px] lg:w-[680px] bg-command-bg border-l border-command-cardBorder shadow-2xl z-50 flex flex-col overflow-hidden animate-in slide-in-from-right duration-200">
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
            {entity.evidence.explanation || 'No explanation was generated for this candidate.'}
          </p>
          {entity.evidence.explanation_degraded && (
            <p className="text-[10px] text-amber-400 mt-0.5 font-mono">
              ⚠ template summary ({entity.evidence.explanation_provider || 'no VLM provider reachable'})
            </p>
          )}
        </div>

        <button
          type="button"
          onClick={onClose}
          className="w-7 h-7 rounded-full bg-slate-800 hover:bg-slate-700 text-slate-300 flex items-center justify-center transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <BeforeAfterSwipe
          beforeUrl={api.staticUrl(entity.imagery.before)}
          afterUrl={api.staticUrl(entity.imagery.after)}
          sarUrl={entity.imagery.sar ? api.staticUrl(entity.imagery.sar) : undefined}
          beforeDate={beforeIso}
          afterDate={afterIso}
        />

        {timeline.isLoading ? (
          <div className="h-44 bg-command-card border border-command-cardBorder rounded-lg flex items-center justify-center text-xs font-mono text-slate-500">
            <span className="inline-block w-4 h-4 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin mr-2" />
            Loading embedding trajectory...
          </div>
        ) : timeline.isError ? (
          <div className="h-24 bg-command-card border border-red-900/40 rounded-lg flex items-center justify-center text-xs font-mono text-red-400 gap-2">
            <AlertTriangle className="w-4 h-4" />
            Could not load trajectory: {timeline.error.message}
          </div>
        ) : (
          <TrajectoryChart
            trajectory={timeline.data?.trajectory ?? []}
            breakDate={entity.first_seen}
            breakDateCi={entity.first_seen_ci}
            ciWidthDays={entity.ci_width_days}
          />
        )}

        <EvidenceChecklist gates={entity.evidence.gates} confidence={entity.confidence} />

        <ProvenanceBlock
          sourceScenes={entity.provenance.source_scenes}
          sensors={entity.provenance.sensors}
          processingChain={entity.provenance.processing_chain}
          manifestHash={entity.provenance.model_manifest_hash}
          entryHash={lastVerdict?.entryHash}
          chainValid={health.data?.audit_ledger.chain_valid}
        />
      </div>

      <div className="p-3.5 border-t border-command-cardBorder bg-command-sidebar flex items-center justify-between gap-2">
        <div className="flex items-center space-x-2">
          {lastVerdict ? (
            <div className="flex items-center space-x-1.5 px-3 py-1.5 rounded bg-emerald-950 border border-emerald-800 text-emerald-400 text-xs font-mono">
              <CheckCircle2 className="w-4 h-4" />
              <span>Verdict: {lastVerdict.verdict.toUpperCase()} (Hashed to Ledger)</span>
            </div>
          ) : verdictMutation.isError ? (
            <div className="flex flex-col gap-1">
              <div className="flex items-center space-x-1.5 px-3 py-1.5 rounded bg-red-950 border border-red-800 text-red-400 text-xs font-mono">
                <AlertTriangle className="w-4 h-4" />
                <span>Failed: {verdictMutation.error.message}</span>
              </div>
              <button
                type="button"
                onClick={() => handleVerdict('confirm')}
                className="text-[10px] text-slate-400 underline hover:text-slate-200 text-left"
              >
                Retry
              </button>
            </div>
          ) : (
            <>
              <button
                type="button"
                onClick={() => handleVerdict('confirm')}
                disabled={verdictMutation.isPending}
                className="flex items-center space-x-1.5 px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-slate-950 text-xs font-mono font-bold transition-colors shadow disabled:opacity-50"
              >
                <Check className="w-3.5 h-3.5 text-slate-950" />
                <span>Confirm</span>
              </button>

              <button
                type="button"
                onClick={() => handleVerdict('reject')}
                disabled={verdictMutation.isPending}
                className="flex items-center space-x-1.5 px-3 py-1.5 rounded bg-rose-950/80 hover:bg-rose-900 text-rose-300 border border-rose-800 text-xs font-mono transition-colors disabled:opacity-50"
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
            href={api.exportUrl(entity.entity_id)}
            target="_blank"
            rel="noreferrer"
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

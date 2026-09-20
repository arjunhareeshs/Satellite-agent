'use client';

/**
 * PRD section 8.5's image-to-image search had no frontend at all: the "Find
 * similar sites" button on EvidencePanel was declared with an optional
 * `onFindSimilar` prop that `page.tsx` never actually passed, so the button
 * never rendered and `POST /search/similar` was unreachable from the UI.
 *
 * This is a lightweight results panel, not a full entity re-hydration --
 * `/search/similar` returns `{entity_id, visual_score, raw_cosine, payload}`
 * for each match, which is enough to rank and locate a result without a
 * second round-trip per match.
 */

import React from 'react';
import { X, Compass, Loader2 } from 'lucide-react';
import type { SimilarSitesResponse } from '@/lib/types';

interface SimilarSitesProps {
  isOpen: boolean;
  isLoading: boolean;
  data: SimilarSitesResponse | null;
  error: string | null;
  onClose: () => void;
  /** Selects the match if it happens to be in the current result set already. */
  onLocate: (entityId: string) => void;
}

export const SimilarSites: React.FC<SimilarSitesProps> = ({
  isOpen,
  isLoading,
  data,
  error,
  onClose,
  onLocate,
}) => {
  if (!isOpen) return null;

  const matches = data?.similar_entities ?? [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 backdrop-blur-sm animate-in zoom-in-95 duration-150">
      <div className="w-full max-w-md bg-command-card border border-command-cardBorder rounded-lg shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between p-3 border-b border-slate-800">
          <span className="flex items-center gap-1.5 text-xs font-mono font-bold uppercase tracking-wider text-slate-200">
            <Compass className="w-3.5 h-3.5 text-cyan-400" />
            Similar Sites {data?.query_entity_id ? `— ${data.query_entity_id}` : ''}
          </span>
          <button
            onClick={onClose}
            className="w-6 h-6 rounded-full bg-slate-800 hover:bg-slate-700 text-slate-300 flex items-center justify-center"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>

        <div className="max-h-96 overflow-y-auto p-3 space-y-1.5">
          {isLoading && (
            <div className="flex items-center justify-center gap-2 text-slate-400 text-xs font-mono py-6">
              <Loader2 className="w-4 h-4 animate-spin" />
              Searching the visual index...
            </div>
          )}

          {error && (
            <div className="text-xs font-mono text-red-400 bg-red-950/30 border border-red-900/40 rounded p-2">
              {error}
            </div>
          )}

          {!isLoading && !error && matches.length === 0 && (
            <div className="text-xs font-mono text-slate-500 text-center py-6">
              No visually similar entities found in the index.
            </div>
          )}

          {matches.map((m) => (
            <button
              key={m.entity_id}
              onClick={() => onLocate(m.entity_id)}
              className="w-full flex items-center justify-between px-2.5 py-1.5 rounded bg-slate-900/60 border border-slate-800 hover:border-cyan-700 text-left text-xs font-mono transition-colors"
            >
              <span className="text-slate-200">{m.entity_id}</span>
              <span className="text-cyan-400">
                {Math.round((m.visual_score ?? m.raw_cosine ?? 0) * 100)}%
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};

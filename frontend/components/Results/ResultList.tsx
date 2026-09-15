'use client';

import React from 'react';
import { ResultCard, SearchResultItem } from './ResultCard';
import { ListFilter, AlertCircle } from 'lucide-react';

interface ResultListProps {
  results: SearchResultItem[];
  selectedId?: string;
  onSelect: (result: SearchResultItem) => void;
  latencyMs?: number;
}

export const ResultList: React.FC<ResultListProps> = ({
  results,
  selectedId,
  onSelect,
  latencyMs
}) => {
  return (
    <div className="flex flex-col flex-1 min-h-0 bg-command-sidebar border border-command-cardBorder rounded-lg p-3">
      <div className="flex items-center justify-between pb-2 border-b border-slate-800 mb-2.5">
        <div className="flex items-center space-x-2">
          <ListFilter className="w-3.5 h-3.5 text-cyan-400" />
          <span className="text-xs font-mono font-bold uppercase tracking-wider text-slate-200">
            Ranked Review Queue ({results.length})
          </span>
        </div>
        {latencyMs !== undefined && (
          <span className="text-[10px] font-mono text-slate-400 bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800">
            {latencyMs} ms
          </span>
        )}
      </div>

      {results.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-center p-6 text-slate-500">
          <AlertCircle className="w-8 h-8 text-slate-600 mb-2" />
          <p className="text-xs font-mono">No entities retrieved</p>
          <p className="text-[11px] text-slate-600 mt-1">
            Execute a query or plan to populate the intelligence queue.
          </p>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto space-y-2 pr-1">
          {results.map((r) => (
            <ResultCard
              key={r.entity_id}
              result={r}
              isSelected={r.entity_id === selectedId}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
};

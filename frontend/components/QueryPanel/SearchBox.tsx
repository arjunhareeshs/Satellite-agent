'use client';

import React, { useState } from 'react';
import { Search, Sparkles, Terminal, ChevronRight } from 'lucide-react';

interface SearchBoxProps {
  onSearch: (query: string) => void;
  isLoading?: boolean;
}

const PRESET_QUERIES = [
  "Find new structures within 500 m of the river between 2024 and 2025",
  "Locate new road developments near the Yamuna river",
  "Identify commercial buildings built in late 2024"
];

export const SearchBox: React.FC<SearchBoxProps> = ({ onSearch, isLoading }) => {
  const [query, setQuery] = useState(PRESET_QUERIES[0]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) {
      onSearch(query.trim());
    }
  };

  return (
    <div className="bg-command-card border border-command-cardBorder rounded-lg p-3.5 shadow-sm">
      <div className="flex items-center justify-between mb-2">
        <label className="text-[11px] font-mono uppercase tracking-wider text-slate-400 flex items-center space-x-1.5">
          <Terminal className="w-3.5 h-3.5 text-cyan-400" />
          <span>Ask TRINETRA (Natural Language)</span>
        </label>
        <span className="text-[10px] font-mono text-cyan-400/80 bg-cyan-950/60 px-1.5 py-0.5 rounded border border-cyan-900/40">
          NL → DSL Compiler
        </span>
      </div>

      <form onSubmit={handleSubmit} className="space-y-2.5">
        <div className="relative">
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            rows={2}
            className="w-full bg-slate-950/80 border border-slate-800 rounded px-3 py-2 text-xs font-sans text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500/60 focus:ring-1 focus:ring-cyan-500/30 resize-none"
            placeholder="e.g. Find new buildings within 500 m of water appearing between 2024 and 2025..."
          />
        </div>

        <div className="flex items-center justify-between">
          <button
            type="submit"
            disabled={isLoading}
            className="w-full flex items-center justify-center space-x-2 px-3.5 py-2 rounded bg-cyan-600 hover:bg-cyan-500 text-slate-950 font-semibold text-xs transition-colors shadow disabled:opacity-50"
          >
            {isLoading ? (
              <>
                <span className="inline-block w-3.5 h-3.5 border-2 border-slate-950 border-t-transparent rounded-full animate-spin" />
                <span>Compiling & Executing...</span>
              </>
            ) : (
              <>
                <Search className="w-3.5 h-3.5 text-slate-950" />
                <span>Search Intelligence Archive</span>
              </>
            )}
          </button>
        </div>
      </form>

      {/* Preset demo triggers */}
      <div className="mt-3 pt-2.5 border-t border-slate-800/80">
        <span className="text-[10px] uppercase font-mono text-slate-400 tracking-wider block mb-1.5">
          Demo Scenarios:
        </span>
        <div className="space-y-1">
          {PRESET_QUERIES.map((preset, idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => {
                setQuery(preset);
                onSearch(preset);
              }}
              className="w-full text-left text-[11px] font-sans text-slate-300 hover:text-cyan-300 px-2 py-1 rounded hover:bg-slate-800/50 flex items-center justify-between group transition-colors"
            >
              <span className="truncate">{preset}</span>
              <ChevronRight className="w-3 h-3 text-slate-600 group-hover:text-cyan-400 flex-shrink-0 ml-1" />
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};

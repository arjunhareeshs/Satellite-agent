'use client';

import React from 'react';
import { Shield, Radio, Database, Cpu, Download, RefreshCw, Layers } from 'lucide-react';

interface HeaderProps {
  onSeedReset?: () => void;
  onOpenCoChange?: () => void;
  entityCount?: number;
}

export const Header: React.FC<HeaderProps> = ({ onSeedReset, onOpenCoChange, entityCount = 4 }) => {
  return (
    <header className="h-14 border-b border-command-cardBorder bg-command-sidebar px-4 flex items-center justify-between select-none">
      {/* Brand & Emblem */}
      <div className="flex items-center space-x-3">
        <div className="w-8 h-8 rounded bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400">
          <Shield className="w-5 h-5" />
        </div>
        <div>
          <div className="flex items-center space-x-2">
            <span className="font-mono font-bold tracking-wider text-base text-slate-100">TRINETRA</span>
            <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-cyan-950 text-cyan-400 border border-cyan-800/60 font-semibold">
              v1.0 Sovereign
            </span>
          </div>
          <p className="text-[11px] text-slate-400 font-sans tracking-tight">
            Semantic Retrieval & Multi-Temporal Change Analysis
          </p>
        </div>
      </div>

      {/* AOI & Temporal Context */}
      <div className="hidden md:flex items-center space-x-6 text-xs font-mono">
        <div className="flex items-center space-x-2 text-slate-300">
          <span className="text-slate-500 uppercase tracking-wider text-[10px]">AOI:</span>
          <span className="text-cyan-300 font-medium">Delhi-NCR / Yamuna</span>
        </div>
        <div className="h-3 w-px bg-slate-800" />
        <div className="flex items-center space-x-2 text-slate-300">
          <span className="text-slate-500 uppercase tracking-wider text-[10px]">Window:</span>
          <span className="text-slate-200">2024-01 → 2025-12</span>
        </div>
        <div className="h-3 w-px bg-slate-800" />
        <div className="flex items-center space-x-2">
          <span className="inline-block w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-emerald-400 uppercase text-[11px] font-semibold tracking-wide">
            Air-Gapped Secure
          </span>
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center space-x-2">
        <button
          onClick={onOpenCoChange}
          className="flex items-center space-x-1.5 px-2.5 py-1.5 rounded bg-slate-800/80 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-mono transition-colors"
          title="Open Regional Co-Change Graph"
        >
          <Layers className="w-3.5 h-3.5 text-cyan-400" />
          <span className="hidden sm:inline">Co-Change</span>
        </button>

        <a
          href="/api/v1/export/full_archive"
          target="_blank"
          className="flex items-center space-x-1.5 px-2.5 py-1.5 rounded bg-slate-800/80 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-mono transition-colors"
        >
          <Download className="w-3.5 h-3.5 text-slate-300" />
          <span className="hidden sm:inline">GeoJSON</span>
        </a>
      </div>
    </header>
  );
};

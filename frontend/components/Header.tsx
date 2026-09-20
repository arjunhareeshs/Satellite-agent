'use client';

import React from 'react';
import { Shield, Download, Layers, WifiOff, AlertTriangle } from 'lucide-react';
import { useHealth, useStats } from '@/lib/hooks';
import { api } from '@/lib/api';

/**
 * Previously: AOI name, date window and the "Air-Gapped Secure" indicator
 * were all hardcoded literals, and the dot was permanently green regardless
 * of whether the backend was reachable -- `/api/v1/health` was never called
 * from here. `entityCount` defaulted to a literal `4` matching the seed
 * fixture's four hand-authored entities. `onSeedReset` was declared as a prop
 * and never wired to anything (dead prop, removed).
 */

interface HeaderProps {
  onOpenCoChange?: () => void;
  entityCount?: number;
}

export const Header: React.FC<HeaderProps> = ({ onOpenCoChange, entityCount = 0 }) => {
  const stats = useStats();
  const health = useHealth();

  const isReachable = !health.isError;
  const offlineCompliant = health.data?.offline_compliant;

  return (
    <header className="h-14 border-b border-command-cardBorder bg-command-sidebar px-4 flex items-center justify-between select-none">
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

      <div className="hidden md:flex items-center space-x-6 text-xs font-mono">
        <div className="flex items-center space-x-2 text-slate-300">
          <span className="text-slate-500 uppercase tracking-wider text-[10px]">AOI:</span>
          <span className="text-cyan-300 font-medium">
            {stats.data?.aoi_name ?? (stats.isLoading ? '…' : 'unknown')}
          </span>
        </div>
        <div className="h-3 w-px bg-slate-800" />
        <div className="flex items-center space-x-2 text-slate-300">
          <span className="text-slate-500 uppercase tracking-wider text-[10px]">Window:</span>
          <span className="text-slate-200">
            {stats.data?.date_range
              ? `${stats.data.date_range.start.slice(0, 7)} → ${stats.data.date_range.end.slice(0, 7)}`
              : stats.isLoading ? '…' : 'unknown'}
          </span>
        </div>
        <div className="h-3 w-px bg-slate-800" />
        <div className="flex items-center space-x-2">
          {isReachable ? (
            <>
              <span
                className={`inline-block w-2 h-2 rounded-full animate-pulse ${
                  offlineCompliant ? 'bg-emerald-400' : 'bg-amber-400'
                }`}
              />
              <span
                className={`uppercase text-[11px] font-semibold tracking-wide ${
                  offlineCompliant ? 'text-emerald-400' : 'text-amber-400'
                }`}
                title={
                  offlineCompliant
                    ? 'Model manifest verified and no network-dependent provider active'
                    : health.data
                      ? `Not offline-compliant: ${health.data.model_manifest.message}, VLM=${health.data.vlm_provider.active}`
                      : undefined
                }
              >
                {offlineCompliant ? 'Air-Gapped Secure' : 'Not Offline-Compliant'}
              </span>
            </>
          ) : (
            <>
              <WifiOff className="w-3.5 h-3.5 text-red-400" />
              <span className="uppercase text-[11px] font-semibold tracking-wide text-red-400">
                Backend Unreachable
              </span>
            </>
          )}
        </div>
        {stats.data && stats.data.total_entities === 0 ? (
          <div className="flex items-center space-x-1.5 text-amber-400" title="No entities indexed yet">
            <AlertTriangle className="w-3.5 h-3.5" />
            <span className="text-[11px]">Archive empty</span>
          </div>
        ) : (
          <div className="flex items-center space-x-2 text-slate-300">
            <span className="text-slate-500 uppercase tracking-wider text-[10px]">Results:</span>
            <span className="text-slate-200">{entityCount}</span>
          </div>
        )}
      </div>

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
          href={api.exportUrl('full_archive')}
          target="_blank"
          rel="noreferrer"
          className="flex items-center space-x-1.5 px-2.5 py-1.5 rounded bg-slate-800/80 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-mono transition-colors"
        >
          <Download className="w-3.5 h-3.5 text-slate-300" />
          <span className="hidden sm:inline">GeoJSON</span>
        </a>
      </div>
    </header>
  );
};

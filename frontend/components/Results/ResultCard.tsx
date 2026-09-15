'use client';

import React from 'react';
import { Eye, Radio, CheckCircle2, Waves, Calendar } from 'lucide-react';

export interface SearchResultItem {
  rank: number;
  entity_id: string;
  entity_type: string;
  location: { lat: number; lon: number };
  area_m2: number;
  change_type: string;
  first_seen: string;
  first_seen_ci: string[];
  ci_width_days: number;
  confidence: number;
  scores: {
    semantic: number;
    visual: number;
    temporal: number;
    spatial: number;
    sensor: number;
    final: number;
  };
  evidence: {
    optical: boolean;
    sar: boolean;
    temporal_persistence: boolean;
    observations_after_break: number;
    optical_z: number;
    sar_z: number;
    registration_residual_px: number;
    cloud_free_pct: number;
    explanation: string;
  };
  relations: {
    river_distance_m?: number;
    road_distance_m?: number;
  };
  imagery: {
    before: string;
    after: string;
    sar?: string;
  };
  provenance: {
    source_scenes: string[];
    sensors: string[];
    processing_chain: string[];
    model_manifest_hash: string;
  };
}

interface ResultCardProps {
  result: SearchResultItem;
  isSelected?: boolean;
  onSelect: (result: SearchResultItem) => void;
}

export const ResultCard: React.FC<ResultCardProps> = ({ result, isSelected, onSelect }) => {
  const confPct = Math.round(result.confidence * 100);

  return (
    <div
      onClick={() => onSelect(result)}
      className={`p-3 rounded-lg border transition-all cursor-pointer select-none ${
        isSelected
          ? 'bg-cyan-950/40 border-cyan-500 shadow-md shadow-cyan-950/20'
          : 'bg-command-card border-command-cardBorder hover:border-slate-700 hover:bg-slate-900/50'
      }`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <span className="font-mono text-xs font-bold text-slate-400 bg-slate-800 px-1.5 py-0.5 rounded">
            #{result.rank}
          </span>
          <span className="font-mono font-bold text-xs text-slate-100">{result.entity_id}</span>
          <span className="text-[10px] uppercase font-mono px-1.5 py-0.2 rounded bg-slate-800/80 text-cyan-300 border border-slate-700">
            {result.change_type}
          </span>
        </div>

        {/* Dual-Witness Chips */}
        <div className="flex items-center space-x-1.5 text-[10px] font-mono">
          <span className="flex items-center text-emerald-400 bg-emerald-950/60 px-1.5 py-0.5 rounded border border-emerald-900/40">
            ✓opt
          </span>
          {result.evidence.sar ? (
            <span className="flex items-center text-cyan-400 bg-cyan-950/60 px-1.5 py-0.5 rounded border border-cyan-900/40 font-semibold">
              ✓sar
            </span>
          ) : (
            <span className="text-slate-500 bg-slate-900 px-1 py-0.5 rounded">
              sar-
            </span>
          )}
          <span className="font-bold text-xs text-emerald-400 ml-1">
            {confPct}%
          </span>
        </div>
      </div>

      {/* Attributes & Relations */}
      <div className="mt-2 text-[11px] text-slate-400 grid grid-cols-2 gap-1.5 font-sans">
        <div className="flex items-center space-x-1 text-slate-300">
          <Calendar className="w-3 h-3 text-slate-500" />
          <span>
            {result.first_seen_ci[0]?.slice(0, 7)} → {result.first_seen_ci[1]?.slice(0, 7)}
          </span>
        </div>

        {result.relations.river_distance_m !== undefined && (
          <div className="flex items-center space-x-1 text-slate-300">
            <Waves className="w-3 h-3 text-cyan-500/80" />
            <span>{Math.round(result.relations.river_distance_m)} m from river</span>
          </div>
        )}
      </div>

      {/* Footer / Inspect Button */}
      <div className="mt-2 pt-2 border-t border-slate-800/60 flex items-center justify-between">
        <span className="text-[10px] font-mono text-slate-500">
          Area: {Math.round(result.area_m2)} m²
        </span>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onSelect(result);
          }}
          className="flex items-center space-x-1 text-[11px] font-mono text-cyan-400 hover:text-cyan-300 group"
        >
          <Eye className="w-3 h-3" />
          <span>Inspect Evidence</span>
        </button>
      </div>
    </div>
  );
};

'use client';

import React, { useState, useEffect } from 'react';
import { Sliders, Play } from 'lucide-react';
import type { QueryPlan } from '@/lib/types';

/**
 * Re-exported from lib/types.ts, not redefined here.
 *
 * The hand-written version previously in this file omitted `aoi` and
 * `sensors` entirely. Object spreads (`{ ...plan, ... }`) throughout this
 * component meant those fields usually survived at runtime regardless, but
 * `handleExecutePlan` in app/page.tsx did NOT spread the prior plan when
 * building the request -- it really did drop them on re-execute. Fixed there;
 * fixed here by making the type honest so it can't happen again.
 */
export type QueryPlanDSL = QueryPlan;

interface PlanEditorProps {
  initialPlan: QueryPlanDSL | null;
  onExecutePlan: (plan: QueryPlanDSL) => void;
  isLoading?: boolean;
}

export const PlanEditor: React.FC<PlanEditorProps> = ({ initialPlan, onExecutePlan, isLoading }) => {
  const [isExpanded, setIsExpanded] = useState(true);
  const [plan, setPlan] = useState<QueryPlanDSL | null>(initialPlan);

  useEffect(() => {
    if (initialPlan) {
      setPlan(initialPlan);
    }
  }, [initialPlan]);

  if (!plan) {
    return null;
  }

  const handleExecute = () => {
    onExecutePlan(plan);
  };

  return (
    <div className="bg-command-card border border-command-cardBorder rounded-lg p-3 shadow-sm">
      <div className="flex items-center justify-between pb-2 border-b border-slate-800">
        <div className="flex items-center space-x-2">
          <Sliders className="w-3.5 h-3.5 text-cyan-400" />
          <span className="text-[11px] font-mono uppercase tracking-wider text-slate-200 font-semibold">
            Query Plan (Transparency Form)
          </span>
        </div>
        <button
          type="button"
          onClick={() => setIsExpanded(!isExpanded)}
          className="text-[10px] font-mono text-cyan-400 hover:text-cyan-300 transition-colors"
        >
          {isExpanded ? 'Minimize ▴' : 'Expand ▾'}
        </button>
      </div>

      {isExpanded && (
        <div className="mt-2.5 space-y-2.5 text-xs font-mono">
          {/* Target Entity Type */}
          <div className="grid grid-cols-3 gap-2 items-center">
            <span className="text-slate-400 text-[11px]">Target Entity:</span>
            <select
              value={plan.target.entity_type}
              onChange={(e) => setPlan({
                ...plan,
                target: { ...plan.target, entity_type: e.target.value }
              })}
              className="col-span-2 bg-slate-950 border border-slate-800 rounded px-2 py-1 text-slate-200 focus:outline-none focus:border-cyan-500"
            >
              <option value="building">Building / Structure</option>
              <option value="road">Road / Paved Surface</option>
              <option value="water">Water Body / River</option>
              <option value="vegetation">Vegetation / Crop</option>
              <option value="vehicle_cluster">Vehicle Cluster</option>
            </select>
          </div>

          {/* Spatial Relation */}
          <div className="grid grid-cols-3 gap-2 items-center">
            <span className="text-slate-400 text-[11px]">Spatial Join:</span>
            <div className="col-span-2 flex space-x-1.5">
              <select
                value={plan.spatial[0]?.relation || 'near_water'}
                onChange={(e) => {
                  // Preserve every other field on the existing predicate --
                  // in particular target_layer, which a from-scratch object
                  // literal here previously dropped on every edit, silently
                  // reverting an analyst's explicit "ref_water" / "ref_roads"
                  // choice back to the relation's default layer.
                  const newSpatial = [...plan.spatial];
                  const current = newSpatial[0] ?? { relation: 'near_water', distance_m: 500 };
                  newSpatial[0] = { ...current, relation: e.target.value };
                  setPlan({ ...plan, spatial: newSpatial });
                }}
                className="w-1/2 bg-slate-950 border border-slate-800 rounded px-2 py-1 text-slate-200 focus:outline-none focus:border-cyan-500"
              >
                <option value="near_water">Near Water</option>
                <option value="near_road">Near Road</option>
                <option value="within_aoi">Within AOI</option>
              </select>

              <div className="w-1/2 flex items-center bg-slate-950 border border-slate-800 rounded px-2 py-1">
                <input
                  type="number"
                  value={plan.spatial[0]?.distance_m ?? 500}
                  onChange={(e) => {
                    const newSpatial = [...plan.spatial];
                    const current = newSpatial[0] ?? { relation: 'near_water', distance_m: 500 };
                    newSpatial[0] = { ...current, distance_m: Number(e.target.value) };
                    setPlan({ ...plan, spatial: newSpatial });
                  }}
                  className="w-full bg-transparent text-slate-200 focus:outline-none text-right pr-1"
                />
                <span className="text-slate-500 text-[10px]">m</span>
              </div>
            </div>
          </div>

          {/* Temporal Window */}
          {plan.temporal && (
            <div className="grid grid-cols-3 gap-2 items-center">
              <span className="text-slate-400 text-[11px]">Time Window:</span>
              <div className="col-span-2 flex space-x-1">
                <input
                  type="date"
                  value={plan.temporal.from}
                  onChange={(e) => setPlan({
                    ...plan,
                    temporal: { ...plan.temporal!, from: e.target.value }
                  })}
                  className="w-1/2 bg-slate-950 border border-slate-800 rounded px-1.5 py-1 text-slate-300 text-[11px] focus:outline-none focus:border-cyan-500"
                />
                <input
                  type="date"
                  value={plan.temporal.to}
                  onChange={(e) => setPlan({
                    ...plan,
                    temporal: { ...plan.temporal!, to: e.target.value }
                  })}
                  className="w-1/2 bg-slate-950 border border-slate-800 rounded px-1.5 py-1 text-slate-300 text-[11px] focus:outline-none focus:border-cyan-500"
                />
              </div>
            </div>
          )}

          {/* Change Type & Min Confidence */}
          {plan.change && (
            <div className="grid grid-cols-3 gap-2 items-center">
              <span className="text-slate-400 text-[11px]">Change Type:</span>
              <div className="col-span-2 flex items-center space-x-2">
                <select
                  value={plan.change.types[0] || 'construction'}
                  onChange={(e) => setPlan({
                    ...plan,
                    change: { ...plan.change!, types: [e.target.value] }
                  })}
                  className="w-3/5 bg-slate-950 border border-slate-800 rounded px-2 py-1 text-slate-200 focus:outline-none focus:border-cyan-500"
                >
                  <option value="construction">Construction</option>
                  <option value="clearance">Clearance</option>
                  <option value="road_development">Road Dev</option>
                  <option value="expansion">Expansion</option>
                </select>

                <div className="w-2/5 flex items-center justify-end space-x-1.5 bg-slate-950 border border-slate-800 rounded px-1.5 py-1">
                  <span className="text-[10px] text-slate-400">≥</span>
                  {/*
                    Previously display-only text -- the analyst could see the
                    threshold but never actually change ChangeConstraint's
                    min_confidence from the UI. A real range input now writes
                    it back into the plan like every other field here does.
                  */}
                  <input
                    type="range"
                    min={0}
                    max={100}
                    step={5}
                    value={Math.round((plan.change.min_confidence ?? 0.6) * 100)}
                    onChange={(e) => setPlan({
                      ...plan,
                      change: { ...plan.change!, min_confidence: Number(e.target.value) / 100 }
                    })}
                    className="w-14 accent-cyan-500"
                  />
                  <span className="text-cyan-400 font-bold w-9 text-right">
                    {Math.round((plan.change.min_confidence ?? 0.6) * 100)}%
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Execute plan button */}
          <div className="pt-2 border-t border-slate-800 flex items-center justify-between">
            <span className="text-[10px] text-slate-400 italic">
              Editable DSL guarantees transparency & eliminates LLM hallucination
            </span>
            <button
              type="button"
              onClick={handleExecute}
              disabled={isLoading}
              className="flex items-center space-x-1 px-3 py-1 rounded bg-slate-800 hover:bg-cyan-600 hover:text-slate-950 text-cyan-400 text-xs font-mono font-medium border border-cyan-800/60 transition-colors shadow-sm disabled:opacity-50"
            >
              <Play className="w-3 h-3" />
              <span>Execute Plan</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

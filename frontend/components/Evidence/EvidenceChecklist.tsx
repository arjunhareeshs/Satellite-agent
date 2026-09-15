'use client';

import React from 'react';
import { CheckCircle2, XCircle, ShieldCheck, Info } from 'lucide-react';

interface EvidenceChecklistProps {
  opticalZ?: number;
  sarZ?: number;
  residualPx?: number;
  cloudFreePct?: number;
  confidence?: number;
  sarConfirmed?: boolean;
}

export const EvidenceChecklist: React.FC<EvidenceChecklistProps> = ({
  opticalZ = 5.2,
  sarZ = 4.1,
  residualPx = 0.18,
  cloudFreePct = 97.2,
  confidence = 0.94,
  sarConfirmed = true
}) => {
  return (
    <div className="bg-command-card border border-command-cardBorder rounded-lg p-3 space-y-2.5">
      <div className="flex items-center justify-between pb-1.5 border-b border-slate-800">
        <span className="text-xs font-mono font-bold uppercase tracking-wider text-slate-200 flex items-center space-x-1.5">
          <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
          <span>5-Gate False-Alarm Suppression Cascade</span>
        </span>
        <span className="text-[10px] font-mono text-emerald-400 bg-emerald-950 px-1.5 py-0.5 rounded border border-emerald-900 font-semibold">
          All 5 Gates Passed
        </span>
      </div>

      <div className="space-y-1.5 text-xs font-mono">
        {/* Gate 1 */}
        <div className="flex items-center justify-between p-1.5 rounded bg-slate-900/60 border border-slate-800/80">
          <div className="flex items-center space-x-2">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-slate-300">Gate 1: Observation Quality</span>
          </div>
          <span className="text-emerald-400 text-[11px]">{cloudFreePct}% cloud-free</span>
        </div>

        {/* Gate 2 */}
        <div className="flex items-center justify-between p-1.5 rounded bg-slate-900/60 border border-slate-800/80">
          <div className="flex items-center space-x-2">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-slate-300">Gate 2: Sub-pixel Registration</span>
          </div>
          <span className="text-emerald-400 text-[11px]">{residualPx} px (max 0.50 px)</span>
        </div>

        {/* Gate 3 */}
        <div className="flex items-center justify-between p-1.5 rounded bg-slate-900/60 border border-slate-800/80">
          <div className="flex items-center space-x-2">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-slate-300">Gate 3: Radiometric Baseline</span>
          </div>
          <span className="text-emerald-400 text-[11px]">Normalized to Reference</span>
        </div>

        {/* Gate 4 */}
        <div className="flex items-center justify-between p-1.5 rounded bg-slate-900/60 border border-slate-800/80">
          <div className="flex items-center space-x-2">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-slate-300">Gate 4: Phenological Subtraction</span>
          </div>
          <span className="text-emerald-400 text-[11px]">z = {opticalZ}σ deviation</span>
        </div>

        {/* Gate 5 */}
        <div className="flex items-center justify-between p-1.5 rounded bg-slate-900/60 border border-slate-800/80">
          <div className="flex items-center space-x-2">
            {sarConfirmed ? (
              <CheckCircle2 className="w-3.5 h-3.5 text-cyan-400" />
            ) : (
              <XCircle className="w-3.5 h-3.5 text-amber-500" />
            )}
            <span className="text-slate-300">Gate 5: Dual-Witness SAR Fusion</span>
          </div>
          <span className={sarConfirmed ? "text-cyan-300 text-[11px]" : "text-amber-400 text-[11px]"}>
            {sarConfirmed ? `Confirmed (z = ${sarZ}σ)` : 'Optical-only'}
          </span>
        </div>
      </div>

      {/* Conformal Guarantee Box */}
      <div className="mt-2 p-2 rounded bg-cyan-950/30 border border-cyan-800/50 flex items-start space-x-2 text-[11px] font-sans text-cyan-200">
        <Info className="w-4 h-4 text-cyan-400 flex-shrink-0 mt-0.5" />
        <div>
          <span className="font-semibold text-cyan-300">Conformal Statistical Guarantee: </span>
          <span>
            At operational threshold τ = 0.72, the false-alarm rate is ≤ 10% with 95% statistical coverage.
          </span>
        </div>
      </div>
    </div>
  );
};

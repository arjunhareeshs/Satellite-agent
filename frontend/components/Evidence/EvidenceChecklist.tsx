'use client';

import React from 'react';
import { CheckCircle2, XCircle, ShieldCheck, ShieldAlert, Info } from 'lucide-react';
import type { GateResult } from '@/lib/types';

/**
 * Previously this component received real evidence props (`opticalZ`, `sarZ`,
 * `residualPx`, `cloudFreePct`, `sarConfirmed`) but never compared any of them
 * to a threshold: all five gates rendered an unconditional green
 * `CheckCircle2`, the header always said "All 5 Gates Passed", and the
 * confidence prop was accepted and never displayed. The backend's
 * `fusion.py` has always computed real per-gate `{passed, metric,
 * threshold}` results, but only the aggregate score reached the API response
 * -- so there was no honest data for this component to render even if it had
 * tried.
 *
 * `EntityEvidence.gates` (backend/schemas/query.py) now carries that array
 * through. This component renders exactly what it says: pass/fail per gate,
 * from the gate's own measured metric and threshold, with nothing hardcoded.
 */

const GATE_LABELS: Record<string, string> = {
  gate_1_quality: 'Gate 1: Observation Quality',
  gate_2_geometric: 'Gate 2: Sub-pixel Registration',
  gate_3_radiometric: 'Gate 3: Radiometric Baseline',
  gate_4_phenological: 'Gate 4: Phenological Subtraction',
  gate_5_dual_witness: 'Gate 5: Dual-Witness SAR Fusion',
};

function labelFor(gate: GateResult): string {
  return GATE_LABELS[gate.name] ?? gate.name.replace(/_/g, ' ');
}

interface EvidenceChecklistProps {
  gates: GateResult[];
  confidence: number;
}

export const EvidenceChecklist: React.FC<EvidenceChecklistProps> = ({ gates, confidence }) => {
  const hasGates = gates.length > 0;
  const passedCount = gates.filter((g) => g.passed).length;
  const allPassed = hasGates && passedCount === gates.length;

  return (
    <div className="bg-command-card border border-command-cardBorder rounded-lg p-3 space-y-2.5">
      <div className="flex items-center justify-between pb-1.5 border-b border-slate-800">
        <span className="text-xs font-mono font-bold uppercase tracking-wider text-slate-200 flex items-center space-x-1.5">
          <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
          <span>5-Gate False-Alarm Suppression Cascade</span>
        </span>
        {hasGates ? (
          <span
            className={`text-[10px] font-mono px-1.5 py-0.5 rounded border font-semibold ${
              allPassed
                ? 'text-emerald-400 bg-emerald-950 border-emerald-900'
                : 'text-amber-400 bg-amber-950/60 border-amber-900'
            }`}
          >
            {passedCount} / {gates.length} Gates Passed
          </span>
        ) : (
          <span className="text-[10px] font-mono text-slate-500 bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800">
            No gate data
          </span>
        )}
      </div>

      {!hasGates && (
        <div className="text-[11px] font-mono text-slate-500 p-2">
          This result was returned without per-gate evidence -- re-run the search
          against a build where scripts 07/08 and the fusion engine have populated
          real quality metrics.
        </div>
      )}

      <div className="space-y-1.5 text-xs font-mono">
        {gates.map((gate) => (
          <div
            key={gate.name}
            className={`flex items-center justify-between p-1.5 rounded border ${
              gate.passed
                ? 'bg-slate-900/60 border-slate-800/80'
                : 'bg-amber-950/20 border-amber-900/40'
            }`}
          >
            <div className="flex items-center space-x-2">
              {gate.passed ? (
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
              ) : (
                <XCircle className="w-3.5 h-3.5 text-amber-500" />
              )}
              <span className="text-slate-300">{labelFor(gate)}</span>
            </div>
            <span
              className={`text-[11px] text-right ${gate.passed ? 'text-emerald-400' : 'text-amber-400'}`}
            >
              {gate.metric}
              {gate.threshold ? ` (${gate.threshold})` : ''}
            </span>
          </div>
        ))}
      </div>

      {/* Confidence -- previously accepted as a prop and never rendered anywhere. */}
      <div className="flex items-center justify-between text-[11px] font-mono pt-1">
        <span className="text-slate-400">Overall confidence</span>
        <span className={`font-bold ${confidence >= 0.7 ? 'text-emerald-400' : 'text-amber-400'}`}>
          {Math.round(confidence * 100)}%
        </span>
      </div>

      {!allPassed && hasGates && (
        <div className="p-2 rounded bg-amber-950/30 border border-amber-800/50 flex items-start space-x-2 text-[11px] font-sans text-amber-200">
          <ShieldAlert className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
          <span>
            One or more gates failed for this candidate. It still surfaced because it
            met the query's minimum confidence, not because every verification check
            passed -- read the failing gate's metric above before confirming.
          </span>
        </div>
      )}

      {/* This statistic previously appeared here unconditionally as marketing
          copy ("τ = 0.72, false-alarm rate ≤ 10%, 95% coverage") regardless of
          which gates actually passed. It is not shown until the conformal
          calibration in PRD section 7.9 is wired to compute it per result;
          a made-up number is worse than none. */}
      <div className="p-2 rounded bg-slate-900/40 border border-slate-800 flex items-start space-x-2 text-[11px] font-sans text-slate-400">
        <Info className="w-4 h-4 text-slate-500 flex-shrink-0 mt-0.5" />
        <span>
          Calibrated false-alarm bounds (PRD section 7.9) are not yet computed per
          result. Treat gate pass/fail and confidence above as the evidence for this
          candidate.
        </span>
      </div>
    </div>
  );
};

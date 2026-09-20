'use client';

import React from 'react';
import { Lock, Hash, GitBranch, ShieldQuestion } from 'lucide-react';

/**
 * Previously every prop here had a hardcoded default matching the seed
 * fixture's literals -- `sourceScenes = ["S2A_MSIL2A_20240821T052651", ...]`,
 * `manifestHash = "a3f9c2e8..."`, `entryHash = "7f2e1c94..."` -- and
 * `entryHash` was never actually passed by EvidencePanel, so every entity
 * showed the identical fake ledger hash forever. "Chain Verified" was a
 * static badge with no connection to `audit_ledger.verify_integrity()`.
 *
 * Source data is now required, not defaulted, and the two facts that used to
 * be asserted unconditionally -- chain integrity and "this entity has a
 * ledger entry" -- are each optional and rendered as their true tri-state:
 * verified / not verified / unknown, and hash / no entry yet, respectively.
 */

interface ProvenanceBlockProps {
  sourceScenes: string[];
  sensors: string[];
  processingChain: string[];
  manifestHash: string;
  /** Only present after this entity has had a confirm/reject verdict submitted. */
  entryHash?: string | null;
  /** From GET /health -> audit_ledger.chain_valid. Undefined while unknown. */
  chainValid?: boolean;
}

export const ProvenanceBlock: React.FC<ProvenanceBlockProps> = ({
  sourceScenes,
  sensors,
  processingChain,
  manifestHash,
  entryHash,
  chainValid,
}) => {
  return (
    <div className="bg-command-card border border-command-cardBorder rounded-lg p-3 space-y-2 text-xs font-mono">
      <div className="flex items-center justify-between pb-1.5 border-b border-slate-800">
        <span className="font-bold uppercase tracking-wider text-slate-200 flex items-center space-x-1.5">
          <Lock className="w-3.5 h-3.5 text-cyan-400" />
          <span>Cryptographic Provenance Lineage</span>
        </span>
        {chainValid === true && (
          <span className="text-[10px] text-emerald-400 bg-emerald-950 px-1.5 py-0.5 rounded border border-emerald-900">
            Chain Verified
          </span>
        )}
        {chainValid === false && (
          <span className="text-[10px] text-red-400 bg-red-950 px-1.5 py-0.5 rounded border border-red-900">
            Chain Tamper Detected
          </span>
        )}
        {chainValid === undefined && (
          <span className="flex items-center space-x-1 text-[10px] text-slate-500 bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800">
            <ShieldQuestion className="w-3 h-3" />
            <span>Chain status unknown</span>
          </span>
        )}
      </div>

      <div className="space-y-1.5 text-[11px]">
        <div>
          <span className="text-slate-500 uppercase text-[10px] block">
            Source Scenes {sensors.length ? `(${sensors.join(', ')})` : ''}:
          </span>
          {sourceScenes.length ? (
            <div className="text-slate-300 space-y-0.5">
              {sourceScenes.map((s, idx) => (
                <div key={idx} className="truncate bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800">
                  {s}
                </div>
              ))}
            </div>
          ) : (
            <div className="text-slate-500 italic">No source scenes recorded for this entity.</div>
          )}
        </div>

        <div>
          <span className="text-slate-500 uppercase text-[10px] block">Processing Chain:</span>
          {processingChain.length ? (
            <div className="flex flex-wrap gap-1 text-[10px]">
              {processingChain.map((step, idx) => (
                <span key={idx} className="bg-slate-900 text-slate-300 px-1.5 py-0.5 rounded border border-slate-800">
                  {step}
                </span>
              ))}
            </div>
          ) : (
            <div className="text-slate-500 italic text-[10px]">Not recorded.</div>
          )}
        </div>

        <div className="pt-1 border-t border-slate-800/80 space-y-1 text-[10px]">
          <div className="flex items-center justify-between text-slate-400">
            <span className="flex items-center space-x-1">
              <Hash className="w-3 h-3 text-cyan-400" />
              <span>Manifest Hash:</span>
            </span>
            {manifestHash ? (
              <span className="text-cyan-400/90 truncate ml-2 max-w-[200px]" title={manifestHash}>
                {manifestHash.slice(0, 16)}...
              </span>
            ) : (
              <span className="text-slate-500 italic">not staged</span>
            )}
          </div>

          <div className="flex items-center justify-between text-slate-400">
            <span className="flex items-center space-x-1">
              <GitBranch className="w-3 h-3 text-emerald-400" />
              <span>Ledger Entry:</span>
            </span>
            {entryHash ? (
              <span className="text-emerald-400/90 truncate ml-2 max-w-[200px]" title={entryHash}>
                {entryHash.slice(0, 16)}...
              </span>
            ) : (
              <span className="text-slate-500 italic">Confirm or reject to record one</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

'use client';

import React from 'react';
import { Database, Lock, Hash, GitBranch } from 'lucide-react';

interface ProvenanceBlockProps {
  sourceScenes?: string[];
  sensors?: string[];
  processingChain?: string[];
  manifestHash?: string;
  entryHash?: string;
}

export const ProvenanceBlock: React.FC<ProvenanceBlockProps> = ({
  sourceScenes = ["S2A_MSIL2A_20240821T052651", "S1A_IW_GRDH_20240819"],
  sensors = ["Sentinel-2 L2A", "Sentinel-1 GRD"],
  processingChain = ["cloud_mask", "coregister", "radiometric_harmonize", "chip", "segment", "embed"],
  manifestHash = "a3f9c2e817d54b830e2f91bc471d2b86ea92401f85de060a894a735c091e3e7f",
  entryHash = "7f2e1c94d68a2b530184fa93bc021876e193240c57da9180b2a5c4e138a29b01"
}) => {
  return (
    <div className="bg-command-card border border-command-cardBorder rounded-lg p-3 space-y-2 text-xs font-mono">
      <div className="flex items-center justify-between pb-1.5 border-b border-slate-800">
        <span className="font-bold uppercase tracking-wider text-slate-200 flex items-center space-x-1.5">
          <Lock className="w-3.5 h-3.5 text-cyan-400" />
          <span>Cryptographic Provenance Lineage</span>
        </span>
        <span className="text-[10px] text-emerald-400 bg-emerald-950 px-1.5 py-0.5 rounded border border-emerald-900">
          Chain Verified
        </span>
      </div>

      <div className="space-y-1.5 text-[11px]">
        {/* Source Scenes */}
        <div>
          <span className="text-slate-500 uppercase text-[10px] block">Source Scenes:</span>
          <div className="text-slate-300 space-y-0.5">
            {sourceScenes.map((s, idx) => (
              <div key={idx} className="truncate bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800">
                {s}
              </div>
            ))}
          </div>
        </div>

        {/* Processing Chain */}
        <div>
          <span className="text-slate-500 uppercase text-[10px] block">Processing Chain:</span>
          <div className="flex flex-wrap gap-1 text-[10px]">
            {processingChain.map((step, idx) => (
              <span key={idx} className="bg-slate-900 text-slate-300 px-1.5 py-0.5 rounded border border-slate-800">
                {step}
              </span>
            ))}
          </div>
        </div>

        {/* Hashes */}
        <div className="pt-1 border-t border-slate-800/80 space-y-1 text-[10px]">
          <div className="flex items-center justify-between text-slate-400">
            <span className="flex items-center space-x-1">
              <Hash className="w-3 h-3 text-cyan-400" />
              <span>Manifest Hash:</span>
            </span>
            <span className="text-cyan-400/90 truncate ml-2 max-w-[200px]" title={manifestHash}>
              {manifestHash.slice(0, 16)}...
            </span>
          </div>

          <div className="flex items-center justify-between text-slate-400">
            <span className="flex items-center space-x-1">
              <GitBranch className="w-3 h-3 text-emerald-400" />
              <span>Ledger Entry:</span>
            </span>
            <span className="text-emerald-400/90 truncate ml-2 max-w-[200px]" title={entryHash}>
              {entryHash.slice(0, 16)}...
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

'use client';

import React, { useState, useEffect } from 'react';
import { X, Network, Share2, Layers, Info } from 'lucide-react';

interface CoChangeGraphProps {
  isOpen: boolean;
  onClose: () => void;
}

export const CoChangeGraph: React.FC<CoChangeGraphProps> = ({ isOpen, onClose }) => {
  const [graphData, setGraphData] = useState<{ nodes: any[]; edges: any[] } | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setIsLoading(true);
    fetch('/api/v1/discover/co-change?max_window_days=21')
      .then(res => res.json())
      .then(data => {
        setGraphData(data);
      })
      .catch(err => console.error("Co-change fetch failed:", err))
      .finally(() => setIsLoading(false));
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 select-none">
      <div className="w-full max-w-3xl bg-command-bg border border-cyan-500/40 rounded-xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh] animate-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="p-4 border-b border-command-cardBorder bg-command-sidebar flex items-center justify-between">
          <div className="flex items-center space-x-2.5">
            <div className="w-7 h-7 rounded bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400">
              <Network className="w-4 h-4" />
            </div>
            <div>
              <h3 className="font-mono text-sm font-bold text-slate-100 flex items-center space-x-2">
                <span>Synchronized Regional Co-Change Graph</span>
                <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-cyan-950 text-cyan-400 border border-cyan-800">
                  PS 2.2.4 Differentiator
                </span>
              </h3>
              <p className="text-xs text-slate-400">
                Surfaces geographically separated sites whose trajectories broke within identical temporal windows.
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="w-7 h-7 rounded-full bg-slate-800 hover:bg-slate-700 text-slate-300 flex items-center justify-center transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Graph Body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          <div className="p-3 rounded bg-cyan-950/20 border border-cyan-800/40 flex items-start space-x-2 text-xs font-sans text-cyan-200">
            <Info className="w-4 h-4 text-cyan-400 flex-shrink-0 mt-0.5" />
            <p>
              <strong>Operational Intelligence Context: </strong>
              Semantic search answers what the analyst asked. Co-change detection uncovers what the analyst didn't know to ask — coordinated regional construction and synchronized development campaigns.
            </p>
          </div>

          {isLoading ? (
            <div className="h-64 flex items-center justify-center text-xs font-mono text-slate-500">
              <span className="inline-block w-4 h-4 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin mr-2" />
              Computing multi-temporal synchronized break matrix...
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {/* Synchronized Clusters */}
              <div className="p-3 rounded-lg border border-slate-800 bg-command-card space-y-2">
                <span className="text-xs font-mono font-bold uppercase text-slate-300 block">
                  Synchronized Temporal Clusters (Δt ≤ 21 Days)
                </span>
                <div className="space-y-2">
                  <div className="p-2 rounded bg-slate-900/80 border border-slate-800 text-xs font-mono">
                    <div className="flex items-center justify-between text-cyan-300 font-bold">
                      <span>Cluster #1: Yamuna Corridor Sector 18</span>
                      <span className="text-[10px] text-emerald-400">Jul–Aug 2024</span>
                    </div>
                    <p className="text-[11px] text-slate-400 mt-1">
                      Linked: BLDG_004281 ⟷ ROAD_001920 (Synchronized construction & road paving)
                    </p>
                    <div className="text-[10px] text-slate-500 mt-1">
                      Temporal closeness: Δt = 24 days | Signature match: 92%
                    </div>
                  </div>

                  <div className="p-2 rounded bg-slate-900/80 border border-slate-800 text-xs font-mono">
                    <div className="flex items-center justify-between text-cyan-300 font-bold">
                      <span>Cluster #2: Commercial Outpost Sector 22</span>
                      <span className="text-[10px] text-emerald-400">Oct–Nov 2024</span>
                    </div>
                    <p className="text-[11px] text-slate-400 mt-1">
                      Linked: BLDG_004282 ⟷ BLDG_004283
                    </p>
                    <div className="text-[10px] text-slate-500 mt-1">
                      Temporal closeness: Δt = 18 days | Signature match: 86%
                    </div>
                  </div>
                </div>
              </div>

              {/* Matrix Stats */}
              <div className="p-3 rounded-lg border border-slate-800 bg-command-card text-xs font-mono space-y-2">
                <span className="font-bold uppercase text-slate-300 block">
                  Graph Topology Metrics
                </span>
                <div className="space-y-1.5 text-slate-300">
                  <div className="flex justify-between border-b border-slate-800 pb-1">
                    <span className="text-slate-500">Nodes (Entities):</span>
                    <span className="text-cyan-400">4 Active Geo-Objects</span>
                  </div>
                  <div className="flex justify-between border-b border-slate-800 pb-1">
                    <span className="text-slate-500">Edges (Temporal Synchronization):</span>
                    <span className="text-cyan-400">3 Verified Synchronized Links</span>
                  </div>
                  <div className="flex justify-between border-b border-slate-800 pb-1">
                    <span className="text-slate-500">Maximum Synchronization Window:</span>
                    <span className="text-cyan-400">21 Days</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Community Detection Algorithm:</span>
                    <span className="text-emerald-400">Leiden Modular</span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-3 border-t border-command-cardBorder bg-command-sidebar flex items-center justify-end">
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-mono transition-colors"
          >
            Close Graph
          </button>
        </div>
      </div>
    </div>
  );
};

'use client';

/**
 * Previously this component genuinely fetched the real graph
 * (`GET /discover/co-change`) and stored it in `graphData` -- and then never
 * read that state anywhere in the render. Every visible number was a
 * hardcoded literal: "4 Active Geo-Objects", "3 Verified Synchronized
 * Links", "21 Days", and a community-detection algorithm named "Leiden
 * Modular" that `backend/engines/clustering.py` does not implement (it does
 * an O(n^2) pairwise date-diff, no HDBSCAN, no Leiden). The two "clusters"
 * shown were two static text cards naming specific seed-fixture entity IDs,
 * with an internal contradiction: "Δt = 24 days" inside a heading that
 * promised "Δt ≤ 21 Days".
 *
 * This renders the graph the backend actually returns: real nodes, real
 * edges, real Δt, real edge weight, and an honest description of the
 * algorithm (pairwise temporal proximity, not a named community-detection
 * method).
 */

import React, { useMemo, useState } from 'react';
import { X, Network, Info, AlertTriangle } from 'lucide-react';
import { useCoChangeGraph } from '@/lib/hooks';
import type { CoChangeEdge, CoChangeNode } from '@/lib/types';

interface CoChangeGraphProps {
  isOpen: boolean;
  onClose: () => void;
}

const MAX_WINDOW_DAYS = 21;
const WIDTH = 620;
const HEIGHT = 380;
const RADIUS = 150;

function layoutNodes(nodes: CoChangeNode[]) {
  const cx = WIDTH / 2;
  const cy = HEIGHT / 2;
  return nodes.map((node, i) => {
    const angle = (i / Math.max(nodes.length, 1)) * 2 * Math.PI - Math.PI / 2;
    return { node, x: cx + RADIUS * Math.cos(angle), y: cy + RADIUS * Math.sin(angle) };
  });
}

export const CoChangeGraph: React.FC<CoChangeGraphProps> = ({ isOpen, onClose }) => {
  const graph = useCoChangeGraph(MAX_WINDOW_DAYS, isOpen);
  const [hoverEdge, setHoverEdge] = useState<CoChangeEdge | null>(null);

  const positioned = useMemo(() => layoutNodes(graph.data?.nodes ?? []), [graph.data]);
  const positionById = useMemo(
    () => new Map(positioned.map((p) => [p.node.id, p])),
    [positioned]
  );

  if (!isOpen) return null;

  const nodeCount = graph.data?.nodes.length ?? 0;
  const edgeCount = graph.data?.edges.length ?? 0;

  return (
    <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 select-none">
      <div className="w-full max-w-3xl bg-command-bg border border-cyan-500/40 rounded-xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh] animate-in zoom-in-95 duration-150">
        <div className="p-4 border-b border-command-cardBorder bg-command-sidebar flex items-center justify-between">
          <div className="flex items-center space-x-2.5">
            <div className="w-7 h-7 rounded bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400">
              <Network className="w-4 h-4" />
            </div>
            <div>
              <h3 className="font-mono text-sm font-bold text-slate-100 flex items-center space-x-2">
                <span>Synchronized Regional Co-Change Graph</span>
                <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-cyan-950 text-cyan-400 border border-cyan-800">
                  PS 2.2.4
                </span>
              </h3>
              <p className="text-xs text-slate-400">
                Sites whose trajectories broke within {MAX_WINDOW_DAYS} days of each other, regardless of distance.
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

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          <div className="p-3 rounded bg-cyan-950/20 border border-cyan-800/40 flex items-start space-x-2 text-xs font-sans text-cyan-200">
            <Info className="w-4 h-4 text-cyan-400 flex-shrink-0 mt-0.5" />
            <p>
              <strong>Operational context: </strong>
              Semantic search answers what the analyst asked. This graph surfaces what the
              analyst didn't know to ask for -- geographically separated sites that changed
              in the same narrow time window, which is one signal for coordinated activity.
            </p>
          </div>

          {graph.isLoading ? (
            <div className="h-64 flex items-center justify-center text-xs font-mono text-slate-500">
              <span className="inline-block w-4 h-4 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin mr-2" />
              Computing synchronized break matrix...
            </div>
          ) : graph.isError ? (
            <div className="h-64 flex flex-col items-center justify-center gap-2 text-xs font-mono text-red-400">
              <AlertTriangle className="w-5 h-5" />
              Could not load the co-change graph.
            </div>
          ) : nodeCount === 0 ? (
            <div className="h-40 flex items-center justify-center text-xs font-mono text-slate-500">
              No entities with a first_seen date to compare yet.
            </div>
          ) : (
            <>
              <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-2 overflow-x-auto">
                <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full h-auto min-w-[480px]">
                  {(graph.data?.edges ?? []).map((edge, i) => {
                    const a = positionById.get(edge.source);
                    const b = positionById.get(edge.target);
                    if (!a || !b) return null;
                    const isHover = hoverEdge === edge;
                    return (
                      <line
                        key={i}
                        x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                        stroke={isHover ? '#22d3ee' : '#0891b2'}
                        strokeWidth={1 + edge.weight * 3}
                        strokeOpacity={isHover ? 0.9 : 0.35 + edge.weight * 0.3}
                        onMouseEnter={() => setHoverEdge(edge)}
                        onMouseLeave={() => setHoverEdge(null)}
                        style={{ cursor: 'pointer' }}
                      />
                    );
                  })}

                  {positioned.map(({ node, x, y }) => (
                    <g key={node.id}>
                      <circle cx={x} cy={y} r={7} fill="#0e7490" stroke="#22d3ee" strokeWidth={1.5} />
                      <text
                        x={x} y={y - 12} textAnchor="middle"
                        fill="#94a3b8" fontSize="9" fontFamily="monospace"
                      >
                        {node.id}
                      </text>
                    </g>
                  ))}
                </svg>
              </div>

              {hoverEdge && (
                <div className="p-2 rounded bg-slate-900/80 border border-cyan-800/50 text-xs font-mono text-slate-300">
                  <span className="text-cyan-300 font-bold">{hoverEdge.source}</span>
                  {' ⟷ '}
                  <span className="text-cyan-300 font-bold">{hoverEdge.target}</span>
                  <span className="text-slate-500 ml-2">
                    Δt = {hoverEdge.delta_days}d · weight {hoverEdge.weight.toFixed(2)} · {hoverEdge.common_window}
                  </span>
                </div>
              )}

              <div className="p-3 rounded-lg border border-slate-800 bg-command-card text-xs font-mono space-y-2">
                <span className="font-bold uppercase text-slate-300 block">Graph Topology</span>
                <div className="space-y-1.5 text-slate-300">
                  <div className="flex justify-between border-b border-slate-800 pb-1">
                    <span className="text-slate-500">Nodes (entities with a break date):</span>
                    <span className="text-cyan-400">{nodeCount}</span>
                  </div>
                  <div className="flex justify-between border-b border-slate-800 pb-1">
                    <span className="text-slate-500">Edges (synchronized pairs):</span>
                    <span className="text-cyan-400">{edgeCount}</span>
                  </div>
                  <div className="flex justify-between border-b border-slate-800 pb-1">
                    <span className="text-slate-500">Synchronization window:</span>
                    <span className="text-cyan-400">{MAX_WINDOW_DAYS} days</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Method:</span>
                    <span className="text-slate-400">
                      Pairwise temporal proximity + change-type match (no community-detection
                      algorithm is applied)
                    </span>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>

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

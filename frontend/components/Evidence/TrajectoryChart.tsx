'use client';

import React from 'react';
import { Activity, Calendar } from 'lucide-react';
import type { TimelinePoint } from '@/lib/types';

/** Re-exported from lib/types.ts; kept as an alias so existing imports of
 * `TrajectoryPoint` from this file keep working. */
export type TrajectoryPoint = TimelinePoint;

function formatTick(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 7);
  return d.toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
}

interface TrajectoryChartProps {
  trajectory: TrajectoryPoint[];
  breakDate?: string;
  breakDateCi?: string[];
  ciWidthDays?: number;
}

export const TrajectoryChart: React.FC<TrajectoryChartProps> = ({
  trajectory,
  breakDate = "2024-08-21",
  breakDateCi = ["2024-07-14", "2024-08-21"],
  ciWidthDays = 38
}) => {
  if (!trajectory || trajectory.length === 0) {
    return (
      <div className="bg-command-card border border-command-cardBorder rounded-lg p-4 text-center text-xs font-mono text-slate-500">
        Trajectory time-series data unavailable for this entity.
      </div>
    );
  }

  // Chart coordinate mapping
  const width = 640;
  const height = 180;
  const padX = 45;
  const padY = 25;
  const plotW = width - 2 * padX;
  const plotH = height - 2 * padY;

  const n = trajectory.length;
  const getX = (idx: number) => padX + (idx / (n - 1)) * plotW;

  const maxVal = Math.max(...trajectory.map(p => Math.max(p.observed_embed_norm, p.baseline_embed_norm)), 2.5);
  const minVal = Math.min(...trajectory.map(p => Math.min(p.observed_embed_norm, p.baseline_embed_norm)), 0.5);

  const getY = (val: number) => padY + plotH - ((val - minVal) / (maxVal - minVal || 1)) * plotH;

  // Polyline points
  const obsPoints = trajectory.map((p, i) => `${getX(i)},${getY(p.observed_embed_norm)}`).join(' ');
  const basePoints = trajectory.map((p, i) => `${getX(i)},${getY(p.baseline_embed_norm)}`).join(' ');

  // Locate break index for vertical indicator
  let breakIdx = trajectory.findIndex(p => p.t >= breakDate);
  if (breakIdx === -1) breakIdx = Math.floor(n * 0.4);
  const breakX = getX(breakIdx);

  // Shaded confidence interval band, positioned from the real CI bounds.
  //
  // Previously this was `breakX - 24` / `breakX + 6` -- a fixed pixel offset
  // with no relationship to breakDateCi or ciWidthDays, so the shaded "Break
  // CI Range" did not represent the interval it claimed to. Finding the
  // nearest trajectory index to each bound and mapping through the same
  // getX() used for every other point keeps it consistent with the axis.
  const nearestIndexToDate = (iso: string): number => {
    let best = 0;
    let bestDiff = Infinity;
    trajectory.forEach((p, i) => {
      const diff = Math.abs(new Date(p.t).getTime() - new Date(iso).getTime());
      if (diff < bestDiff) {
        bestDiff = diff;
        best = i;
      }
    });
    return best;
  };

  const ciLowIdx = breakDateCi[0] ? nearestIndexToDate(breakDateCi[0]) : Math.max(0, breakIdx - 1);
  const ciHighIdx = breakDateCi[1] ? nearestIndexToDate(breakDateCi[1]) : breakIdx;
  const ciStartX = Math.min(getX(ciLowIdx), getX(ciHighIdx));
  const ciEndX = Math.max(getX(ciLowIdx), getX(ciHighIdx));

  // X-axis ticks from the trajectory's actual dates, not fixed labels at
  // fixed fractions of the plot width regardless of what dates are plotted.
  const tickCount = Math.min(5, n);
  const tickIndices = Array.from({ length: tickCount }, (_, i) =>
    Math.round((i / Math.max(tickCount - 1, 1)) * (n - 1))
  );

  const yTickCount = 4;
  const yTicks = Array.from({ length: yTickCount + 1 }, (_, i) => minVal + (i / yTickCount) * (maxVal - minVal));

  return (
    <div className="bg-command-card border border-command-cardBorder rounded-lg p-3">
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center space-x-1.5">
          <Activity className="w-3.5 h-3.5 text-cyan-400" />
          <span className="text-xs font-mono font-bold uppercase tracking-wider text-slate-200">
            Multi-Temporal Trajectory & Break Analysis
          </span>
        </div>

        <div className="flex items-center space-x-1.5 text-[11px] font-mono text-cyan-300 bg-cyan-950/60 px-2 py-0.5 rounded border border-cyan-900/40">
          <Calendar className="w-3 h-3 text-cyan-400" />
          <span>Earliest Break: {breakDateCi[0]} → {breakDateCi[1]} ({ciWidthDays}d CI)</span>
        </div>
      </div>

      {/* SVG Chart */}
      <div className="relative w-full overflow-x-auto bg-slate-950/90 rounded border border-slate-800/80 p-1">
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto min-w-[500px]">
          {/* Grid lines + real Y-axis labels (magnitude of the visual embedding norm) */}
          {yTicks.map((val, i) => (
            <g key={i}>
              <line
                x1={padX} y1={getY(val)} x2={width - padX} y2={getY(val)}
                stroke={i === 0 || i === yTickCount ? '#334155' : '#1e293b'}
                strokeDasharray={i === 0 || i === yTickCount ? undefined : '3 3'}
              />
              <text x={padX - 6} y={getY(val) + 3} fill="#64748b" fontSize="8" fontFamily="monospace" textAnchor="end">
                {val.toFixed(2)}
              </text>
            </g>
          ))}

          {/* Shaded confidence interval band */}
          <rect
            x={ciStartX}
            y={padY}
            width={ciEndX - ciStartX}
            height={plotH}
            fill="#06b6d4"
            fillOpacity="0.12"
          />

          {/* Break Vertical Line */}
          <line
            x1={breakX}
            y1={padY}
            x2={breakX}
            y2={padY + plotH}
            stroke="#22d3ee"
            strokeWidth="1.5"
            strokeDasharray="4 2"
          />

          {/* Seasonal Baseline Curve (Dashed Amber) */}
          <polyline
            fill="none"
            stroke="#f59e0b"
            strokeWidth="1.5"
            strokeDasharray="4 3"
            points={basePoints}
          />

          {/* Observed Trajectory Curve (Solid Cyan) */}
          <polyline
            fill="none"
            stroke="#06b6d4"
            strokeWidth="2"
            points={obsPoints}
          />

          {/* Observation data nodes, with a native tooltip carrying the real
              per-observation values (date, z-score, sensor, valid fraction)
              -- z_score, ndvi and sar_vv_db previously existed on every point
              and were never surfaced anywhere in this chart. */}
          {trajectory.map((p, i) => (
            <circle
              key={i}
              cx={getX(i)}
              cy={getY(p.observed_embed_norm)}
              r={i === breakIdx ? 4 : 2.5}
              fill={i >= breakIdx ? "#22d3ee" : "#38bdf8"}
              stroke="#0f172a"
              strokeWidth="1"
            >
              <title>
                {p.t} · {p.sensor} · z={p.z_score.toFixed(2)} · valid={(p.valid_fraction * 100).toFixed(0)}%
                {p.ndvi != null ? ` · NDVI=${p.ndvi.toFixed(2)}` : ''}
                {p.sar_vv_db != null ? ` · VV=${p.sar_vv_db.toFixed(1)}dB` : ''}
              </title>
            </circle>
          ))}

          {/* X-axis labels from the trajectory's actual observation dates. */}
          {tickIndices.map((idx, i) => (
            <text
              key={i}
              x={getX(idx)}
              y={height - 6}
              fill="#64748b"
              fontSize="9"
              fontFamily="monospace"
              textAnchor={i === 0 ? 'start' : i === tickIndices.length - 1 ? 'end' : 'middle'}
            >
              {formatTick(trajectory[idx].t)}
            </text>
          ))}

          {/* Break label */}
          <text x={breakX - 30} y={padY - 8} fill="#22d3ee" fontSize="10" fontFamily="monospace" fontWeight="bold">
            Break: {breakDate}
          </text>
        </svg>
      </div>

      {/* Legend */}
      <div className="flex items-center justify-center space-x-6 mt-2 text-[11px] font-mono text-slate-400">
        <div className="flex items-center space-x-1.5">
          <span className="w-3 h-0.5 bg-cyan-400 inline-block" />
          <span>Observed Embedding Trajectory</span>
        </div>
        <div className="flex items-center space-x-1.5">
          <span className="w-3 h-0.5 bg-amber-400 border-t border-dashed inline-block" />
          <span>Harmonic Seasonal Baseline</span>
        </div>
        <div className="flex items-center space-x-1.5">
          <span className="w-2.5 h-2.5 bg-cyan-500/20 border border-cyan-400 inline-block rounded-xs" />
          <span>Break CI Range</span>
        </div>
      </div>
    </div>
  );
};

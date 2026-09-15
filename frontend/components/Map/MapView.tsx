'use client';

import React, { useState } from 'react';
import { SearchResultItem } from '../Results/ResultCard';
import { Layers, MapPin, Eye, Compass, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react';

interface MapViewProps {
  entities: SearchResultItem[];
  selectedEntity: SearchResultItem | null;
  onSelectEntity: (entity: SearchResultItem) => void;
}

export const MapView: React.FC<MapViewProps> = ({ entities, selectedEntity, onSelectEntity }) => {
  const [layers, setLayers] = useState({
    optical: true,
    sar: false,
    entities: true,
    water: true,
    roads: true
  });

  // Transform coordinates to canvas percentage space
  // Delhi AOI bounds: Lon 77.10 -> 77.35, Lat 28.50 -> 28.72
  const minLon = 77.10, maxLon = 77.35;
  const minLat = 28.50, maxLat = 28.72;

  const toPercent = (lon: number, lat: number) => {
    const x = ((lon - minLon) / (maxLon - minLon)) * 100;
    const y = 100 - ((lat - minLat) / (maxLat - minLat)) * 100;
    return { x: Math.max(5, Math.min(95, x)), y: Math.max(5, Math.min(95, y)) };
  };

  // Yamuna river course points
  const riverCoords = [
    [77.215, 28.720],
    [77.228, 28.690],
    [77.240, 28.660],
    [77.248, 28.630],
    [77.255, 28.590],
    [77.280, 28.550],
    [77.310, 28.510]
  ];

  const riverSvgPath = riverCoords.map((c, i) => {
    const p = toPercent(c[0], c[1]);
    return `${i === 0 ? 'M' : 'L'} ${p.x}% ${p.y}%`;
  }).join(' ');

  return (
    <div className="relative w-full h-full min-h-[420px] rounded-lg overflow-hidden border border-command-cardBorder bg-[#070b12] tactical-grid select-none flex flex-col">
      {/* Top Map HUD Status */}
      <div className="absolute top-3 left-3 z-20 flex items-center space-x-2 pointer-events-none">
        <div className="px-2.5 py-1 rounded bg-slate-950/80 border border-slate-800 text-[11px] font-mono text-slate-300 backdrop-blur-md flex items-center space-x-1.5 shadow">
          <Compass className="w-3.5 h-3.5 text-cyan-400 animate-spin-slow" />
          <span>MAP: Delhi-NCR (EPSG:32643 UTM 43N)</span>
        </div>
        <div className="px-2 py-1 rounded bg-slate-950/80 border border-slate-800 text-[10px] font-mono text-cyan-400 backdrop-blur-md">
          Offline MBTiles Active
        </div>
      </div>

      {/* Floating Layer Controls */}
      <div className="absolute top-3 right-3 z-20 bg-slate-950/85 border border-slate-800 rounded p-2 text-xs font-mono text-slate-300 backdrop-blur-md shadow-lg space-y-1">
        <div className="flex items-center space-x-1 text-[10px] uppercase font-bold text-slate-400 mb-1 border-b border-slate-800 pb-1">
          <Layers className="w-3 h-3 text-cyan-400" />
          <span>Layers</span>
        </div>
        <label className="flex items-center space-x-1.5 cursor-pointer hover:text-white">
          <input
            type="checkbox"
            checked={layers.optical}
            onChange={(e) => setLayers({ ...layers, optical: e.target.checked })}
            className="rounded bg-slate-900 border-slate-700 text-cyan-500 focus:ring-0"
          />
          <span className="text-[11px]">Optical (S2)</span>
        </label>
        <label className="flex items-center space-x-1.5 cursor-pointer hover:text-white">
          <input
            type="checkbox"
            checked={layers.sar}
            onChange={(e) => setLayers({ ...layers, sar: e.target.checked })}
            className="rounded bg-slate-900 border-slate-700 text-cyan-500 focus:ring-0"
          />
          <span className="text-[11px]">SAR (S1 GRD)</span>
        </label>
        <label className="flex items-center space-x-1.5 cursor-pointer hover:text-white">
          <input
            type="checkbox"
            checked={layers.entities}
            onChange={(e) => setLayers({ ...layers, entities: e.target.checked })}
            className="rounded bg-slate-900 border-slate-700 text-cyan-500 focus:ring-0"
          />
          <span className="text-[11px]">Entities ({entities.length})</span>
        </label>
        <label className="flex items-center space-x-1.5 cursor-pointer hover:text-white">
          <input
            type="checkbox"
            checked={layers.water}
            onChange={(e) => setLayers({ ...layers, water: e.target.checked })}
            className="rounded bg-slate-900 border-slate-700 text-cyan-500 focus:ring-0"
          />
          <span className="text-[11px]">Yamuna River</span>
        </label>
      </div>

      {/* SVG Canvas Map Surface */}
      <div className="relative flex-1 w-full h-full">
        <svg className="absolute inset-0 w-full h-full pointer-events-none">
          {/* AOI Perimeter Box */}
          <rect
            x="4%"
            y="4%"
            width="92%"
            height="92%"
            fill="none"
            stroke="#1e293b"
            strokeWidth="1"
            strokeDasharray="6 4"
          />

          {/* Reference Water: Yamuna River */}
          {layers.water && (
            <g>
              <path
                d={riverSvgPath}
                fill="none"
                stroke="#0284c7"
                strokeWidth="12"
                strokeOpacity="0.4"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d={riverSvgPath}
                fill="none"
                stroke="#38bdf8"
                strokeWidth="3"
                strokeOpacity="0.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <text x="52%" y="42%" fill="#38bdf8" fontSize="10" fontFamily="monospace" opacity="0.8">
                Yamuna River Corridor
              </text>
            </g>
          )}

          {/* Reference Roads (Ring Road representation) */}
          {layers.roads && (
            <path
              d="M 25% 30% Q 55% 45% 65% 75%"
              fill="none"
              stroke="#64748b"
              strokeWidth="2"
              strokeOpacity="0.4"
              strokeDasharray="5 3"
            />
          )}
        </svg>

        {/* Entity Polygon Markers */}
        {layers.entities && entities.map((e) => {
          const pt = toPercent(e.location.lon, e.location.lat);
          const isSelected = selectedEntity?.entity_id === e.entity_id;

          return (
            <div
              key={e.entity_id}
              style={{ left: `${pt.x}%`, top: `${pt.y}%` }}
              onClick={() => onSelectEntity(e)}
              className="absolute -translate-x-1/2 -translate-y-1/2 cursor-pointer z-30 group"
            >
              {/* Radar pulse beacon on selected */}
              {isSelected && (
                <span className="absolute -inset-2 rounded-full bg-cyan-400/30 animate-ping pointer-events-none" />
              )}

              {/* Marker pin */}
              <div className={`flex items-center space-x-1 px-2 py-1 rounded shadow-lg border text-xs font-mono transition-transform group-hover:scale-110 ${
                isSelected
                  ? 'bg-cyan-500 text-slate-950 border-cyan-300 font-bold shadow-cyan-500/50'
                  : 'bg-slate-900/90 text-cyan-300 border-slate-700 hover:border-cyan-400'
              }`}>
                <MapPin className="w-3 h-3" />
                <span>#{e.rank}</span>
              </div>

              {/* Hover Tooltip Card */}
              <div className="hidden group-hover:block absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-48 p-2 rounded bg-slate-950/95 border border-cyan-500/60 shadow-xl text-[11px] font-mono text-slate-200 pointer-events-none z-40 backdrop-blur-md">
                <div className="font-bold text-cyan-300">{e.entity_id}</div>
                <div className="text-slate-400 capitalize">{e.change_type} · {Math.round(e.confidence * 100)}% Conf</div>
                <div className="text-slate-400">{Math.round(e.relations.river_distance_m || 320)}m from river</div>
                <div className="text-emerald-400 mt-1 flex items-center space-x-1">
                  <Eye className="w-3 h-3" />
                  <span>Click to inspect evidence</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Map Bottom Scale & Coordinate HUD */}
      <div className="h-7 border-t border-command-cardBorder bg-slate-950/90 px-3 flex items-center justify-between text-[10px] font-mono text-slate-500">
        <div>LAT: 28.6142° N · LON: 77.2451° E</div>
        <div className="flex items-center space-x-3">
          <span>SCALE: 1:25,000</span>
          <span>GRID: 10m COMMON EPSG:32643</span>
        </div>
      </div>
    </div>
  );
};

'use client';

import React, { useState, useRef, useEffect } from 'react';
import { SlidersHorizontal, Image as ImageIcon, Radio } from 'lucide-react';

interface BeforeAfterSwipeProps {
  beforeUrl: string;
  afterUrl: string;
  sarUrl?: string;
  beforeDate?: string;
  afterDate?: string;
}

export const BeforeAfterSwipe: React.FC<BeforeAfterSwipeProps> = ({
  beforeUrl,
  afterUrl,
  sarUrl,
  beforeDate = "2024-07-11 (Optical)",
  afterDate = "2025-06-14 (Optical)"
}) => {
  const [sliderPos, setSliderPos] = useState(50);
  const [isDragging, setIsDragging] = useState(false);
  const [showSar, setShowSar] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const activeAfterUrl = showSar && sarUrl ? sarUrl : afterUrl;
  const activeAfterLabel = showSar && sarUrl ? "2024-08-19 (Sentinel-1 SAR)" : afterDate;

  const handleMove = (clientX: number) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const x = clientX - rect.left;
    const pct = Math.max(0, Math.min(100, (x / rect.width) * 100));
    setSliderPos(pct);
  };

  const handleTouchMove = (e: React.TouchEvent) => {
    if (isDragging) {
      handleMove(e.touches[0].clientX);
    }
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (isDragging) {
      handleMove(e.clientX);
    }
  };

  return (
    <div className="bg-command-card border border-command-cardBorder rounded-lg p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-mono font-bold uppercase tracking-wider text-slate-200 flex items-center space-x-1.5">
          <SlidersHorizontal className="w-3.5 h-3.5 text-cyan-400" />
          <span>Before / After Swipe Comparison</span>
        </span>

        {sarUrl && (
          <button
            type="button"
            onClick={() => setShowSar(!showSar)}
            className={`flex items-center space-x-1 text-[11px] font-mono px-2 py-0.5 rounded border transition-colors ${
              showSar
                ? 'bg-cyan-950 text-cyan-300 border-cyan-700'
                : 'bg-slate-900 text-slate-400 border-slate-800 hover:text-slate-200'
            }`}
          >
            <Radio className="w-3 h-3 text-cyan-400" />
            <span>{showSar ? 'Showing SAR GRD' : 'View S1 SAR'}</span>
          </button>
        )}
      </div>

      <div
        ref={containerRef}
        onMouseDown={() => setIsDragging(true)}
        onMouseUp={() => setIsDragging(false)}
        onMouseLeave={() => setIsDragging(false)}
        onMouseMove={handleMouseMove}
        onTouchStart={() => setIsDragging(true)}
        onTouchEnd={() => setIsDragging(false)}
        onTouchMove={handleTouchMove}
        className="relative h-64 sm:h-72 w-full rounded overflow-hidden border border-slate-800 cursor-ew-resize select-none bg-slate-950"
      >
        {/* AFTER Image (Full background) */}
        <img
          src={activeAfterUrl}
          alt="After Observation"
          className="absolute inset-0 w-full h-full object-cover"
        />

        {/* BEFORE Image (Clipped overlay) */}
        <div
          className="absolute inset-0 overflow-hidden"
          style={{ width: `${sliderPos}%` }}
        >
          <img
            src={beforeUrl}
            alt="Before Observation"
            className="absolute inset-0 w-full h-full object-cover max-w-none"
            style={{ width: containerRef.current ? `${containerRef.current.clientWidth}px` : '100%' }}
          />
        </div>

        {/* Draggable Divider Line */}
        <div
          className="absolute top-0 bottom-0 w-0.5 bg-cyan-400 shadow-[0_0_8px_rgba(6,182,212,0.8)] z-10"
          style={{ left: `${sliderPos}%` }}
        >
          <div className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-6 h-6 rounded-full bg-slate-900 border-2 border-cyan-400 flex items-center justify-center text-cyan-400 shadow-md">
            <SlidersHorizontal className="w-3 h-3" />
          </div>
        </div>

        {/* Labels */}
        <div className="absolute top-2 left-2 z-20 pointer-events-none">
          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-950/80 text-slate-200 border border-slate-700/60 backdrop-blur-sm">
            BEFORE: {beforeDate}
          </span>
        </div>
        <div className="absolute top-2 right-2 z-20 pointer-events-none">
          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-950/80 text-cyan-300 border border-cyan-900/60 backdrop-blur-sm">
            AFTER: {activeAfterLabel}
          </span>
        </div>
      </div>

      <p className="text-[10px] font-mono text-slate-500 mt-1.5 text-center">
        ◀ Drag slider left/right to compare pre-change baseline with post-change structure ▶
      </p>
    </div>
  );
};

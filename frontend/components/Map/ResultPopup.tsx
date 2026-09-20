'use client';

/**
 * Extracted from the inline hover tooltip that used to live inside
 * MapView.tsx's marker div (`group-hover:block absolute ...`), which also
 * fabricated a distance: `{Math.round(e.relations.river_distance_m || 320)}m
 * from river` -- the `|| 320` silently substituted a plausible-looking value
 * matching the seed fixture's constant whenever the real distance was
 * missing or zero. Renders the real relation, or says explicitly that none
 * was computed.
 */

import React from 'react';
import { Eye } from 'lucide-react';
import type { SearchResult } from '@/lib/types';

export const ResultPopup: React.FC<{ entity: SearchResult }> = ({ entity }) => {
  const riverDist = entity.relations.river_distance_m;

  return (
    <div className="w-48 p-2 text-[11px] font-mono text-slate-200">
      <div className="font-bold text-cyan-300">{entity.entity_id}</div>
      <div className="text-slate-400 capitalize">
        {entity.change_type} · {Math.round(entity.confidence * 100)}% conf
      </div>
      <div className="text-slate-400">
        {riverDist != null ? `${Math.round(riverDist)}m from water` : 'No water relation computed'}
      </div>
      <div className="text-emerald-400 mt-1 flex items-center space-x-1">
        <Eye className="w-3 h-3" />
        <span>Click to inspect evidence</span>
      </div>
    </div>
  );
};

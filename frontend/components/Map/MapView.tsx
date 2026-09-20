'use client';

/**
 * Real MapLibre GL map. Replaces a component that was an SVG `<div>` doing
 * naive lon/lat -> percent math: AOI bounds hardcoded to
 * `77.10/77.35/28.50/28.72` (MapView.tsx:24-25, previously); the Yamuna drawn
 * as seven hand-picked coordinate pairs (MapView.tsx:34-42); the road network
 * as a single SVG bezier curve (MapView.tsx:151); a static HUD showing
 * BLDG_004281's seed centroid as if it were the cursor position; and a label
 * reading "Offline MBTiles Active" while the app never requested a single
 * tile from anywhere.
 *
 * What changed:
 *   - real MapLibre GL instance with real pan/zoom (the Zoom/Fit icons were
 *     imported and unused before)
 *   - the backend's real GeoJSON `Polygon` per result is drawn -- previously
 *     discarded entirely; only a centroid marker was shown
 *   - AOI, water and road reference layers are fetched from
 *     GET /api/v1/layers/{aoi,water,roads} (backend/api/layers.py, which did
 *     not exist before) instead of being hand-drawn
 *   - live cursor lat/lon and a real, zoom-derived scale bar in the HUD
 *   - the basemap is honestly labelled: a local tileserver style is used when
 *     configured and reachable, otherwise the map runs on a blank background
 *     with our own vector layers and says so, rather than claiming offline
 *     tiles that were never actually loaded
 */

import React, { useCallback, useMemo, useRef, useState } from 'react';
import Map, {
  Layer,
  MapRef,
  NavigationControl,
  Popup,
  Source,
  type MapLayerMouseEvent,
} from 'react-map-gl/maplibre';
import type { StyleSpecification } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Layers, Compass, Maximize2 } from 'lucide-react';
import type { SearchResult } from '@/lib/types';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { ResultPopup } from './ResultPopup';

interface MapViewProps {
  entities: SearchResult[];
  selectedEntity: SearchResult | null;
  onSelectEntity: (entity: SearchResult) => void;
  /** AOI bounds from /api/v1/stats; falls back to the PRD's declared AOI if stats hasn't loaded yet. */
  bounds?: { min_lon: number; min_lat: number; max_lon: number; max_lat: number } | null;
}

const FALLBACK_BOUNDS = { min_lon: 77.10, min_lat: 28.50, max_lon: 77.35, max_lat: 28.72 };

// A local tileserver-gl instance serving the offline .mbtiles (docker-compose
// runs one on :8081, per PRD section 11.4). Configurable because the port and
// even whether one is running at all varies by deployment; the map degrades
// honestly rather than silently pointing at a public tile CDN, which would
// violate the offline requirement outright.
const LOCAL_TILESERVER_STYLE =
  process.env.NEXT_PUBLIC_TILESERVER_STYLE_URL || 'http://localhost:8081/styles/basemap/style.json';

const BLANK_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [
    { id: 'background', type: 'background', paint: { 'background-color': '#070b12' } },
  ],
};

function boundsToLngLatBounds(b: typeof FALLBACK_BOUNDS): [[number, number], [number, number]] {
  return [
    [b.min_lon, b.min_lat],
    [b.max_lon, b.max_lat],
  ];
}

/** Rough metres-per-pixel at a given latitude/zoom, for the scale bar text. */
function metersPerPixel(lat: number, zoom: number): number {
  return (156543.03392 * Math.cos((lat * Math.PI) / 180)) / Math.pow(2, zoom);
}

function formatScale(metersPerPx: number): string {
  const widthPx = 80;
  const meters = metersPerPx * widthPx;
  if (meters >= 1000) return `${(meters / 1000).toFixed(1)} km`;
  return `${Math.round(meters)} m`;
}

const ENTITY_COLORS: Record<string, string> = {
  building: '#f59e0b',
  road: '#94a3b8',
  water: '#38bdf8',
  vegetation: '#22c55e',
  bare_ground: '#a16207',
};

export const MapView: React.FC<MapViewProps> = ({ entities, selectedEntity, onSelectEntity, bounds }) => {
  const mapRef = useRef<MapRef>(null);
  const [layers, setLayers] = useState({ entities: true, water: true, roads: true });
  const [cursor, setCursor] = useState<{ lng: number; lat: number } | null>(null);
  const [zoom, setZoom] = useState(11);
  const [hoverInfo, setHoverInfo] = useState<{ entity: SearchResult; lng: number; lat: number } | null>(null);
  const [tileserverReachable, setTileserverReachable] = useState<boolean | null>(null);

  const effectiveBounds = bounds ?? FALLBACK_BOUNDS;
  const centerLon = (effectiveBounds.min_lon + effectiveBounds.max_lon) / 2;
  const centerLat = (effectiveBounds.min_lat + effectiveBounds.max_lat) / 2;

  // Probe the local tileserver once. A failed fetch just means "no basemap
  // staged" -- handled below by falling back to BLANK_STYLE -- not an error
  // worth surfacing, since running without a basemap is a legitimate state
  // pre-Phase-F1 (offline .mbtiles generation).
  useQuery({
    queryKey: ['tileserver-probe'],
    queryFn: async ({ signal }) => {
      try {
        const res = await fetch(LOCAL_TILESERVER_STYLE, { signal });
        setTileserverReachable(res.ok);
        return res.ok;
      } catch {
        setTileserverReachable(false);
        return false;
      }
    },
    retry: false,
    staleTime: Infinity,
  });

  const waterLayer = useQuery({
    queryKey: ['layer', 'water'],
    queryFn: ({ signal }) => api.referenceLayer('water', signal),
    retry: false,
  });
  const roadsLayer = useQuery({
    queryKey: ['layer', 'roads'],
    queryFn: ({ signal }) => api.referenceLayer('roads', signal),
    retry: false,
  });
  const aoiLayer = useQuery({
    queryKey: ['layer', 'aoi'],
    queryFn: ({ signal }) => api.referenceLayer('aoi', signal),
    retry: false,
  });

  const entityCollection = useMemo(
    () => ({
      type: 'FeatureCollection' as const,
      features: entities
        .filter((e) => e.geometry?.coordinates?.length)
        .map((e) => ({
          type: 'Feature' as const,
          properties: {
            entity_id: e.entity_id,
            entity_type: e.entity_type,
            rank: e.rank,
            confidence: e.confidence,
            selected: selectedEntity?.entity_id === e.entity_id,
            color: ENTITY_COLORS[e.entity_type] ?? '#06b6d4',
          },
          geometry: e.geometry as GeoJSON.Geometry,
        })),
    }),
    [entities, selectedEntity]
  );

  const handleClick = useCallback(
    (event: MapLayerMouseEvent) => {
      const feature = event.features?.[0];
      if (!feature) return;
      const entityId = feature.properties?.entity_id;
      const match = entities.find((e) => e.entity_id === entityId);
      if (match) onSelectEntity(match);
    },
    [entities, onSelectEntity]
  );

  const handleMouseMove = useCallback(
    (event: MapLayerMouseEvent) => {
      setCursor({ lng: event.lngLat.lng, lat: event.lngLat.lat });

      const feature = event.features?.[0];
      if (!feature) {
        setHoverInfo(null);
        return;
      }
      const entityId = feature.properties?.entity_id;
      const match = entities.find((e) => e.entity_id === entityId);
      setHoverInfo(match ? { entity: match, lng: event.lngLat.lng, lat: event.lngLat.lat } : null);
    },
    [entities]
  );

  const handleFit = useCallback(() => {
    mapRef.current?.fitBounds(boundsToLngLatBounds(effectiveBounds), { padding: 32, duration: 400 });
  }, [effectiveBounds]);

  const mapStyle: StyleSpecification | string =
    tileserverReachable === true ? LOCAL_TILESERVER_STYLE : BLANK_STYLE;

  return (
    <div className="relative w-full h-full min-h-[420px] rounded-lg overflow-hidden border border-command-cardBorder bg-[#070b12] select-none flex flex-col">
      <div className="absolute top-3 left-3 z-20 flex items-center space-x-2 pointer-events-none">
        <div className="px-2.5 py-1 rounded bg-slate-950/80 border border-slate-800 text-[11px] font-mono text-slate-300 backdrop-blur-md flex items-center space-x-1.5 shadow">
          <Compass className="w-3.5 h-3.5 text-cyan-400" />
          <span>Delhi-NCR / Yamuna corridor</span>
        </div>
        <div
          className={`px-2 py-1 rounded border text-[10px] font-mono backdrop-blur-md ${
            tileserverReachable
              ? 'bg-slate-950/80 border-slate-800 text-cyan-400'
              : 'bg-amber-950/60 border-amber-900 text-amber-400'
          }`}
        >
          {tileserverReachable === null
            ? 'Checking basemap…'
            : tileserverReachable
              ? 'Offline basemap tiles active'
              : 'No basemap tiles staged (see PRD 11.4)'}
        </div>
      </div>

      <div className="absolute top-3 right-3 z-20 flex flex-col items-end gap-2">
        <div className="flex flex-col rounded bg-slate-950/85 border border-slate-800 shadow-lg overflow-hidden">
          <button
            type="button"
            onClick={() => mapRef.current?.zoomIn({ duration: 200 })}
            className="w-8 h-8 flex items-center justify-center text-slate-300 hover:bg-slate-800 hover:text-cyan-400 border-b border-slate-800"
            aria-label="Zoom in"
          >
            +
          </button>
          <button
            type="button"
            onClick={() => mapRef.current?.zoomOut({ duration: 200 })}
            className="w-8 h-8 flex items-center justify-center text-slate-300 hover:bg-slate-800 hover:text-cyan-400 border-b border-slate-800"
            aria-label="Zoom out"
          >
            −
          </button>
          <button
            type="button"
            onClick={handleFit}
            className="w-8 h-8 flex items-center justify-center text-slate-300 hover:bg-slate-800 hover:text-cyan-400"
            aria-label="Fit to AOI"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>
        </div>

        <div className="bg-slate-950/85 border border-slate-800 rounded p-2 text-xs font-mono text-slate-300 backdrop-blur-md shadow-lg space-y-1 min-w-[150px]">
          <div className="flex items-center space-x-1 text-[10px] uppercase font-bold text-slate-400 mb-1 border-b border-slate-800 pb-1">
            <Layers className="w-3 h-3 text-cyan-400" />
            <span>Layers</span>
          </div>
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
            <span className="text-[11px]">Water ({waterLayer.data?.features.length ?? 0})</span>
          </label>
          <label className="flex items-center space-x-1.5 cursor-pointer hover:text-white">
            <input
              type="checkbox"
              checked={layers.roads}
              onChange={(e) => setLayers({ ...layers, roads: e.target.checked })}
              className="rounded bg-slate-900 border-slate-700 text-cyan-500 focus:ring-0"
            />
            <span className="text-[11px]">Roads ({roadsLayer.data?.features.length ?? 0})</span>
          </label>
        </div>
      </div>

      <div className="relative flex-1 w-full h-full">
        <Map
          ref={mapRef}
          mapStyle={mapStyle}
          initialViewState={{
            longitude: centerLon,
            latitude: centerLat,
            zoom: 11,
          }}
          onZoom={(e) => setZoom(e.viewState.zoom)}
          onMouseMove={handleMouseMove}
          onMouseLeave={() => { setCursor(null); setHoverInfo(null); }}
          onClick={handleClick}
          interactiveLayerIds={['entities-fill']}
        >
          <NavigationControl showCompass={false} position="bottom-right" style={{ display: 'none' }} />

          {aoiLayer.data && (
            <Source id="aoi" type="geojson" data={aoiLayer.data}>
              <Layer
                id="aoi-line"
                type="line"
                paint={{ 'line-color': '#1e293b', 'line-width': 1.5, 'line-dasharray': [4, 3] }}
              />
            </Source>
          )}

          {layers.water && waterLayer.data && (
            <Source id="water" type="geojson" data={waterLayer.data}>
              <Layer
                id="water-line"
                type="line"
                paint={{ 'line-color': '#38bdf8', 'line-width': 3, 'line-opacity': 0.85 }}
              />
              <Layer
                id="water-fill"
                type="fill"
                filter={['==', ['geometry-type'], 'Polygon']}
                paint={{ 'fill-color': '#0284c7', 'fill-opacity': 0.25 }}
              />
            </Source>
          )}

          {layers.roads && roadsLayer.data && (
            <Source id="roads" type="geojson" data={roadsLayer.data}>
              <Layer
                id="roads-line"
                type="line"
                paint={{ 'line-color': '#64748b', 'line-width': 1.5, 'line-opacity': 0.6 }}
              />
            </Source>
          )}

          {layers.entities && (
            <Source id="entities" type="geojson" data={entityCollection}>
              <Layer
                id="entities-fill"
                type="fill"
                paint={{
                  'fill-color': ['get', 'color'],
                  'fill-opacity': ['case', ['get', 'selected'], 0.55, 0.3],
                }}
              />
              <Layer
                id="entities-outline"
                type="line"
                paint={{
                  'line-color': ['get', 'color'],
                  'line-width': ['case', ['get', 'selected'], 3, 1.5],
                }}
              />
            </Source>
          )}

          {hoverInfo && (
            <Popup
              longitude={hoverInfo.lng}
              latitude={hoverInfo.lat}
              closeButton={false}
              closeOnClick={false}
              offset={12}
              className="trinetra-map-popup"
            >
              <ResultPopup entity={hoverInfo.entity} />
            </Popup>
          )}
        </Map>
      </div>

      <div className="h-7 border-t border-command-cardBorder bg-slate-950/90 px-3 flex items-center justify-between text-[10px] font-mono text-slate-500">
        <div>
          {cursor
            ? `LAT: ${cursor.lat.toFixed(4)}° N · LON: ${cursor.lng.toFixed(4)}° E`
            : 'Move cursor over the map for coordinates'}
        </div>
        <div className="flex items-center space-x-3">
          <span>SCALE: ~{formatScale(metersPerPixel(centerLat, zoom))} / 80px</span>
          <span>GRID: 10m COMMON EPSG:32643</span>
        </div>
      </div>
    </div>
  );
};

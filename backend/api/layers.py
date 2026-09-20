"""
Reference vector layers for the map.

Previously there was no route for these at all. The frontend's map instead
hardcoded the Yamuna's course as seven coordinate pairs and the ring road as an
SVG bezier curve (MapView.tsx:34-42,151), while the real OSM extracts sat
unused on disk at data/raw/vectors/. This serves those real files directly.
"""

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/layers", tags=["Layers"])

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VECTOR_DIR = os.path.join(ROOT, "data", "raw", "vectors")

LAYER_FILES = {
    "aoi": "aoi.geojson",
    "water": "ref_water.geojson",
    "roads": "ref_roads.geojson",
    "landuse": "ref_landuse.geojson",
    "rail": "ref_rail.geojson",
}


@router.get("/{layer}")
async def get_layer(layer: str):
    """Serve a reference vector layer as GeoJSON."""
    filename = LAYER_FILES.get(layer)
    if not filename:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown layer '{layer}'. Available: {sorted(LAYER_FILES)}",
        )

    path = os.path.join(VECTOR_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail=f"{filename} has not been generated yet. Run "
                   f"scripts/01_define_aoi.py (aoi) or "
                   f"scripts/02_load_reference_vectors.py (water/roads/landuse/rail).",
        )

    return FileResponse(path, media_type="application/geo+json")

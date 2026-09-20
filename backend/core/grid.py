"""
Canonical analysis grid for the TRINETRA AOI.

Every raster the system ingests -- Sentinel-2 optical and Sentinel-1 SAR alike --
is warped onto the single grid defined here. PRD section 4.5 calls the shared 10 m
grid "non-negotiable", and it is: S2 L2A arrives natively in EPSG:32643, but
Sentinel-1 RTC over this AOI arrives in EPSG:32644. Without a common target grid
the two sensors never share pixel centres and the dual-witness verification in
section 7.8 compares unrelated ground positions.

The grid is derived deterministically from config/aoi.yaml so that two machines
building the archive independently produce byte-comparable geometry.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Tuple

import yaml

# Must come before anything initializes pyproj/rasterio CRS handling: repoints
# PROJ at the database bundled in this environment. See the module docstring.
from . import projenv  # noqa: F401

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config",
    "aoi.yaml",
)

# Authalic sphere radius used for the geodesic area check.
_EARTH_RADIUS_M = 6371008.8


@dataclass(frozen=True)
class CanonicalGrid:
    """The one grid every scene is resampled to."""

    crs: str
    resolution_m: float
    origin_x: float      # left edge, metres in `crs`
    origin_y: float      # top edge, metres in `crs`
    width: int           # pixels
    height: int          # pixels

    @property
    def transform(self):
        """rasterio affine transform for this grid."""
        from rasterio.transform import from_origin

        return from_origin(
            self.origin_x, self.origin_y, self.resolution_m, self.resolution_m
        )

    @property
    def bounds(self) -> Tuple[float, float, float, float]:
        """(left, bottom, right, top) in `crs` metres."""
        return (
            self.origin_x,
            self.origin_y - self.height * self.resolution_m,
            self.origin_x + self.width * self.resolution_m,
            self.origin_y,
        )

    @property
    def shape(self) -> Tuple[int, int]:
        return (self.height, self.width)

    def matches(self, transform, width: int, height: int, tol: float = 1e-6) -> bool:
        """True when a raster is already on this exact grid."""
        if width != self.width or height != self.height:
            return False
        own = self.transform
        return all(abs(a - b) < tol for a, b in zip(tuple(own)[:6], tuple(transform)[:6]))


def load_aoi_config(path: str | None = None) -> dict:
    with open(path or _CONFIG_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def geodesic_area_km2(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> float:
    """Area of a lat/lon rectangle on the authalic sphere, in km^2."""
    return (
        _EARTH_RADIUS_M
        * _EARTH_RADIUS_M
        * math.radians(max_lon - min_lon)
        * (math.sin(math.radians(max_lat)) - math.sin(math.radians(min_lat)))
    ) / 1e6


@lru_cache(maxsize=1)
def get_grid(path: str | None = None) -> CanonicalGrid:
    """
    Build the canonical grid from config/aoi.yaml.

    The AOI bbox is projected to the working CRS, then the extent is snapped
    *outward* to whole multiples of the snap distance. Snapping outward rather
    than rounding guarantees the grid always fully contains the declared AOI,
    and makes the origin independent of floating-point noise in the projection.
    """
    from pyproj import Transformer

    cfg = load_aoi_config(path)
    b = cfg["bounds"]
    grid_cfg = cfg.get("grid", {})

    crs = grid_cfg.get("crs", cfg["working_crs"])
    res = float(grid_cfg.get("resolution_m", 10.0))
    snap = float(grid_cfg.get("snap_m", res))

    transformer = Transformer.from_crs(cfg["storage_crs"], crs, always_xy=True)

    # Project all four corners, not just two: the graticule is not rectangular in
    # UTM, so taking only (min,min) and (max,max) would clip the AOI corners.
    xs, ys = [], []
    for lon, lat in (
        (b["min_lon"], b["min_lat"]),
        (b["max_lon"], b["min_lat"]),
        (b["max_lon"], b["max_lat"]),
        (b["min_lon"], b["max_lat"]),
    ):
        x, y = transformer.transform(lon, lat)
        xs.append(x)
        ys.append(y)

    left = math.floor(min(xs) / snap) * snap
    right = math.ceil(max(xs) / snap) * snap
    bottom = math.floor(min(ys) / snap) * snap
    top = math.ceil(max(ys) / snap) * snap

    width = int(round((right - left) / res))
    height = int(round((top - bottom) / res))

    return CanonicalGrid(
        crs=crs,
        resolution_m=res,
        origin_x=left,
        origin_y=top,
        width=width,
        height=height,
    )


def describe() -> str:
    g = get_grid()
    left, bottom, right, top = g.bounds
    return (
        f"CanonicalGrid {g.crs} @ {g.resolution_m:g} m\n"
        f"  size   : {g.width} x {g.height} px ({g.width * g.height / 1e6:.2f} Mpx)\n"
        f"  origin : ({g.origin_x:.1f}, {g.origin_y:.1f})\n"
        f"  bounds : ({left:.1f}, {bottom:.1f}, {right:.1f}, {top:.1f})\n"
        f"  extent : {(right - left) / 1000:.2f} x {(top - bottom) / 1000:.2f} km"
    )


if __name__ == "__main__":
    print(describe())

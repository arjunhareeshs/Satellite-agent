"""
Windowed COG reads, warping onto the canonical grid, and COG writing.

The whole download strategy rests on one property we verified against the live
asset store before committing to it: the Sentinel-2 and Sentinel-1 assets are
Cloud-Optimized GeoTIFFs served with `Accept-Ranges: bytes`. A single S2 band is
238 MB, but the AOI is a 24 km square inside it, so a windowed `/vsicurl` read
pulls only the tiles that intersect the AOI. That turns a ~400 GB archive
download into ~11 GB of clipped COGs.

Everything written here lands on the canonical grid from backend.core.grid, so
optical and SAR share pixel centres exactly (PRD section 4.5).
"""

from __future__ import annotations

import hashlib
import os
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

# Must come before rasterio initializes: repoints PROJ at the database bundled
# in this environment rather than a system-wide one. See the module docstring.
from backend.core import projenv  # noqa: F401

# GDAL/rasterio tuning for reading remote COGs. Without these every windowed
# read re-opens the file and re-reads the header, which dominates wall clock.
GDAL_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "GDAL_HTTP_MULTIPLEX": "YES",
    "GDAL_HTTP_VERSION": "2",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MAX_RETRY": "5",
    "GDAL_HTTP_RETRY_DELAY": "2",
    "VSI_CACHE": "TRUE",
    "VSI_CACHE_SIZE": "134217728",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff,.TIF,.TIFF",
}


def rio_env():
    """rasterio Env preconfigured for remote COG access."""
    import rasterio

    return rasterio.Env(**GDAL_ENV)


def sha256_file(path: str, chunk_size: int = 1 << 20) -> str:
    """Real SHA-256 of a file on disk."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def read_onto_grid(
    href: str,
    grid,
    resampling: str = "bilinear",
    dtype: Optional[str] = None,
    fill_value: float = 0,
) -> np.ndarray:
    """
    Read a single remote band and reproject/resample it onto the canonical grid.

    A WarpedVRT is what makes this both correct and cheap: GDAL computes the
    source window that corresponds to the AOI and fetches only those COG tiles,
    so a 20 m band and a 10 m band, in two different UTM zones, both come back
    as the same 2443x2432 array with identical georeferencing.
    """
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT

    method = getattr(Resampling, resampling)

    with rio_env():
        with rasterio.open(href) as src:
            with WarpedVRT(
                src,
                crs=grid.crs,
                transform=grid.transform,
                width=grid.width,
                height=grid.height,
                resampling=method,
                src_nodata=src.nodata,
                nodata=fill_value,
            ) as vrt:
                data = vrt.read(1)

    if dtype is not None and data.dtype != np.dtype(dtype):
        data = data.astype(dtype)
    return data


def read_stack_onto_grid(
    hrefs: Sequence[Tuple[str, str]],
    grid,
    resampling_per_band: Optional[Dict[str, str]] = None,
    dtype: str = "uint16",
) -> Tuple[np.ndarray, List[str]]:
    """
    Read several bands onto the canonical grid and stack them band-first.

    `hrefs` is a sequence of (band_name, url). Categorical bands such as SCL must
    be read with nearest-neighbour resampling -- interpolating a class code
    produces class values that do not exist, which would silently corrupt the
    cloud mask.
    """
    resampling_per_band = resampling_per_band or {}
    layers: List[np.ndarray] = []
    names: List[str] = []

    for band_name, href in hrefs:
        method = resampling_per_band.get(band_name, "bilinear")
        arr = read_onto_grid(href, grid, resampling=method)
        layers.append(arr.astype(dtype))
        names.append(band_name)

    return np.stack(layers, axis=0), names


def write_cog(
    path: str,
    data: np.ndarray,
    grid,
    band_names: Optional[Iterable[str]] = None,
    dtype: Optional[str] = None,
    nodata: Optional[float] = None,
    tags: Optional[Dict[str, str]] = None,
    compress: str = "DEFLATE",
) -> str:
    """
    Write a band-first array to a Cloud-Optimized GeoTIFF on the canonical grid.

    Returns the path written.
    """
    import rasterio
    from rasterio.shutil import copy as rio_copy

    if data.ndim == 2:
        data = data[np.newaxis, ...]
    count = data.shape[0]
    dtype = dtype or str(data.dtype)

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    profile = {
        "driver": "GTiff",
        "height": grid.height,
        "width": grid.width,
        "count": count,
        "dtype": dtype,
        "crs": grid.crs,
        "transform": grid.transform,
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
        "compress": compress,
        "predictor": 2 if dtype.startswith(("int", "uint")) else 3,
        "BIGTIFF": "IF_SAFER",
    }
    if nodata is not None:
        profile["nodata"] = nodata

    tmp_path = path + ".tmp.tif"
    with rasterio.open(tmp_path, "w", **profile) as dst:
        dst.write(data.astype(dtype))
        if band_names:
            for idx, name in enumerate(band_names, start=1):
                dst.set_band_description(idx, name)
        if tags:
            dst.update_tags(**{k: str(v) for k, v in tags.items()})
        dst.build_overviews([2, 4, 8, 16], rasterio.enums.Resampling.average)

    # Rewrite through the COG driver so the overviews and layout are actually
    # COG-conformant rather than just a tiled GeoTIFF that happens to have them.
    with rio_env():
        rio_copy(
            tmp_path,
            path,
            driver="COG",
            compress=compress,
            overview_resampling="average",
            blocksize=512,
            BIGTIFF="IF_SAFER",
        )
    os.remove(tmp_path)
    return path


def assert_on_grid(path: str, grid) -> None:
    """
    Fail loudly if a raster is not on the canonical grid.

    This is the check that keeps the PRD's "identical pixel centres" claim
    honest. It runs after every write and at the start of every stage that
    compares optical against SAR.
    """
    import rasterio

    with rasterio.open(path) as src:
        if not grid.matches(src.transform, src.width, src.height):
            raise ValueError(
                "%s is not on the canonical grid\n"
                "  expected %dx%d @ %s transform=%s\n"
                "  found    %dx%d @ %s transform=%s"
                % (
                    path,
                    grid.width,
                    grid.height,
                    grid.crs,
                    tuple(grid.transform)[:6],
                    src.width,
                    src.height,
                    src.crs,
                    tuple(src.transform)[:6],
                )
            )

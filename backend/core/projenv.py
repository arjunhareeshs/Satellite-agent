"""
Pin PROJ to the PROJ database that ships with our own wheels.

Importing this module has a side effect, on purpose, and it must happen before
rasterio or pyproj initialize their CRS machinery.

The problem it solves: PROJ resolves its database through the PROJ_LIB /
PROJ_DATA environment variables, and any other GDAL-linked software on the
machine may set them system-wide. On this development box PostgreSQL/PostGIS
sets:

    PROJ_LIB = C:\\Program Files\\PostgreSQL\\18\\share\\contrib\\postgis-3.6\\proj

which carries a proj.db with DATABASE.LAYOUT.VERSION.MINOR = 2, while the PROJ
built into the rasterio wheel expects >= 4. The result is that every reprojection
fails with "The EPSG code is unknown" -- a confusing error, because EPSG:32643 is
about as well known as a CRS gets, and the real fault is a shadowed database.

QGIS, ArcGIS, OSGeo4W and a conda base environment all cause the same collision,
so a machine that works today can break when unrelated software is installed.
Rather than asking anyone to edit their system environment, we point PROJ at the
data directory inside this virtualenv.
"""

from __future__ import annotations

import os
from typing import List, Optional

_ORIGINAL_PROJ_LIB = os.environ.get("PROJ_LIB")
_ORIGINAL_PROJ_DATA = os.environ.get("PROJ_DATA")

_applied: Optional[str] = None


def _candidate_dirs() -> List[str]:
    """PROJ data directories shipped inside this environment, best first."""
    candidates: List[str] = []

    try:
        import rasterio

        candidates.append(os.path.join(os.path.dirname(rasterio.__file__), "proj_data"))
    except ImportError:
        pass

    try:
        import pyproj

        candidates.append(
            os.path.join(os.path.dirname(pyproj.__file__), "proj_dir", "share", "proj")
        )
    except ImportError:
        pass

    return candidates


def ensure_proj_data() -> Optional[str]:
    """
    Point PROJ_LIB / PROJ_DATA at a bundled proj.db.

    Returns the directory applied, or None when no bundled database was found
    (in which case whatever the system provides is left alone).
    """
    global _applied
    if _applied is not None:
        return _applied

    current = os.environ.get("PROJ_DATA") or os.environ.get("PROJ_LIB")
    if current and os.path.exists(os.path.join(current, "proj.db")):
        # Only trust the inherited setting when it lives inside this environment;
        # an external one is exactly the case that breaks us.
        venv_root = os.path.dirname(os.path.dirname(os.path.abspath(os.sys.prefix)))
        if os.path.abspath(current).startswith(os.path.abspath(os.sys.prefix)) or \
           os.path.abspath(current).startswith(venv_root):
            _applied = current
            return _applied

    for candidate in _candidate_dirs():
        if os.path.exists(os.path.join(candidate, "proj.db")):
            os.environ["PROJ_LIB"] = candidate
            os.environ["PROJ_DATA"] = candidate
            # pyproj caches its data directory at import, so tell it explicitly
            # if it is already loaded.
            try:
                import pyproj

                pyproj.datadir.set_data_dir(
                    os.path.join(os.path.dirname(pyproj.__file__), "proj_dir", "share", "proj")
                )
            except Exception:  # noqa: BLE001
                pass
            _applied = candidate
            return _applied

    return None


def status() -> dict:
    """Reported by /api/v1/health so a shadowed PROJ is visible, not mysterious."""
    return {
        "applied": _applied,
        "inherited_proj_lib": _ORIGINAL_PROJ_LIB,
        "inherited_proj_data": _ORIGINAL_PROJ_DATA,
        "overridden": bool(_applied and _applied != _ORIGINAL_PROJ_LIB),
    }


# Applied at import. This module exists to be imported for its side effect.
ensure_proj_data()

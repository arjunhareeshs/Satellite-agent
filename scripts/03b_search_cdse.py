"""
03b — Cross-reference each selected scene to its Copernicus Data Space product ID.

The pixels come from AWS (Sentinel-2) and Planetary Computer (Sentinel-1)
because those are free, need no account, and serve range-readable COGs. But the
authoritative source of Copernicus data is the Copernicus Data Space Ecosystem,
and a provenance record for a defence evaluation should cite it.

This script resolves every scene in the manifests to its CDSE product ID and
canonical product name via the CDSE OData catalogue -- which is queryable
without credentials -- and writes them back into the manifests so that
provenance.json carries the Copernicus identifier alongside the mirror URL.

It is advisory: a scene that cannot be resolved is reported and left alone. The
pipeline does not depend on it.

Usage:
    python scripts/03b_search_cdse.py
    python scripts/03b_search_cdse.py --sensor s2
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.parse

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.acquisition.stac import CDSE_ODATA_URL  # noqa: E402
from backend.core.grid import load_aoi_config  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFESTS = {
    "s2": (os.path.join(ROOT, "data", "metadata", "s2_scenes.json"), "SENTINEL-2"),
    "s1": (os.path.join(ROOT, "data", "metadata", "s1_scenes.json"), "SENTINEL-1"),
}

# CDSE product types matching what we actually consume.
PRODUCT_TYPE_HINT = {"SENTINEL-2": "MSIL2A", "SENTINEL-1": "GRDH"}


def _aoi_wkt(cfg: dict) -> str:
    b = cfg["bounds"]
    return (
        "POLYGON((%(x1)f %(y1)f,%(x2)f %(y1)f,%(x2)f %(y2)f,%(x1)f %(y2)f,%(x1)f %(y1)f))"
        % {"x1": b["min_lon"], "y1": b["min_lat"], "x2": b["max_lon"], "y2": b["max_lat"]}
    )


def resolve_scene(client: httpx.Client, collection: str, scene: dict, aoi_wkt: str):
    """
    Find the CDSE product whose sensing time matches this scene.

    Matching on a +/- 2 minute sensing window plus AOI intersection is enough to
    be unambiguous: two products of the same collection cannot cover the same
    AOI at the same instant.
    """
    sensing = dt.datetime.fromisoformat(scene["datetime"].replace("Z", "+00:00"))
    lo = (sensing - dt.timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    hi = (sensing + dt.timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    filt = (
        "Collection/Name eq '%s' "
        "and OData.CSC.Intersects(area=geography'SRID=4326;%s') "
        "and ContentDate/Start gt %s and ContentDate/Start lt %s"
    ) % (collection, aoi_wkt, lo, hi)

    url = "%s/Products?%s" % (
        CDSE_ODATA_URL,
        urllib.parse.urlencode({"$filter": filt, "$top": 20}),
    )

    resp = client.get(url, timeout=45.0)
    resp.raise_for_status()
    products = resp.json().get("value", [])

    hint = PRODUCT_TYPE_HINT.get(collection, "")
    for product in products:
        if hint in product.get("Name", ""):
            return product
    return products[0] if products else None


def main() -> int:
    ap = argparse.ArgumentParser(description="Cross-reference scenes to CDSE product IDs")
    ap.add_argument("--sensor", choices=["s1", "s2", "both"], default="both")
    args = ap.parse_args()

    cfg = load_aoi_config()
    aoi_wkt = _aoi_wkt(cfg)
    targets = ["s2", "s1"] if args.sensor == "both" else [args.sensor]

    print("TRINETRA — Copernicus Data Space provenance cross-reference")
    print("  endpoint    : %s" % CDSE_ODATA_URL)
    print("  note        : advisory only; pixels come from the AWS / MPC mirrors")
    print()

    overall_ok = True

    with httpx.Client(follow_redirects=True) as client:
        for key in targets:
            path, collection = MANIFESTS[key]
            if not os.path.exists(path):
                print("  %s: manifest not found, skipping (%s)"
                      % (key, os.path.relpath(path, ROOT)))
                continue

            with open(path, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)

            scenes = manifest["scenes"]
            print("  %s: resolving %d scenes against %s" % (key, len(scenes), collection))

            resolved = unresolved = 0
            for i, scene in enumerate(scenes, start=1):
                try:
                    product = resolve_scene(client, collection, scene, aoi_wkt)
                except Exception as exc:  # noqa: BLE001
                    print("    [%3d] error %s: %s" % (i, scene["stac_id"][:40], exc))
                    unresolved += 1
                    continue

                if product is None:
                    unresolved += 1
                    continue

                scene["cdse_product_id"] = product.get("Id")
                scene["cdse_product_name"] = product.get("Name")
                resolved += 1
                if resolved <= 3:
                    print("    [%3d] %s\n          -> %s"
                          % (i, scene["stac_id"][:52], product.get("Name", "")[:70]))

            manifest["cdse_cross_reference"] = {
                "endpoint": CDSE_ODATA_URL,
                "resolved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "resolved": resolved,
                "unresolved": unresolved,
            }

            with open(path, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, indent=2)

            print("    resolved %d / %d  (unresolved %d)"
                  % (resolved, len(scenes), unresolved))
            print("    updated %s" % os.path.relpath(path, ROOT))
            print()

            if resolved == 0 and scenes:
                overall_ok = False

    if not overall_ok:
        print("WARNING: nothing resolved. CDSE may be unreachable; provenance will")
        print("         carry the mirror URL only.")
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

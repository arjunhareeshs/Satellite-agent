"""
05 — Search for real Sentinel-1 RTC scenes over the AOI.

Replaces the previous version, which fabricated 24 scene IDs on the 19th of
every month -- a cadence that is impossible for a 12-day repeat orbit -- and
also pretended to be the (never-written) 06_download_sentinel1.py.

Source is Microsoft Planetary Computer, collection `sentinel-1-rtc`. RTC means
ESA's orbit-file / thermal-noise / calibration / terrain-correction chain has
already been applied, so PRD section 4.5's SNAP pipeline is satisfied by the
product rather than reimplemented locally. Assets are signed with an anonymous
SAS token.

Orbit discipline: SAR backscatter depends on viewing geometry, so a trajectory
assembled from mixed relative orbits carries a step change that has nothing to
do with the ground. This script reports the orbit distribution and keeps a
single track.

Usage:
    python scripts/05_search_sentinel1.py
    python scripts/05_search_sentinel1.py --relative-orbit 63
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.acquisition.stac import search_sentinel1  # noqa: E402
from backend.core.grid import load_aoi_config  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(ROOT, "data", "metadata", "s1_scenes.json")


def main() -> int:
    cfg = load_aoi_config()
    sel = cfg.get("selection", {})
    window = cfg["temporal_window"]

    ap = argparse.ArgumentParser(description="Search Sentinel-1 RTC over the AOI")
    ap.add_argument("--start", default=window["start"])
    ap.add_argument("--end", default=window["end"])
    ap.add_argument(
        "--min-intersection", type=float, default=sel.get("min_aoi_intersection", 0.6)
    )
    ap.add_argument(
        "--max-per-month", type=int, default=sel.get("max_scenes_per_month", 3)
    )
    ap.add_argument(
        "--relative-orbit",
        type=int,
        default=None,
        help="Pin a specific track. Default: the best-covered one.",
    )
    ap.add_argument("--out", default=OUT_PATH)
    args = ap.parse_args()

    b = cfg["bounds"]
    bbox = [b["min_lon"], b["min_lat"], b["max_lon"], b["max_lat"]]

    print("TRINETRA — Sentinel-1 RTC discovery")
    print("  provider    : Microsoft Planetary Computer (sentinel-1-rtc)")
    print("  note        : RTC is already calibrated + terrain-corrected")
    print("  bbox        : %s" % bbox)
    print("  window      : %s -> %s" % (args.start, args.end))
    print("  searching...")

    manifest = search_sentinel1(
        aoi_bbox=bbox,
        start=args.start,
        end=args.end,
        min_intersection=args.min_intersection,
        max_per_month=args.max_per_month,
        relative_orbit=args.relative_orbit,
    )

    if manifest["total"] == 0:
        print("  FAIL: no scenes matched. Check connectivity and filters.", file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    scenes = manifest["scenes"]
    years = sorted({s["datetime"][:4] for s in scenes})

    print("  candidates  : %d passed coverage filter" % manifest["candidates_found"])
    print("  orbits seen : %s" % manifest["orbit_distribution"])
    print("  track kept  : relative orbit %s (%s)"
          % (manifest["filters"]["relative_orbit"], scenes[0].get("orbit_state")))
    print("  selected    : %d after monthly stratification" % manifest["total"])
    print("  date range  : %s -> %s" % (scenes[0]["datetime"][:10], scenes[-1]["datetime"][:10]))
    print("  years       : %s" % ", ".join(years))
    print("  source CRS  : %s (warped to the canonical grid on download)"
          % sorted({str(s.get("epsg")) for s in scenes}))

    gaps = manifest["coverage_gaps"]
    if gaps:
        print("  gaps        : %d month(s) with no usable scene: %s"
              % (len(gaps), ", ".join(gaps)))
    else:
        print("  gaps        : none — every month in the window has coverage")

    print("  example     : %s" % scenes[0]["stac_id"])
    print("  wrote       : %s" % os.path.relpath(args.out, ROOT))
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

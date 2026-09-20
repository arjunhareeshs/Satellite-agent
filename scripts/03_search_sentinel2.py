"""
03 — Search for real Sentinel-2 L2A scenes over the AOI.

Replaces the previous version, which generated scene IDs in a for-loop with a
two-valued cloud cover and never touched the network.

This queries Element84 Earth Search (AWS open data, no account needed), filters
on cloud cover and AOI coverage, stratifies by month so the monsoon is not
silently dropped, and writes a real download manifest. Metadata only -- no
pixels are fetched here (PRD section 4.3: search before download).

Usage:
    python scripts/03_search_sentinel2.py
    python scripts/03_search_sentinel2.py --start 2024-01-01 --end 2024-12-31
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.acquisition.stac import search_sentinel2  # noqa: E402
from backend.core.grid import load_aoi_config  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(ROOT, "data", "metadata", "s2_scenes.json")


def main() -> int:
    cfg = load_aoi_config()
    sel = cfg.get("selection", {})
    window = cfg["temporal_window"]

    ap = argparse.ArgumentParser(description="Search Sentinel-2 L2A over the AOI")
    ap.add_argument("--start", default=window["start"])
    ap.add_argument("--end", default=window["end"])
    ap.add_argument("--max-cloud", type=float, default=sel.get("max_cloud_cover", 30.0))
    ap.add_argument(
        "--min-intersection", type=float, default=sel.get("min_aoi_intersection", 0.6)
    )
    ap.add_argument(
        "--max-per-month", type=int, default=sel.get("max_scenes_per_month", 3)
    )
    ap.add_argument("--out", default=OUT_PATH)
    args = ap.parse_args()

    b = cfg["bounds"]
    bbox = [b["min_lon"], b["min_lat"], b["max_lon"], b["max_lat"]]

    print("TRINETRA — Sentinel-2 L2A discovery")
    print("  provider    : Element84 Earth Search (AWS open data, no auth)")
    print("  bbox        : %s" % bbox)
    print("  window      : %s -> %s" % (args.start, args.end))
    print("  filters     : cloud < %g%%, AOI coverage > %g, max %d/month"
          % (args.max_cloud, args.min_intersection, args.max_per_month))
    print("  searching...")

    manifest = search_sentinel2(
        aoi_bbox=bbox,
        start=args.start,
        end=args.end,
        max_cloud=args.max_cloud,
        min_intersection=args.min_intersection,
        max_per_month=args.max_per_month,
    )

    if manifest["total"] == 0:
        print("  FAIL: no scenes matched. Check connectivity and filters.", file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    scenes = manifest["scenes"]
    clouds = [s["cloud_cover"] for s in scenes]
    years = sorted({s["datetime"][:4] for s in scenes})

    print("  candidates  : %d passed cloud + coverage filters" % manifest["candidates_found"])
    print("  selected    : %d after monthly stratification" % manifest["total"])
    print("  date range  : %s -> %s" % (scenes[0]["datetime"][:10], scenes[-1]["datetime"][:10]))
    print("  years       : %s" % ", ".join(years))
    print("  cloud cover : min %.1f%%  median %.1f%%  max %.1f%%"
          % (min(clouds), sorted(clouds)[len(clouds) // 2], max(clouds)))
    print("  tiles       : %s" % sorted({s["mgrs_tile"] for s in scenes if s["mgrs_tile"]}))

    gaps = manifest["coverage_gaps"]
    if gaps:
        # Not a failure. PRD section 4.3 asks for gaps to be recorded, because a
        # month with no usable observation is itself a result for the evaluation
        # report rather than something to paper over.
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

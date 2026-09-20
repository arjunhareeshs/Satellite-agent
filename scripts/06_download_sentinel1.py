"""
06 — Download the selected Sentinel-1 RTC scenes.

This script never existed. Its work was previously discharged by a comment in
05_search_sentinel1.py that wrote provenance.json files for five empty
directories.

Performs real windowed reads of VV and VH from the remote RTC COGs, warps each
from its native UTM zone onto the canonical grid (the step that makes optical
and SAR share pixel centres), converts linear gamma-nought to decibels, and
writes a 2-band float32 COG with real provenance.

Usage:
    python scripts/06_download_sentinel1.py
    python scripts/06_download_sentinel1.py --limit 5        # smoke test
    python scripts/06_download_sentinel1.py --force
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import time as _time_module

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.acquisition.download import download_s1_scene  # noqa: E402
from backend.core.grid import get_grid  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "data", "metadata", "s1_scenes.json")
OUT_ROOT = os.path.join(ROOT, "data", "raw", "sentinel1")


def main() -> int:
    ap = argparse.ArgumentParser(description="Download Sentinel-1 RTC AOI clips")
    ap.add_argument("--manifest", default=MANIFEST)
    ap.add_argument("--out", default=OUT_ROOT)
    ap.add_argument("--limit", type=int, default=None, help="Only the first N scenes")
    ap.add_argument("--force", action="store_true", help="Re-download cached scenes")
    ap.add_argument("--no-retry", action="store_true",
                    help="Do not automatically retry scenes that fail once")
    args = ap.parse_args()

    if not os.path.exists(args.manifest):
        print("FAIL: %s not found. Run scripts/05_search_sentinel1.py first."
              % os.path.relpath(args.manifest, ROOT), file=sys.stderr)
        return 1

    with open(args.manifest, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)

    scenes = manifest["scenes"]
    if args.limit:
        scenes = scenes[: args.limit]

    grid = get_grid()
    os.makedirs(args.out, exist_ok=True)

    print("TRINETRA — Sentinel-1 RTC download")
    print("  scenes      : %d (relative orbit %s)"
          % (len(scenes), manifest.get("filters", {}).get("relative_orbit")))
    print("  grid        : %s @ %g m, %d x %d px"
          % (grid.crs, grid.resolution_m, grid.width, grid.height))
    print("  bands       : VV_db VH_db")
    print("  destination : %s" % os.path.relpath(args.out, ROOT))
    print()

    # SAS tokens are signed lazily, one asset at a time, inside
    # download_s1_scene -- not here in bulk. A previous version signed every
    # asset URL for the whole batch up front in one tight loop; bulk-signing
    # ~270 URLs in a few seconds tripped Planetary Computer's per-IP rate
    # limit for anonymous SAS issuance, and every scene after the ninth in that
    # run failed with HTTP 403 for the rest of the batch. Signing per-asset,
    # spread across the run's actual download cadence, stays under the limit.

    downloaded = cached = failed = 0
    total_bytes = 0
    failures = []
    t_start = time.perf_counter()

    for i, scene in enumerate(scenes, start=1):
        label = "%s  %s" % (scene["stac_id"][:52], scene["datetime"][:10])
        try:
            t0 = time.perf_counter()
            result = download_s1_scene(scene, grid, args.out, force=args.force)
            elapsed = time.perf_counter() - t0

            if result["status"] == "cached":
                cached += 1
                print("  [%3d/%3d] cached      %s" % (i, len(scenes), label))
            else:
                downloaded += 1
                total_bytes += result["size_bytes"]
                print("  [%3d/%3d] ok  %5.1fs  %s  %5.1f MB  valid %.0f%%"
                      % (i, len(scenes), elapsed, label,
                         result["size_bytes"] / 1e6, result["valid_fraction"] * 100))
        except Exception as exc:  # noqa: BLE001 - report and continue
            failed += 1
            failures.append((scene["stac_id"], str(exc)))
            print("  [%3d/%3d] FAIL        %s\n            %s"
                  % (i, len(scenes), label, exc), file=sys.stderr)

    wall = time.perf_counter() - t_start
    print()
    print("  downloaded  : %d" % downloaded)
    print("  cached      : %d" % cached)
    print("  failed      : %d" % failed)
    print("  new bytes   : %.2f GB" % (total_bytes / 1e9))
    print("  wall clock  : %.1f s" % wall)

    # See scripts/04_download_sentinel2.py for why this retry pass exists: a
    # multi-hour archive build over a residential connection sees the
    # occasional DNS hiccup unrelated to the data itself.
    if failures and not args.no_retry:
        print("\n  retrying %d failed scene(s) after a network pause..." % len(failures))
        time.sleep(15)
        by_id = {sc["stac_id"]: sc for sc in scenes}
        retry_failures = []
        for stac_id, _err in failures:
            scene = by_id.get(stac_id)
            if scene is None:
                retry_failures.append((stac_id, "scene not found for retry"))
                continue
            try:
                result = download_s1_scene(scene, grid, args.out, force=args.force)
                if result["status"] != "cached":
                    downloaded += 1
                    total_bytes += result["size_bytes"]
                print("    retry ok    %s" % stac_id)
            except Exception as exc:  # noqa: BLE001
                retry_failures.append((stac_id, str(exc)))
                print("    retry FAIL  %s: %s" % (stac_id, exc), file=sys.stderr)
        failed = len(retry_failures)
        failures = retry_failures

    if failures:
        print("\n  failures:")
        for stac_id, err in failures:
            print("    %s: %s" % (stac_id, err))
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

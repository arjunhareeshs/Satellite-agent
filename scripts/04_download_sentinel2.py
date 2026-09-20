"""
04 — Download the selected Sentinel-2 L2A scenes.

Replaces the previous version, which created five empty directories and wrote
the SHA-256 of the empty string as each scene's checksum, then printed
"downloads verified with cryptographic checksums."

This performs real windowed reads of the six Prithvi bands plus SCL from the
remote COGs, warps each onto the canonical grid, writes a 7-band COG, and
records a provenance.json whose checksum is computed from the bytes on disk.

Resume-capable: a scene whose recorded checksum still matches its COG is
skipped, so an interrupted run continues rather than restarting.

Usage:
    python scripts/04_download_sentinel2.py
    python scripts/04_download_sentinel2.py --limit 5        # smoke test
    python scripts/04_download_sentinel2.py --force
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import time as _time_module

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.acquisition.download import download_s2_scene  # noqa: E402
from backend.core.grid import get_grid  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "data", "metadata", "s2_scenes.json")
OUT_ROOT = os.path.join(ROOT, "data", "raw", "sentinel2")


def main() -> int:
    ap = argparse.ArgumentParser(description="Download Sentinel-2 AOI clips")
    ap.add_argument("--manifest", default=MANIFEST)
    ap.add_argument("--out", default=OUT_ROOT)
    ap.add_argument("--limit", type=int, default=None, help="Only the first N scenes")
    ap.add_argument("--force", action="store_true", help="Re-download cached scenes")
    ap.add_argument("--no-retry", action="store_true",
                    help="Do not automatically retry scenes that fail once")
    args = ap.parse_args()

    if not os.path.exists(args.manifest):
        print("FAIL: %s not found. Run scripts/03_search_sentinel2.py first."
              % os.path.relpath(args.manifest, ROOT), file=sys.stderr)
        return 1

    with open(args.manifest, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)

    scenes = manifest["scenes"]
    if args.limit:
        scenes = scenes[: args.limit]

    grid = get_grid()
    os.makedirs(args.out, exist_ok=True)

    print("TRINETRA — Sentinel-2 download")
    print("  scenes      : %d" % len(scenes))
    print("  grid        : %s @ %g m, %d x %d px"
          % (grid.crs, grid.resolution_m, grid.width, grid.height))
    print("  bands       : B02 B03 B04 B8A B11 B12 + SCL")
    print("  destination : %s" % os.path.relpath(args.out, ROOT))
    print()

    downloaded = cached = failed = 0
    total_bytes = 0
    failures = []
    t_start = time.perf_counter()

    for i, scene in enumerate(scenes, start=1):
        label = "%s  %s" % (scene["stac_id"], scene["datetime"][:10])
        try:
            t0 = time.perf_counter()
            result = download_s2_scene(scene, grid, args.out, force=args.force)
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

    # A multi-hour archive build over a residential connection will see the
    # occasional DNS hiccup or connection reset that has nothing to do with the
    # data itself -- confirmed on this run ("Could not resolve host" for a
    # handful of scenes while curl to the same host succeeded seconds later).
    # One retry pass over just the scenes that failed, after a short pause for
    # the transient condition to clear, avoids turning that into a manual
    # re-run for what is usually a fully healthy archive.
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
                result = download_s2_scene(scene, grid, args.out, force=args.force)
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
        # A partial archive is a real state, not a success. Exit non-zero so the
        # Makefile chain stops rather than building indices over missing scenes.
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

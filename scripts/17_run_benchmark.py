"""
17 — Measure the archive and write a real build_report.json.

Replaces a version whose entire output was a 60-line dict of literals --
`"area_km2": 538.2` (the wrong, uncorrected value), `"entities_indexed":
1420` (traced to a print statement in the old 10_extract_entities.py),
`"change_f1": 0.94` for an ablation that was never run, and `"offline_verified":
True` asserted rather than checked. `du -sh data` on that build showed 23 KB
on disk against a claimed 15.01 GB.

Every field below is either read from an artifact a real pipeline stage wrote,
or measured directly in this script. Where a real number cannot yet be
produced -- the false-alarm ablation needs a labelled dataset and multiple
pipeline runs, which is out of scope for a single benchmark pass -- the field
says so explicitly instead of inventing one.

Usage:
    python scripts/17_run_benchmark.py
    python scripts/17_run_benchmark.py --queries 20   # latency sample size
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
METADATA_DIR = os.path.join(ROOT, "data", "metadata")


def _read_json(filename: str) -> Optional[dict]:
    path = os.path.join(METADATA_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _dir_size_bytes(path: str) -> int:
    total = 0
    if not os.path.isdir(path):
        return 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            fp = os.path.join(dirpath, name)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def _human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return "%.1f %s" % (size, unit)
        size /= 1024
    return "%.1f TB" % size


def _count_completed_downloads(sensor_dir: str) -> int:
    """
    A scene counts as downloaded when its `*_stack.tif` exists, not when its
    directory exists. `download_s2_scene`/`download_s1_scene` both call
    `os.makedirs(scene_dir, exist_ok=True)` before attempting the read, so a
    scene that failed mid-download (a transient DNS error, an expired SAS
    token before the signing fix) still leaves a directory behind with no
    COG in it. Counting directories over-reported every scene this pipeline
    had ever *attempted*, downloaded or not.
    """
    if not os.path.isdir(sensor_dir):
        return 0
    count = 0
    for name in os.listdir(sensor_dir):
        scene_dir = os.path.join(sensor_dir, name)
        if not os.path.isdir(scene_dir):
            continue
        if any(fn.endswith("_stack.tif") for fn in os.listdir(scene_dir)):
            count += 1
    return count


def measure_scenes() -> Dict[str, Any]:
    s2 = _read_json("s2_scenes.json") or {}
    s1 = _read_json("s1_scenes.json") or {}
    s2_downloaded = _count_completed_downloads(os.path.join(ROOT, "data", "raw", "sentinel2"))
    s1_downloaded = _count_completed_downloads(os.path.join(ROOT, "data", "raw", "sentinel1"))
    return {
        "sentinel2_searched": s2.get("total", 0),
        "sentinel2_downloaded": s2_downloaded,
        "sentinel1_searched": s1.get("total", 0),
        "sentinel1_downloaded": s1_downloaded,
        "total_downloaded": s2_downloaded + s1_downloaded,
    }


def measure_storage() -> Dict[str, Any]:
    raw = _dir_size_bytes(os.path.join(ROOT, "data", "raw"))
    processed = _dir_size_bytes(os.path.join(ROOT, "data", "processed"))
    models = _dir_size_bytes(os.path.join(ROOT, "models"))
    metadata = _dir_size_bytes(METADATA_DIR)
    return {
        "raw_bytes": raw,
        "processed_bytes": processed,
        "models_bytes": models,
        "metadata_bytes": metadata,
        "total_bytes": raw + processed + models + metadata,
        "raw_human": _human_bytes(raw),
        "processed_human": _human_bytes(processed),
        "models_human": _human_bytes(models),
        "total_human": _human_bytes(raw + processed + models + metadata),
    }


def measure_entities() -> Dict[str, Any]:
    from backend.engines.spatial import spatial_engine

    entities_doc = _read_json("entities.json")
    if entities_doc:
        return {
            "total": entities_doc.get("total_entities", 0),
            "by_type": entities_doc.get("by_type", {}),
            "source": "entities.json",
        }
    spatial_engine.init_pool()
    count = spatial_engine.status()["entities_loaded"]
    return {"total": count, "by_type": {}, "source": "spatial_engine (live)"}


def measure_query_latency(n_queries: int) -> Dict[str, Any]:
    """
    Real p50/p95 over actual /search executions against whatever is currently
    indexed. Previously these six numbers (nl_parse through total_p95) were
    literals with no query ever run.
    """
    from backend.core.executor import pipeline_executor
    from backend.core.query_parser import query_parser

    sample_queries = [
        "Find new structures within 500 m of the river",
        "Locate construction near roads in the last year",
        "Show vegetation clearance close to water",
    ]

    latencies_ms: List[float] = []
    for i in range(n_queries):
        query_text = sample_queries[i % len(sample_queries)]
        t0 = time.perf_counter()
        plan = query_parser.parse_to_plan(query_text)
        pipeline_executor.execute_plan(plan, explain_top_n=3)
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)

    latencies_ms.sort()

    def percentile(p: float) -> float:
        if not latencies_ms:
            return 0.0
        idx = min(len(latencies_ms) - 1, int(round(p / 100.0 * (len(latencies_ms) - 1))))
        return round(latencies_ms[idx], 1)

    return {
        "n_queries": n_queries,
        "p50_ms": percentile(50),
        "p95_ms": percentile(95),
        "min_ms": round(min(latencies_ms), 1) if latencies_ms else 0.0,
        "max_ms": round(max(latencies_ms), 1) if latencies_ms else 0.0,
    }


def measure_offline_compliance() -> Dict[str, Any]:
    from backend.core.manifest import verify_manifest
    from backend.models.vlm import provider_status

    manifest_result = verify_manifest()
    vlm = provider_status()
    return {
        "manifest_ok": manifest_result.ok,
        "manifest_message": manifest_result.message,
        "active_vlm_provider": vlm["active"],
        "offline_compliant": manifest_result.ok and vlm["active"] != "groq",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure the archive and write build_report.json")
    ap.add_argument("--queries", type=int, default=10, help="Sample size for latency measurement")
    ap.add_argument("--out", default=os.path.join(METADATA_DIR, "build_report.json"))
    args = ap.parse_args()

    print("TRINETRA — benchmark")
    t_start = time.perf_counter()

    aoi_summary = _read_json("aoi_summary.json") or {}
    scenes = measure_scenes()
    storage = measure_storage()
    entities = measure_entities()

    print("  measuring query latency over %d sample queries..." % args.queries)
    latency = measure_query_latency(args.queries)

    compliance = measure_offline_compliance()

    report = {
        "evaluation_name": "SIH26227 Benchmark Submission",
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "aoi_name": aoi_summary.get("name"),
        "bounds": aoi_summary.get("bounds"),
        "area_km2": aoi_summary.get("area_km2"),
        "scenes": scenes,
        "entities": entities,
        "storage_footprint": storage,
        "query_latency_ms": latency,
        "offline_compliance": compliance,
        # Requires a labelled dataset and multiple full pipeline runs with
        # gates 1-5 progressively enabled -- not something one benchmark pass
        # produces. Left explicitly absent rather than filled with the
        # previous literal 0.42 -> 0.94 progression, which no run ever
        # measured.
        "false_alarm_cascade_ablation": None,
        "false_alarm_cascade_ablation_note": (
            "Not measured by this script. Requires eval/change_labels.json "
            "coverage across the real archive and a run per gate "
            "configuration; see eval/run_eval.py for the single-configuration "
            "metrics that are measured."
        ),
        "benchmark_wall_clock_sec": round(time.perf_counter() - t_start, 2),
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    print()
    print("  scenes      : %d/%d S2 downloaded, %d/%d S1 downloaded"
          % (scenes["sentinel2_downloaded"], scenes["sentinel2_searched"],
             scenes["sentinel1_downloaded"], scenes["sentinel1_searched"]))
    print("  entities    : %d (%s)" % (entities["total"], entities["source"]))
    print("  storage     : %s (raw %s, processed %s, models %s)"
          % (storage["total_human"], storage["raw_human"], storage["processed_human"],
             storage["models_human"]))
    print("  latency     : p50 %.1f ms, p95 %.1f ms (n=%d)"
          % (latency["p50_ms"], latency["p95_ms"], latency["n_queries"]))
    print("  offline     : %s (%s)" % (compliance["offline_compliant"], compliance["manifest_message"]))
    print("  wrote       : %s" % os.path.relpath(args.out, ROOT))
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
TRINETRA quantitative evaluation suite.

The previous version of this file had two defects that made every number it
printed meaningless as a measurement:

  1. Line 84 assigned the ground truth as the prediction for every entity
     except one: `pred_dt = datetime(2024, 8, 21) if item["entity_id"] ==
     "BLDG_004281" else true_dt`. The temporal model was never invoked for
     this metric; the "median error" was structurally forced toward zero.
  2. Every result line printed `[OK]` unconditionally, with no assertion and
     no non-zero exit -- the script could not fail regardless of what the
     numbers were, including the negative-control line, which printed "100%
     (Floodplain suppressed)" as a literal string without ever loading
     `eval/negative_controls/floodplain.json`.

This version calls `temporal_engine.estimate_break_from_history()` -- the same
CUSUM detector `CellModel.update()` runs online -- against each entity's own
recorded trajectory, actually loads and checks the negative control file, and
asserts against the PRD's stated contracts so a regression exits non-zero
instead of printing [OK] regardless.
"""

import os
import sys
import json
import math
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.core.query_parser import query_parser
from backend.core.executor import pipeline_executor
from backend.engines.temporal import temporal_engine
from scripts.seed_demo_data import seed_all

# Contracts from the PRD's Definition of Done. A run that misses one of these
# is a real failure, not a warning -- reflected in the exit code.
CONTRACT_MIN_NDCG = 0.85
CONTRACT_MIN_MAP = 0.90
CONTRACT_MAX_MEDIAN_DATE_ERROR_DAYS = 25


def compute_dcg(relevances, k=10):
    dcg = 0.0
    for i, rel in enumerate(relevances[:k], start=1):
        dcg += (2**rel - 1) / math.log2(i + 1)
    return dcg


def run_retrieval_metrics():
    with open(os.path.join("eval", "queries.json"), "r", encoding="utf-8") as f:
        queries = json.load(f)
    with open(os.path.join("eval", "relevance.json"), "r", encoding="utf-8") as f:
        relevance_map = json.load(f)

    ndcg_scores = []
    relational_map_scores = []

    for q in queries:
        qid = q["query_id"]
        qtext = q["query_text"]
        plan = query_parser.parse_to_plan(qtext)
        resp = pipeline_executor.execute_plan(plan, explain_top_n=3)

        retrieved_ids = [r.entity_id for r in resp.results]
        q_rel = relevance_map.get(qid, {})

        rels = [q_rel.get(eid, 0) for eid in retrieved_ids]
        ideal_rels = sorted(q_rel.values(), reverse=True)

        actual_dcg = compute_dcg(rels, k=10)
        ideal_dcg = compute_dcg(ideal_rels, k=10)
        ndcg = (actual_dcg / ideal_dcg) if ideal_dcg > 0 else 1.0
        ndcg_scores.append(ndcg)

        if q.get("relation") == "near_water":
            expected = q.get("expected_ids", [])
            hits = sum(1 for eid in retrieved_ids if eid in expected)
            relational_map_scores.append(hits / max(1, len(expected)))

        print("  query [%s]: '%s...' -> nDCG@10 = %.3f" % (qid, qtext[:45], ndcg))

    avg_ndcg = sum(ndcg_scores) / max(1, len(ndcg_scores))
    avg_map = sum(relational_map_scores) / max(1, len(relational_map_scores)) if relational_map_scores else 0.0
    return avg_ndcg, avg_map, len(queries)


def run_temporal_metrics():
    """
    Break-date accuracy, computed by actually running the detector.

    For each labelled entity, replay its recorded trajectory through
    `estimate_break_from_history` and compare the detector's own estimate
    against the ground truth -- rather than the ground truth against itself.
    """
    with open(os.path.join("eval", "change_labels.json"), "r", encoding="utf-8") as f:
        gt_data = json.load(f)

    date_errors = []
    undetected = []
    for item in gt_data["ground_truth"]:
        if not (item["true_change"] and item.get("true_break_date")):
            continue

        entity_id = item["entity_id"]
        trajectory = temporal_engine.get_entity_timeline(entity_id)
        if not trajectory:
            undetected.append((entity_id, "no trajectory registered"))
            continue

        result = temporal_engine.estimate_break_from_history(trajectory)
        if result is None:
            undetected.append((entity_id, "detector found no break"))
            continue

        true_dt = datetime.fromisoformat(item["true_break_date"])
        pred_dt = datetime.fromisoformat(result["estimate"])
        date_errors.append(abs((pred_dt - true_dt).days))

    median_error = sorted(date_errors)[len(date_errors) // 2] if date_errors else None
    return median_error, len(date_errors), undetected


def run_negative_controls():
    """
    Actually load and check the negative control, instead of printing a
    literal "100% (Floodplain suppressed)" that no code path could contradict.
    """
    control_dir = os.path.join("eval", "negative_controls")
    if not os.path.isdir(control_dir):
        return [], []

    passed, failed = [], []
    for filename in sorted(os.listdir(control_dir)):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(control_dir, filename)
        with open(path, "r", encoding="utf-8") as f:
            control = json.load(f)

        # A negative control passes when the recorded status says the change
        # was suppressed AND the recorded CUSUM statistic stayed under the
        # engine's own H_THRESHOLD (4.0) -- checked against the constant the
        # detector actually uses, not merely trusted from the fixture.
        from backend.engines.temporal import H_THRESHOLD

        status = control.get("status", "")
        cusum_max = control.get("cusum_max")
        ok = status == "SUPPRESSED" and cusum_max is not None and cusum_max <= H_THRESHOLD
        (passed if ok else failed).append((filename, control))

    return passed, failed


def run_evaluation() -> int:
    print("=" * 50)
    print("TRINETRA: Quantitative Evaluation Protocol")
    print("=" * 50)

    seed_all()

    avg_ndcg, avg_map, n_queries = run_retrieval_metrics()
    median_date_error, n_dated, undetected = run_temporal_metrics()
    controls_passed, controls_failed = run_negative_controls()

    print("-" * 50)
    print("Results:")

    ok = True

    ndcg_pass = avg_ndcg >= CONTRACT_MIN_NDCG
    print("  %s nDCG@10: %.3f (contract >= %.2f, over %d queries)"
          % ("[OK]" if ndcg_pass else "[FAIL]", avg_ndcg, CONTRACT_MIN_NDCG, n_queries))
    ok &= ndcg_pass

    map_pass = avg_map >= CONTRACT_MIN_MAP
    print("  %s MAP on relational queries: %.3f (contract >= %.2f)"
          % ("[OK]" if map_pass else "[FAIL]", avg_map, CONTRACT_MIN_MAP))
    ok &= map_pass

    if median_date_error is None:
        print("  [FAIL] Temporal date error: no entity produced a detected break")
        ok = False
    else:
        date_pass = median_date_error <= CONTRACT_MAX_MEDIAN_DATE_ERROR_DAYS
        print("  %s Median temporal date error: %d days over %d detected breaks "
              "(contract <= %d days)"
              % ("[OK]" if date_pass else "[FAIL]", median_date_error, n_dated,
                 CONTRACT_MAX_MEDIAN_DATE_ERROR_DAYS))
        ok &= date_pass

    for entity_id, reason in undetected:
        print("    note: %s -- %s" % (entity_id, reason))

    if not controls_passed and not controls_failed:
        print("  [WARN] No negative control files found under eval/negative_controls/")
    else:
        for filename, _ in controls_passed:
            print("  [OK] Negative control suppressed: %s" % filename)
        for filename, control in controls_failed:
            print("  [FAIL] Negative control NOT suppressed: %s (status=%s, cusum_max=%s)"
                  % (filename, control.get("status"), control.get("cusum_max")))
            ok = False

    print("=" * 50)
    print("EVALUATION %s" % ("PASSED" if ok else "FAILED"))
    print("=" * 50)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run_evaluation())

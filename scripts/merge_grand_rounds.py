#!/usr/bin/env python3
"""Merge Grand Rounds v1 results into THE_CLINIC patient files.

Reads grand_rounds_results.jsonl produced by Herm Zero's grand_rounds_harness.py
(run 2026-03-28/29 on Veron-1 / RTX 5090) and appends one exam per patient to
each patient's examination_log. Idempotent via exam_id.

Doctor is attributed to Herm Zero (the agent that actually ran the harness);
the filing/merge is done by Opus 4.6 post-hoc because Herm Zero ran out of
tokens before he could file it.
"""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

CLINIC_DIR = Path("/srv/repos/windy-pro/THE_CLINIC")
PATIENTS_DIR = CLINIC_DIR / "translation-pairs"
GR_RESULTS = Path(
    "/home/user1-gpu/Desktop/grants_folder/windy-pro/grand_rounds/grand_rounds_results.jsonl"
)
GR_SUMMARY = Path(
    "/home/user1-gpu/Desktop/grants_folder/windy-pro/grand_rounds/grand_rounds_summary.json"
)

EXAM_ID_PREFIX = "GR1"
RUN_DATE = "2026-03-29T04:48:06+00:00"
DOCTOR = "Herm Zero (Dr. B)"
FILED_BY = "Opus 4.6 Opus-Claw (Dr. C)"
MACHINE = "Veron-1 (RTX 5090, Mt Pleasant SC)"
METHOD = "Grand Rounds v1: 6-test composite (bloodwork, crossmatch, vitals, stress_fracture, consistency, scripture)"
PROTOCOL = "grand_rounds_harness.py v1"

# Grade → verdict mapping
GRADE_TO_VERDICT = {
    "A+": "EXCELLENT", "A": "EXCELLENT", "A-": "EXCELLENT",
    "B+": "GOOD", "B": "GOOD", "B-": "GOOD",
    "C+": "ACCEPTABLE", "C": "ACCEPTABLE", "C-": "ACCEPTABLE",
    "D+": "POOR", "D": "POOR", "D-": "POOR",
    "F": "FAIL",
}


def variant_key(harness_variant: str) -> str:
    """Map harness variant name to patient_file variant_cluster key."""
    if harness_variant == "base":
        return "base"
    if harness_variant == "herm0":
        return "herm0"
    if harness_variant == "herm0-ct2":
        return "herm0_ct2"
    if harness_variant == "herm0-scripture":
        return "herm0_scripture"
    if harness_variant == "ct2":
        return "ct2_int8"
    return harness_variant


def strip_detail(test_result: dict) -> dict:
    """Keep only the headline numbers, drop verbose per-sentence details."""
    if not isinstance(test_result, dict):
        return test_result
    out = {"status": test_result.get("status")}
    if out["status"] == "skipped":
        out["reason"] = test_result.get("reason")
        return out
    for k in ("score", "n_sentences", "passed", "total",
              "avg_latency_ms", "p95_latency_ms", "batch_throughput_sps",
              "gpu_memory_mb", "determinism"):
        if k in test_result:
            out[k] = test_result[k]
    return out


def build_exam_for_patient(rows: list) -> dict:
    """Collapse per-variant grand rounds rows into a single patient exam entry."""
    results = {}
    variants_tested = []
    for r in rows:
        vkey = variant_key(r["variant"])
        variants_tested.append(vkey)
        results[vkey] = {
            "composite_grade": r.get("composite_grade"),
            "composite_score": r.get("composite_score"),
            "verdict": GRADE_TO_VERDICT.get(r.get("composite_grade", ""), "UNKNOWN"),
            "grade_breakdown": r.get("grade_breakdown", {}),
            "skipped_tests": r.get("skipped_tests", []),
            "tests": {
                test: strip_detail(detail)
                for test, detail in r.get("test_results", {}).items()
            },
        }

    # Pick a best grade for convenience
    grades_present = [v["composite_grade"] for v in results.values() if v.get("composite_grade")]
    best_grade = max(grades_present, key=lambda g: ("ABCDF".index(g[0]), -ord(g[-1]) if len(g) > 1 else 0), default=None) if grades_present else None

    return {
        "exam_id": f"{EXAM_ID_PREFIX}-{rows[0]['model_name'][len('windy-pair-'):]}",
        "date": RUN_DATE,
        "doctor": DOCTOR,
        "filed_by": FILED_BY,
        "machine": MACHINE,
        "method": METHOD,
        "protocol_script": PROTOCOL,
        "variants_tested": variants_tested,
        "results": results,
        "notes": f"Grand Rounds v1 full-fleet battery. Run 2026-03-28/29, 4.9h, 2658 variants. Filed to clinic post-hoc by {FILED_BY} on 2026-04-11.",
    }


def load_gr_results():
    by_pid = defaultdict(list)
    with open(GR_RESULTS) as f:
        for line in f:
            r = json.loads(line)
            pid = r["model_name"][len("windy-pair-"):]
            by_pid[pid].append(r)
    return by_pid


def update_consensus(patient_chart: dict, base_result: dict | None) -> None:
    """Propagate base-variant Grand Rounds grade into consensus fields."""
    if not base_result:
        return
    consensus = patient_chart.setdefault("consensus", {})
    consensus["gr1_composite_grade"] = base_result.get("composite_grade")
    consensus["gr1_composite_score"] = base_result.get("composite_score")
    consensus["gr1_verdict"] = GRADE_TO_VERDICT.get(
        base_result.get("composite_grade", ""), "UNKNOWN"
    )
    consensus["last_updated"] = datetime.now().isoformat()


def merge(dry_run: bool = False):
    by_pid = load_gr_results()
    print(f"Loaded {sum(len(v) for v in by_pid.values())} rows across {len(by_pid)} patients")

    merged = 0
    skipped_already = 0
    missing = 0
    exam_id_prefix = EXAM_ID_PREFIX

    for pid, rows in by_pid.items():
        pf = PATIENTS_DIR / f"{pid}.json"
        if not pf.exists():
            missing += 1
            continue

        chart = json.loads(pf.read_text())
        exam_log = chart.setdefault("examination_log", [])

        existing_ids = {e.get("exam_id", "") for e in exam_log}
        exam_id = f"{exam_id_prefix}-{pid}"
        if exam_id in existing_ids:
            skipped_already += 1
            continue

        exam = build_exam_for_patient(rows)
        exam_log.append(exam)

        base_result = exam["results"].get("base")
        update_consensus(chart, base_result)

        chart["_last_updated"] = datetime.now().isoformat()

        if not dry_run:
            pf.write_text(json.dumps(chart, indent=2))
        merged += 1

    print(f"Merged: {merged}")
    print(f"Already present (skipped): {skipped_already}")
    print(f"Missing patient file: {missing}")


if __name__ == "__main__":
    import sys
    merge(dry_run="--dry-run" in sys.argv)

#!/usr/bin/env python3
"""Merge Phase 3b full-fleet certification results into clinic patient files.

Reads phase3b results JSONL and for each patient:
  - Creates one DRC-CERT-{pid} exam entry with results for ALL tested variants
  - Assigns Dr. C certification grade per variant
  - Updates consensus with Dr. C certification fields
  - Idempotent by exam_id

Doctor: Opus 4.6 Opus-Claw (Dr. C)
"""

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
PATIENTS = CLINIC / "translation-pairs"
RESULTS = CLINIC / "grand-rounds" / "phase3b_fullfleet" / "results.jsonl"

DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"
MACHINE = "Veron-1 (RTX 5090, Mt Pleasant SC)"

GRADE_RANK = {
    "A+": 13, "A": 12, "A-": 11, "B+": 10, "B": 9, "B-": 8,
    "C+": 7, "C": 6, "C-": 5, "D+": 4, "D": 3, "D-": 2, "F": 1,
}

GRADE_VERDICT = {
    "A+": "CERTIFIED_ELITE", "A": "CERTIFIED_EXCELLENT", "A-": "CERTIFIED_EXCELLENT",
    "B+": "CERTIFIED_GOOD", "B": "CERTIFIED_GOOD", "B-": "CERTIFIED_GOOD",
    "C+": "CERTIFIED_ACCEPTABLE", "C": "CERTIFIED_ACCEPTABLE", "C-": "CERTIFIED_ACCEPTABLE",
    "D+": "CERTIFIED_POOR", "D": "CERTIFIED_POOR", "D-": "CERTIFIED_POOR",
    "F": "CERTIFIED_FAIL",
}


def strip_verbose(test_results):
    """Keep headline metrics, drop per-sentence details."""
    out = {}
    for name, data in (test_results or {}).items():
        if not isinstance(data, dict):
            continue
        entry = {"status": data.get("status")}
        for k in ("score", "n_sentences", "passed", "total",
                  "avg_latency_ms", "p95_latency_ms", "batch_throughput_sps",
                  "gpu_memory_mb", "determinism"):
            if k in data:
                entry[k] = data[k]
        out[name] = entry
    return out


def variant_key(harness_variant):
    m = {"base": "base", "ct2": "ct2_int8", "herm0": "herm0",
         "herm0-scripture": "herm0_scripture", "herm0-ct2": "herm0_ct2"}
    return m.get(harness_variant, harness_variant)


def main():
    run_iso = datetime.now(timezone.utc).isoformat()

    # Group results by patient
    by_pid = defaultdict(list)
    total_rows = 0
    with open(RESULTS) as f:
        for line in f:
            r = json.loads(line)
            if r.get("status") != "complete":
                continue
            total_rows += 1
            model_name = r.get("model_name", "")
            pid = model_name[len("windy-pair-"):] if model_name.startswith("windy-pair-") else model_name
            by_pid[pid].append(r)

    print(f"Loaded {total_rows} complete rows across {len(by_pid)} patients")

    merged = 0
    skipped = 0

    for pid, rows in by_pid.items():
        pf = PATIENTS / f"{pid}.json"
        if not pf.exists():
            continue

        chart = json.loads(pf.read_text())
        log = chart.setdefault("examination_log", [])

        exam_id = f"DRC-CERT-{pid}"
        if any(e.get("exam_id") == exam_id for e in log):
            skipped += 1
            continue

        # Build per-variant results
        variant_results = {}
        variants_tested = []
        best_grade_rank = 0
        best_grade = None
        best_score = None

        for r in rows:
            vname = variant_key(r.get("variant", "base"))
            variants_tested.append(vname)
            grade = r.get("composite_grade")
            score = r.get("composite_score")

            variant_results[vname] = {
                "composite_grade": grade,
                "composite_score": score,
                "verdict": GRADE_VERDICT.get(grade, "UNKNOWN"),
                "grade_breakdown": r.get("grade_breakdown", {}),
                "skipped_tests": r.get("skipped_tests", []),
                "tests": strip_verbose(r.get("test_results", {})),
            }

            rank = GRADE_RANK.get(grade, 0)
            if rank > best_grade_rank:
                best_grade_rank = rank
                best_grade = grade
                best_score = score

        # Build exam entry
        exam = {
            "exam_id": exam_id,
            "date": run_iso,
            "doctor": DOCTOR,
            "machine": MACHINE,
            "method": (
                "Phase 3b — Full Fleet Dr. C Independent Certification. "
                "Ran grand_rounds_harness.py (same 6-test battery as Herm Zero's GR1) "
                "independently on every testable variant. This is Dr. C's personal "
                "certification, not a verification of GR1."
            ),
            "protocol_script": "scripts/phase3b_fullfleet.py + grand_rounds_harness.py",
            "variants_tested": sorted(set(variants_tested)),
            "results": variant_results,
            "best_grade": best_grade,
            "best_score": best_score,
            "notes": (
                f"Dr. C independent certification of {pid}. "
                f"Tested {len(variants_tested)} variant(s): {', '.join(sorted(set(variants_tested)))}. "
                f"Best variant grade: {best_grade} ({best_score}). "
                f"This is a fresh, independent run — not a re-run of GR1. "
                f"Filed by {DOCTOR} on {run_iso[:10]}."
            ),
        }
        log.append(exam)

        # Update consensus
        consensus = chart.setdefault("consensus", {})
        base_result = variant_results.get("base", {})
        consensus["drc_cert_grade"] = base_result.get("composite_grade")
        consensus["drc_cert_score"] = base_result.get("composite_score")
        consensus["drc_cert_verdict"] = base_result.get("verdict")
        consensus["drc_cert_best_variant_grade"] = best_grade
        consensus["drc_cert_best_variant_score"] = best_score
        consensus["drc_cert_date"] = run_iso
        consensus["drc_cert_doctor"] = DOCTOR

        chart["_last_updated"] = run_iso
        pf.write_text(json.dumps(chart, indent=2))
        merged += 1

    print(f"Merged: {merged}")
    print(f"Skipped (already present): {skipped}")

    # Grade distribution summary
    from collections import Counter
    base_grades = Counter()
    best_grades = Counter()
    for pid, rows in by_pid.items():
        for r in rows:
            if r.get("variant") == "base":
                base_grades[r.get("composite_grade")] += 1
        best = max((r.get("composite_grade", "F") for r in rows),
                   key=lambda g: GRADE_RANK.get(g, 0), default="?")
        best_grades[best] += 1

    print(f"\nBase grade distribution:")
    for g in sorted(base_grades, key=lambda x: -GRADE_RANK.get(x, 0)):
        print(f"  {g}: {base_grades[g]}")
    print(f"\nBest-variant grade distribution:")
    for g in sorted(best_grades, key=lambda x: -GRADE_RANK.get(x, 0)):
        print(f"  {g}: {best_grades[g]}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Merge Phase 3a independent re-test results into clinic patient files.

Reads phase3a_retest_results.jsonl and for each target patient:
  - appends a DRC-P3A-{pid} exam entry attributed to Opus 4.6 Opus-Claw (Dr. C)
  - compares against the GR1 grade stored in consensus.gr1_composite_grade
  - records the agreement/disagreement in consensus.phase3a_verdict

Doctor: Opus 4.6 Opus-Claw (Dr. C)
Date:   2026-04-11
"""

import json
from datetime import datetime, timezone
from pathlib import Path

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
PATIENTS = CLINIC / "translation-pairs"
RESULTS = CLINIC / "grand-rounds" / "phase3a_retest" / "phase3a_retest_results.jsonl"

DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"
MACHINE = "Veron-1 (RTX 5090, Mt Pleasant SC)"
RUN_ISO = datetime.now(timezone.utc).isoformat()


def main():
    results = []
    with open(RESULTS) as f:
        for line in f:
            results.append(json.loads(line))

    complete = [r for r in results if r.get("status") == "complete"]
    errors = [r for r in results if r.get("status") != "complete"]

    print(f"Loaded {len(results)} rows ({len(complete)} complete, {len(errors)} errors)")

    matches = 0
    mismatches = 0
    merged = 0

    for r in complete:
        pid = r["pid"]
        pf = PATIENTS / f"{pid}.json"
        if not pf.exists():
            print(f"  WARN: patient file missing: {pid}")
            continue

        chart = json.loads(pf.read_text())
        log = chart.setdefault("examination_log", [])

        exam_id = f"DRC-P3A-{pid}"
        if any(e.get("exam_id") == exam_id for e in log):
            continue  # idempotent

        # Build condensed test_results (drop verbose per-sentence data)
        test_summary = {}
        for test, data in r.get("test_results", {}).items():
            if not isinstance(data, dict):
                continue
            out = {"status": data.get("status")}
            for k in ("score", "passed", "total",
                      "avg_latency_ms", "p95_latency_ms", "batch_throughput_sps",
                      "gpu_memory_mb", "determinism", "n_sentences"):
                if k in data:
                    out[k] = data[k]
            test_summary[test] = out

        new_grade = r.get("composite_grade")
        new_score = r.get("composite_score")
        orig_grade = r.get("original_grade")
        orig_score = r.get("original_score")
        agreement = r.get("grade_agreement")

        if agreement == "match":
            matches += 1
        else:
            mismatches += 1

        exam = {
            "exam_id": exam_id,
            "date": r.get("_phase3a_filed_at", RUN_ISO),
            "doctor": DOCTOR,
            "machine": MACHINE,
            "method": (
                "Phase 3a — Independent re-run of Herm Zero's Grand Rounds v1 harness "
                "(same methodology, fresh execution). Targets: base variants that graded "
                "D+/D/D-/F in GR1 and still have safetensors on disk."
            ),
            "protocol_script": "grand_rounds_harness.py v1 via phase3a_retest.py",
            "variants_tested": ["base"],
            "results": {
                "base": {
                    "composite_grade": new_grade,
                    "composite_score": new_score,
                    "grade_breakdown": r.get("grade_breakdown", {}),
                    "skipped_tests": r.get("skipped_tests", []),
                    "tests": test_summary,
                    "verification_vs_gr1": {
                        "original_grade": orig_grade,
                        "original_score": orig_score,
                        "new_grade": new_grade,
                        "new_score": new_score,
                        "grade_agreement": agreement,
                        "score_delta": round((new_score or 0) - (orig_score or 0), 2),
                    },
                }
            },
            "elapsed_s": r.get("_phase3a_elapsed_s"),
            "notes": (
                f"Independent verification of GR1 failing base model. Ran the SAME "
                f"grand_rounds_harness.py that Herm Zero used, as a fresh subprocess. "
                f"Original GR1 grade: {orig_grade} ({orig_score}). "
                f"New grade: {new_grade} ({new_score}). "
                f"Agreement: {agreement}. "
                f"No model weights modified. Filed by {DOCTOR} on 2026-04-11."
            ),
        }
        log.append(exam)

        # Update consensus with phase3a verdict
        consensus = chart.setdefault("consensus", {})
        consensus["phase3a_grade"] = new_grade
        consensus["phase3a_score"] = new_score
        consensus["phase3a_verdict"] = (
            "CONFIRMED_FAILING" if agreement == "match"
            else "REFUTED_FAILING" if (new_grade and new_grade[0] in "ABC")
            else "DIFFERENT_FAILING_GRADE"
        )
        consensus["phase3a_filed_at"] = RUN_ISO

        chart["_last_updated"] = RUN_ISO
        pf.write_text(json.dumps(chart, indent=2))
        merged += 1

    print(f"Merged: {merged}")
    print(f"Matches (grade agrees with GR1): {matches}")
    print(f"Mismatches: {mismatches}")

    if errors:
        print(f"Errors (not merged): {len(errors)}")
        for e in errors[:10]:
            print(f"  {e.get('pid')}: {e.get('status')}")


if __name__ == "__main__":
    main()

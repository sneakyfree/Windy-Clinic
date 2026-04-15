#!/usr/bin/env python3
"""Merge phase3a_v2 results (71 ONNX-only restored retests) into patient files."""

import json
from datetime import datetime, timezone
from pathlib import Path

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
PATIENTS = CLINIC / "translation-pairs"
RESULTS = CLINIC / "grand-rounds" / "phase3a_v2_retest" / "results.jsonl"

DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"
MACHINE = "Veron-1 (RTX 5090, Mt Pleasant SC)"
RUN_ISO = datetime.now(timezone.utc).isoformat()


def main():
    merged = 0
    for line in open(RESULTS):
        r = json.loads(line)
        if r.get("status") != "complete":
            continue
        pid = r["pid"]
        pf = PATIENTS / f"{pid}.json"
        if not pf.exists():
            continue
        chart = json.loads(pf.read_text())
        log = chart.setdefault("examination_log", [])
        exam_id = f"DRC-P3A-V2-{pid}"
        if any(e.get("exam_id") == exam_id for e in log):
            continue

        # Strip verbose test data
        tests = {}
        for name, data in r.get("test_results", {}).items():
            if not isinstance(data, dict):
                continue
            out = {"status": data.get("status")}
            for k in ("score", "n_sentences", "passed", "total",
                      "avg_latency_ms", "p95_latency_ms", "batch_throughput_sps",
                      "gpu_memory_mb", "determinism"):
                if k in data:
                    out[k] = data[k]
            tests[name] = out

        log.append({
            "exam_id": exam_id,
            "date": r.get("_filed_at", RUN_ISO),
            "doctor": DOCTOR,
            "machine": MACHINE,
            "method": (
                "Phase 3a-v2 — re-test of ONNX-archived failing base model "
                "after restoring the original Helsinki-NLP source from HuggingFace "
                "and symlinking it into models/windy-pair-*/base/."
            ),
            "protocol_script": "scripts/phase3a_v2_retest.py + grand_rounds_harness.py",
            "variants_tested": ["base"],
            "results": {
                "base": {
                    "composite_grade": r.get("composite_grade"),
                    "composite_score": r.get("composite_score"),
                    "grade_breakdown": r.get("grade_breakdown", {}),
                    "skipped_tests": r.get("skipped_tests", []),
                    "tests": tests,
                    "verification_vs_gr1": {
                        "original_grade": r.get("original_grade"),
                        "original_score": r.get("original_score"),
                        "new_grade": r.get("composite_grade"),
                        "new_score": r.get("composite_score"),
                        "grade_agreement": r.get("grade_agreement"),
                    },
                }
            },
            "notes": (
                f"Re-test of a base model that was deleted during the 2026-03-29 "
                f"ONNX event and restored from Helsinki-NLP/opus-mt-{pid} today. "
                f"The restored base is the ORIGINAL pre-fine-tune Helsinki weights. "
                f"GR1 (Herm Zero): {r.get('original_grade')}/{r.get('original_score')}. "
                f"Dr. C retest: {r.get('composite_grade')}/{r.get('composite_score')}. "
                f"Agreement: {r.get('grade_agreement')}. "
                f"Filed by {DOCTOR} on 2026-04-11."
            ),
        })

        consensus = chart.setdefault("consensus", {})
        consensus["phase3a_v2_grade"] = r.get("composite_grade")
        consensus["phase3a_v2_score"] = r.get("composite_score")
        consensus["phase3a_v2_verdict"] = (
            "CONFIRMED_FAILING" if r.get("grade_agreement") == "match" else "DIFFERS"
        )

        chart["_last_updated"] = RUN_ISO
        pf.write_text(json.dumps(chart, indent=2))
        merged += 1

    print(f"Merged: {merged}")


if __name__ == "__main__":
    main()

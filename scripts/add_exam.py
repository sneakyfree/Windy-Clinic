#!/usr/bin/env python3
"""
THE CLINIC — Add Examination Utility

Simple utility to add a new examination entry to a patient's chart.
Useful for future agents to append new test results without re-merging everything.

Usage:
    python3 add_exam.py --patient af-en --doctor "Herm OC1" --method "stress test" \\
        --verdict PASS --score 95.0 --notes "All clear"
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
import sys

CLINIC_DIR = Path("/srv/repos/windy-pro/THE_CLINIC")

def add_examination(patient_id: str, doctor: str, method: str, verdict: str,
                   score: float = None, notes: str = "", exam_id: str = None,
                   protocol_script: str = None, variants_tested: list = None):
    """Add a new examination entry to a patient's chart."""

    patient_file = CLINIC_DIR / "translation-pairs" / f"{patient_id}.json"

    if not patient_file.exists():
        print(f"ERROR: Patient file not found: {patient_file}")
        return 1

    # Load patient chart
    with open(patient_file) as f:
        patient_chart = json.load(f)

    # Generate exam_id if not provided
    if not exam_id:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        exam_id = f"EXAM-{timestamp}"

    # Build examination entry
    exam_entry = {
        "exam_id": exam_id,
        "date": datetime.now().isoformat(),
        "doctor": doctor,
        "machine": "Unknown",
        "method": method,
        "protocol_script": protocol_script or "manual_entry",
        "variants_tested": variants_tested or ["base"],
        "results": {
            "base": {
                "verdict": verdict
            }
        },
        "notes": notes
    }

    # Add score if provided
    if score is not None:
        exam_entry["results"]["base"]["score"] = score

    # Append to examination_log
    if "examination_log" not in patient_chart:
        patient_chart["examination_log"] = []

    patient_chart["examination_log"].append(exam_entry)

    # Update metadata
    patient_chart["_last_updated"] = datetime.now().isoformat()

    # Recompute consensus
    examination_log = patient_chart["examination_log"]
    doctors = set(exam["doctor"] for exam in examination_log)

    patient_chart["consensus"]["last_updated"] = datetime.now().isoformat()
    patient_chart["consensus"]["doctors_examined"] = len(doctors)
    patient_chart["consensus"]["exams_total"] = len(examination_log)

    # Write back to file
    with open(patient_file, 'w') as f:
        json.dump(patient_chart, f, indent=2)

    print(f"SUCCESS: Added examination {exam_id} to patient {patient_id}")
    print(f"         Doctor: {doctor}")
    print(f"         Method: {method}")
    print(f"         Verdict: {verdict}")
    if score is not None:
        print(f"         Score: {score}")
    print(f"         Total exams for this patient: {len(examination_log)}")

    return 0

def main():
    parser = argparse.ArgumentParser(description="Add examination entry to patient chart")
    parser.add_argument("--patient", required=True, help="Patient ID (e.g., af-en)")
    parser.add_argument("--doctor", required=True, help="Doctor/agent name")
    parser.add_argument("--method", required=True, help="Testing methodology")
    parser.add_argument("--verdict", required=True, help="PASS, FAIL, PARTIAL, etc.")
    parser.add_argument("--score", type=float, help="Quality score (0-100)")
    parser.add_argument("--notes", default="", help="Additional notes")
    parser.add_argument("--exam-id", help="Custom exam ID")
    parser.add_argument("--protocol", help="Protocol script name")
    parser.add_argument("--variants", nargs="+", default=["base"],
                       help="Variants tested (default: base)")

    args = parser.parse_args()

    return add_examination(
        patient_id=args.patient,
        doctor=args.doctor,
        method=args.method,
        verdict=args.verdict,
        score=args.score,
        notes=args.notes,
        exam_id=args.exam_id,
        protocol_script=args.protocol,
        variants_tested=args.variants
    )

if __name__ == "__main__":
    sys.exit(main())

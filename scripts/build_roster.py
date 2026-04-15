#!/usr/bin/env python3
"""Build MASTER_ROSTER.json index from all patient files."""

import json
from datetime import datetime
from pathlib import Path

CLINIC_DIR = Path("/srv/repos/windy-pro/THE_CLINIC")
TRANSLATION_PAIRS_DIR = CLINIC_DIR / "translation-pairs"
OUTPUT_FILE = CLINIC_DIR / "MASTER_ROSTER.json"

def build_roster():
    print("Building MASTER_ROSTER.json...")

    roster = {
        "_generated": datetime.now().isoformat(),
        "_total_patients": 0,
        "_clinic_version": "v1",
        "_variant_counts": {},
        "_star_distribution": {},
        "patients": {}
    }

    patient_files = sorted(TRANSLATION_PAIRS_DIR.glob("*.json"))
    roster["_total_patients"] = len(patient_files)

    variant_counts = {}
    star_dist = {}

    for patient_file in patient_files:
        try:
            with open(patient_file) as f:
                patient_chart = json.load(f)

            patient_id = patient_chart["patient_id"]

            variant_cluster = patient_chart.get("variant_cluster", {})
            variants = [v for v, data in variant_cluster.items() if data.get("status") == "present"]
            for v in variants:
                variant_counts[v] = variant_counts.get(v, 0) + 1

            exam_log = patient_chart.get("examination_log", [])
            exams_count = len(exam_log)
            last_exam = exam_log[-1]["date"] if exam_log else None
            doctors_seen = sorted({exam["doctor"] for exam in exam_log})

            quality = patient_chart.get("quality_rating", {}) or {}
            stars = quality.get("stars")
            quality_label = quality.get("label") or quality.get("quality_label")
            if stars is not None:
                bucket = f"{stars:.1f}"
                star_dist[bucket] = star_dist.get(bucket, 0) + 1

            consensus = patient_chart.get("consensus", {}) or {}

            roster["patients"][patient_id] = {
                "source_repo": patient_chart.get("source_repo"),
                "source_lang": patient_chart.get("source_language", {}).get("code"),
                "target_lang": patient_chart.get("target_language", {}).get("code"),
                "variants": variants,
                "exams_count": exams_count,
                "last_exam": last_exam,
                "doctors_seen": doctors_seen,
                "production_ready": consensus.get("production_ready", False),
                "stars": stars,
                "quality_label": quality_label,
                "overall_verdict": consensus.get("overall_verdict"),
                "confidence": consensus.get("confidence"),
                "gr1_grade": consensus.get("gr1_composite_grade"),
                "gr1_score": consensus.get("gr1_composite_score"),
                "gr1_verdict": consensus.get("gr1_verdict"),
                "has_herm0": "herm0" in variants,
                "has_herm0_scripture": "herm0_scripture" in variants,
            }

        except Exception as e:
            print(f"  WARNING: Failed to process {patient_file.name}: {e}")

    roster["_variant_counts"] = dict(sorted(variant_counts.items(), key=lambda x: -x[1]))
    roster["_star_distribution"] = dict(sorted(star_dist.items(), reverse=True))

    # Write roster
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(roster, f, indent=2)

    print(f"  Created MASTER_ROSTER.json with {len(roster['patients'])} patients")
    print(f"  Location: {OUTPUT_FILE}")

    total_exams = sum(p["exams_count"] for p in roster["patients"].values())
    prod_ready = sum(1 for p in roster["patients"].values() if p["production_ready"])
    has_herm0 = sum(1 for p in roster["patients"].values() if p["has_herm0"])
    has_scripture = sum(1 for p in roster["patients"].values() if p["has_herm0_scripture"])
    has_gr1 = sum(1 for p in roster["patients"].values() if p.get("gr1_grade"))

    gr1_dist = {}
    for p in roster["patients"].values():
        g = p.get("gr1_grade")
        if g:
            gr1_dist[g] = gr1_dist.get(g, 0) + 1
    roster["_gr1_grade_distribution"] = dict(sorted(gr1_dist.items()))

    print()
    print("Statistics:")
    print(f"  Total patients: {roster['_total_patients']}")
    print(f"  Total examinations: {total_exams}")
    print(f"  Production ready: {prod_ready}")
    print(f"  With GR1 grade: {has_gr1}")
    print(f"  With herm0 (OPUS): {has_herm0}")
    print(f"  With herm0_scripture (eBible): {has_scripture}")
    print(f"  Variant counts: {roster['_variant_counts']}")
    print(f"  GR1 grade distribution: {roster['_gr1_grade_distribution']}")

if __name__ == "__main__":
    build_roster()

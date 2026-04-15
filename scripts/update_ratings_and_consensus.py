#!/usr/bin/env python3
"""
Update script for THE CLINIC
- Adds quality_rating from OC1 source files to clinic patient files
- Fixes consensus logic by properly analyzing all examination_log entries
- Regenerates MASTER_ROSTER.json with new fields

This script is idempotent and safe to re-run.
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from collections import defaultdict


# Paths
OC1_SOURCE_DIR = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/patient_files_v2")
CLINIC_DIR = Path("/srv/repos/windy-pro/THE_CLINIC/translation-pairs")
MASTER_ROSTER_PATH = Path("/srv/repos/windy-pro/THE_CLINIC/MASTER_ROSTER.json")


def render_stars(stars: float) -> str:
    """Render star rating as visual unicode stars."""
    rounded = round(stars * 2) / 2  # Round to nearest 0.5

    if rounded == 5.0:
        return "★★★★★"
    elif rounded == 4.5:
        return "★★★★½"
    elif rounded == 4.0:
        return "★★★★"
    elif rounded == 3.5:
        return "★★★½"
    elif rounded == 3.0:
        return "★★★"
    elif rounded == 2.5:
        return "★★½"
    elif rounded == 2.0:
        return "★★"
    elif rounded == 1.5:
        return "★½"
    elif rounded == 1.0:
        return "★"
    elif rounded == 0.5:
        return "½"
    else:
        return "☆"


def extract_patient_id_from_oc1_filename(filename: str) -> Optional[str]:
    """Extract patient_id from OC1 source filename."""
    if filename.startswith("windy-pair-") and filename.endswith(".json"):
        return filename.replace("windy-pair-", "").replace(".json", "")
    elif filename.startswith("windy-p2-helsinki-tc-big-") and filename.endswith(".json"):
        return filename.replace("windy-p2-helsinki-tc-big-", "").replace(".json", "")
    return None


def load_oc1_quality_ratings() -> Dict[str, Dict]:
    """Load all quality_rating objects from OC1 source files."""
    ratings = {}

    for filename in os.listdir(OC1_SOURCE_DIR):
        if not filename.endswith(".json"):
            continue

        patient_id = extract_patient_id_from_oc1_filename(filename)
        if not patient_id:
            continue

        filepath = OC1_SOURCE_DIR / filename
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
                if "quality_rating" in data:
                    ratings[patient_id] = data["quality_rating"]
        except Exception as e:
            print(f"Warning: Could not read {filename}: {e}")

    return ratings


def compute_consensus(examination_log: List[Dict]) -> Dict[str, Any]:
    """
    Compute consensus from all examination_log entries.

    Returns a consensus object with:
    - base_verdict: PASS/FAIL/UNTESTED
    - lora_verdict: PASS/FAIL/UNTESTED
    - ct2_verdict: PASS/LOADER_BROKEN/UNTESTED
    - overall_verdict: PASS if base works
    - confidence: HIGH/MEDIUM/LOW/NONE
    - production_ready: bool
    """
    if not examination_log:
        return {
            "last_updated": datetime.utcnow().isoformat(),
            "doctors_examined": 0,
            "exams_total": 0,
            "base_verdict": "UNTESTED",
            "lora_verdict": "UNTESTED",
            "ct2_verdict": "UNTESTED",
            "overall_verdict": "UNTESTED",
            "confidence": "NONE",
            "production_ready": False,
            "notes": ["No examinations recorded"]
        }

    # Collect unique doctors
    doctors = set()
    for exam in examination_log:
        if "doctor" in exam:
            doctors.add(exam["doctor"])

    # Analyze each variant across all exams
    base_results = []
    lora_results = []
    ct2_results = []
    ct2_has_loader_error = False

    for exam in examination_log:
        results = exam.get("results", {})

        # Base variant analysis
        if "base" in results:
            base_data = results["base"]
            base_results.append(analyze_variant_result(base_data, "base"))

        # LoRA variant analysis
        if "lora" in results:
            lora_data = results["lora"]
            lora_results.append(analyze_variant_result(lora_data, "lora"))

        # CT2 variant analysis
        if "ct2" in results or "ct2_int8" in results:
            ct2_data = results.get("ct2") or results.get("ct2_int8")
            ct2_result = analyze_variant_result(ct2_data, "ct2")
            ct2_results.append(ct2_result)

            # Check for loader errors
            if ct2_result == "LOADER_ERROR" or is_loader_error(ct2_data):
                ct2_has_loader_error = True

    # Compute verdicts
    base_verdict = compute_verdict(base_results)
    lora_verdict = compute_verdict(lora_results)

    # CT2 special handling for loader errors
    if ct2_has_loader_error:
        ct2_verdict = "LOADER_BROKEN"
    else:
        ct2_verdict = compute_verdict(ct2_results)

    # Overall verdict: PASS if base works
    overall_verdict = base_verdict

    # Compute confidence
    doctors_count = len(doctors)
    if base_verdict == "PASS" and doctors_count >= 3:
        confidence = "HIGH"
    elif base_verdict == "PASS" and doctors_count >= 2:
        confidence = "MEDIUM"
    elif base_verdict == "PASS" and doctors_count >= 1:
        confidence = "LOW"
    elif doctors_count == 0:
        confidence = "NONE"
    else:
        # Base failed or untested
        confidence = "LOW"

    # Production ready: overall_verdict is PASS and confidence is HIGH or MEDIUM
    production_ready = overall_verdict == "PASS" and confidence in ["HIGH", "MEDIUM"]

    # Generate notes
    notes = []
    if base_verdict == "PASS":
        if all(r == "PASS" for r in base_results):
            notes.append("All doctors agree base works")
        else:
            notes.append("Base generally passes")

    if lora_verdict == "PASS" and base_verdict == "PASS":
        notes.append("LoRA variant functional")
    elif lora_verdict == "UNTESTED":
        notes.append("LoRA not tested")

    if ct2_verdict == "LOADER_BROKEN":
        notes.append("CT2 has universal loader issue")
    elif ct2_verdict == "PASS":
        notes.append("CT2 variant functional")
    elif ct2_verdict == "UNTESTED":
        notes.append("CT2 not tested")

    return {
        "last_updated": datetime.utcnow().isoformat(),
        "doctors_examined": len(doctors),
        "exams_total": len(examination_log),
        "base_verdict": base_verdict,
        "lora_verdict": lora_verdict,
        "ct2_verdict": ct2_verdict,
        "overall_verdict": overall_verdict,
        "confidence": confidence,
        "production_ready": production_ready,
        "notes": notes
    }


def analyze_variant_result(variant_data: Dict, variant_name: str) -> str:
    """
    Analyze a single variant result and return PASS/FAIL/LOADER_ERROR/UNTESTED.
    """
    if not variant_data:
        return "UNTESTED"

    # Check for errors
    if "error" in variant_data:
        error_text = variant_data["error"].lower()
        if "no file named" in error_text or "loader" in error_text:
            return "LOADER_ERROR"
        return "FAIL"

    # Check verdict field (Herm Zero style)
    if "verdict" in variant_data:
        verdict = variant_data["verdict"]
        if verdict in ["PASS", "CERTIFIED"]:
            return "PASS"
        elif verdict == "FAIL":
            return "FAIL"

    # Check certified field (OC1 style)
    if "certified" in variant_data:
        if variant_data["certified"]:
            return "PASS"
        else:
            return "FAIL"

    # Check score (if score >= 7 out of 10, consider it a pass)
    if "score" in variant_data:
        score = variant_data["score"]
        total = variant_data.get("total", 10)
        if score is not None and total is not None and total > 0 and (score / total) >= 0.7:
            return "PASS"
        elif score is not None and total is not None:
            return "FAIL"

    # Check quality_score (if >= 70, consider it a pass)
    if "quality_score" in variant_data:
        quality_score = variant_data["quality_score"]
        if quality_score is not None and quality_score >= 70:
            return "PASS"
        elif quality_score is not None:
            return "FAIL"

    return "UNTESTED"


def is_loader_error(variant_data: Dict) -> bool:
    """Check if variant has a loader error."""
    if "error" in variant_data:
        error_text = variant_data["error"].lower()
        return "no file named" in error_text or "loader" in error_text

    # Check quality_score being extremely low (< 10)
    if "quality_score" in variant_data:
        quality_score = variant_data["quality_score"]
        if quality_score is not None and quality_score < 10:
            return True

    return False


def compute_verdict(results: List[str]) -> str:
    """
    Compute majority verdict from list of results.
    """
    if not results:
        return "UNTESTED"

    # Filter out UNTESTED
    filtered = [r for r in results if r != "UNTESTED"]
    if not filtered:
        return "UNTESTED"

    # Check for loader errors
    if "LOADER_ERROR" in filtered:
        return "FAIL"

    # Count PASS vs FAIL
    pass_count = filtered.count("PASS")
    fail_count = filtered.count("FAIL")

    # Majority wins
    if pass_count > fail_count:
        return "PASS"
    elif fail_count > pass_count:
        return "FAIL"
    else:
        # Tie - be conservative and say FAIL
        return "FAIL"


def update_clinic_patient_file(patient_id: str, quality_rating: Dict) -> bool:
    """
    Update a single clinic patient file with quality_rating and consensus.
    Returns True if updated, False if file not found.
    """
    clinic_filepath = CLINIC_DIR / f"{patient_id}.json"

    if not clinic_filepath.exists():
        return False

    try:
        with open(clinic_filepath, 'r') as f:
            patient_data = json.load(f)

        # Add quality_rating
        enhanced_rating = {
            "stars": quality_rating["stars"],
            "stars_display": render_stars(quality_rating["stars"]),
            "half_stars": round(quality_rating["stars"] * 2),
            "label": quality_rating["label"],
            "avg_cert_score": quality_rating["avg_cert_score"],
            "best_variant_score": quality_rating["best_variant_score"],
            "variants_tested": quality_rating["variants_tested"],
            "source": "Kit OC1 Alpha certification"
        }
        patient_data["quality_rating"] = enhanced_rating

        # Compute and update consensus
        examination_log = patient_data.get("examination_log", [])
        consensus = compute_consensus(examination_log)
        patient_data["consensus"] = consensus

        # Update timestamp
        patient_data["_last_updated"] = datetime.utcnow().isoformat()

        # Write back
        with open(clinic_filepath, 'w') as f:
            json.dump(patient_data, f, indent=2, ensure_ascii=False)

        return True

    except Exception as e:
        print(f"Error updating {patient_id}: {e}")
        return False


def update_all_consensus_without_ratings():
    """
    Update consensus for all clinic files that don't have quality_rating yet.
    This ensures consensus is fixed for all patients.
    """
    count = 0
    for filename in os.listdir(CLINIC_DIR):
        if not filename.endswith(".json"):
            continue

        filepath = CLINIC_DIR / filename
        try:
            with open(filepath, 'r') as f:
                patient_data = json.load(f)

            # Skip if already has quality_rating (was handled by update_clinic_patient_file)
            if "quality_rating" in patient_data:
                continue

            # Compute and update consensus
            examination_log = patient_data.get("examination_log", [])
            consensus = compute_consensus(examination_log)
            patient_data["consensus"] = consensus

            # Update timestamp
            patient_data["_last_updated"] = datetime.utcnow().isoformat()

            # Write back
            with open(filepath, 'w') as f:
                json.dump(patient_data, f, indent=2, ensure_ascii=False)

            count += 1

        except Exception as e:
            print(f"Error updating consensus for {filename}: {e}")

    return count


def regenerate_master_roster():
    """
    Regenerate MASTER_ROSTER.json with new fields:
    - stars and label from quality_rating
    - overall_verdict and confidence from consensus
    - production_ready from consensus
    """
    patients = {}

    for filename in os.listdir(CLINIC_DIR):
        if not filename.endswith(".json"):
            continue

        patient_id = filename.replace(".json", "")
        filepath = CLINIC_DIR / filename

        try:
            with open(filepath, 'r') as f:
                patient_data = json.load(f)

            # Extract exam data
            exam_log = patient_data.get("examination_log", [])
            doctors = set()
            last_exam = None
            variants = set()

            for exam in exam_log:
                if "doctor" in exam:
                    doctors.add(exam["doctor"])
                if "date" in exam:
                    if last_exam is None or exam["date"] > last_exam:
                        last_exam = exam["date"]
                if "variants_tested" in exam:
                    variants.update(exam["variants_tested"])

            # Get quality rating fields
            quality_rating = patient_data.get("quality_rating", {})
            stars = quality_rating.get("stars")
            label = quality_rating.get("label")

            # Get consensus fields
            consensus = patient_data.get("consensus", {})
            overall_verdict = consensus.get("overall_verdict")
            confidence = consensus.get("confidence")
            production_ready = consensus.get("production_ready", False)

            patients[patient_id] = {
                "source_repo": patient_data.get("source_repo"),
                "source_lang": patient_data.get("source_language", {}).get("code"),
                "target_lang": patient_data.get("target_language", {}).get("code"),
                "variants": sorted(list(variants)),
                "exams_count": len(exam_log),
                "last_exam": last_exam,
                "doctors_seen": sorted(list(doctors)),
                "production_ready": production_ready,
                "stars": stars,
                "quality_label": label,
                "overall_verdict": overall_verdict,
                "confidence": confidence
            }

        except Exception as e:
            print(f"Error processing {filename} for roster: {e}")

    # Write MASTER_ROSTER
    roster = {
        "_generated": datetime.utcnow().isoformat(),
        "_total_patients": len(patients),
        "_clinic_version": "v1",
        "patients": patients
    }

    with open(MASTER_ROSTER_PATH, 'w') as f:
        json.dump(roster, f, indent=2, ensure_ascii=False)

    return len(patients)


def print_verification_stats():
    """Print verification statistics after update."""
    # Count files with quality_rating
    quality_count = 0
    production_ready_count = 0
    confidence_counts = defaultdict(int)

    samples = []

    for filename in os.listdir(CLINIC_DIR):
        if not filename.endswith(".json"):
            continue

        filepath = CLINIC_DIR / filename
        try:
            with open(filepath, 'r') as f:
                patient_data = json.load(f)

            if "quality_rating" in patient_data:
                quality_count += 1

            consensus = patient_data.get("consensus", {})
            if consensus.get("production_ready"):
                production_ready_count += 1

            confidence = consensus.get("confidence")
            if confidence:
                confidence_counts[confidence] += 1

            # Collect samples (first 5)
            if len(samples) < 5:
                samples.append({
                    "patient_id": patient_data.get("patient_id"),
                    "quality_rating": patient_data.get("quality_rating"),
                    "consensus": consensus
                })

        except Exception as e:
            print(f"Error reading {filename}: {e}")

    print("\n" + "="*70)
    print("VERIFICATION RESULTS")
    print("="*70)
    print(f"Patients with quality_rating: {quality_count}")
    print(f"Patients production_ready=true: {production_ready_count}")
    print(f"\nConfidence tier breakdown:")
    print(f"  HIGH:   {confidence_counts['HIGH']}")
    print(f"  MEDIUM: {confidence_counts['MEDIUM']}")
    print(f"  LOW:    {confidence_counts['LOW']}")
    print(f"  NONE:   {confidence_counts['NONE']}")

    print(f"\nSample of 5 random patients:")
    for i, sample in enumerate(samples, 1):
        print(f"\n{i}. {sample['patient_id']}")
        qr = sample.get("quality_rating")
        if qr:
            print(f"   Quality: {qr.get('stars_display')} ({qr.get('stars')} stars, {qr.get('label')})")
        else:
            print(f"   Quality: No rating")

        cons = sample.get("consensus", {})
        print(f"   Consensus: {cons.get('overall_verdict')} | Confidence: {cons.get('confidence')} | Production Ready: {cons.get('production_ready')}")


def main():
    print("="*70)
    print("THE CLINIC: Update Ratings and Consensus")
    print("="*70)

    # Step 1: Load OC1 quality ratings
    print("\n[1/5] Loading OC1 quality ratings...")
    ratings = load_oc1_quality_ratings()
    print(f"      Loaded {len(ratings)} quality ratings from OC1 source files")

    # Step 2: Update clinic files with quality ratings
    print("\n[2/5] Adding quality ratings to clinic patient files...")
    updated_count = 0
    for patient_id, quality_rating in ratings.items():
        if update_clinic_patient_file(patient_id, quality_rating):
            updated_count += 1
    print(f"      Updated {updated_count} patient files with quality ratings")

    # Step 3: Update consensus for all remaining files
    print("\n[3/5] Fixing consensus logic for all patients...")
    consensus_only_count = update_all_consensus_without_ratings()
    print(f"      Updated consensus for {consensus_only_count} additional patients")

    # Step 4: Regenerate MASTER_ROSTER
    print("\n[4/5] Regenerating MASTER_ROSTER.json...")
    roster_count = regenerate_master_roster()
    print(f"      MASTER_ROSTER updated with {roster_count} patients")

    # Step 5: Verification
    print("\n[5/5] Running verification checks...")
    print_verification_stats()

    print("\n" + "="*70)
    print("Update complete!")
    print("="*70)


if __name__ == "__main__":
    main()

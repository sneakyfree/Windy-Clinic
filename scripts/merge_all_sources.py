#!/usr/bin/env python3
"""
THE CLINIC — Unified Patient File Merger
Merges examination data from 4 different doctors/sources into canonical patient charts.

Sources:
1. Kit OC1 Alpha (Dr. A) — patient_files_v2
2. Herm Zero (Dr. B) — Deep Audit v4
3. Herm Zero (Dr. B) — STREPS paragraph stress test
4. Herm OC1 — Original model stress test (ongoing)

Output: THE_CLINIC/translation-pairs/{patient_id}.json
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict
import re

# Paths
SOURCE1_DIR = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/patient_files_v2")
SOURCE2_DIR = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/audit_results/patient_files")
SOURCE3_FILE = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/audit_results/streps/streps_results.jsonl")
SOURCE4_DIR = Path("/srv/repos/windy-pro/stress-test/patient-files/translation-pairs")
OUTPUT_DIR = Path("/srv/repos/windy-pro/THE_CLINIC/translation-pairs")

# Doctor names
DOCTOR_KIT = "Kit OC1 Alpha (Dr. A)"
DOCTOR_HERM_ZERO = "Herm Zero (Dr. B)"
DOCTOR_HERM_OC1 = "Herm OC1"

def normalize_patient_id(raw_id: str) -> str:
    """Extract canonical patient ID from various naming formats."""
    # Strip windy-pair- prefix
    if raw_id.startswith("windy-pair-"):
        raw_id = raw_id[len("windy-pair-"):]

    # Strip windy-p2-helsinki-tc-big- prefix
    if raw_id.startswith("windy-p2-helsinki-tc-big-"):
        raw_id = raw_id[len("windy-p2-helsinki-tc-big-"):]

    # Strip .json extension
    if raw_id.endswith(".json"):
        raw_id = raw_id[:-5]

    return raw_id

def extract_language_info(patient_id: str):
    """Extract source and target language codes from patient ID."""
    parts = patient_id.split("-")
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return "unknown", "unknown"

def load_source1_data():
    """Load Kit OC1 Alpha patient files (v2.0 schema)."""
    print("Loading Source 1: Kit OC1 Alpha patient_files_v2...")
    patients = {}

    for json_file in SOURCE1_DIR.glob("*.json"):
        try:
            with open(json_file) as f:
                data = json.load(f)

            # Extract model_key for Phase 2 models, or derive from filename
            if "identity" in data and "model_key" in data["identity"]:
                patient_id = data["identity"]["model_key"]
            else:
                patient_id = normalize_patient_id(json_file.stem)

            patients[patient_id] = data
        except Exception as e:
            print(f"  WARNING: Failed to load {json_file.name}: {e}")

    print(f"  Loaded {len(patients)} patients from Source 1")
    return patients

def load_source2_data():
    """Load Herm Zero Deep Audit v4 files."""
    print("Loading Source 2: Herm Zero Deep Audit v4...")
    patients = {}

    for json_file in SOURCE2_DIR.glob("*.json"):
        try:
            with open(json_file) as f:
                data = json.load(f)

            patient_id = data.get("model_id", json_file.stem)
            patients[patient_id] = data
        except Exception as e:
            print(f"  WARNING: Failed to load {json_file.name}: {e}")

    print(f"  Loaded {len(patients)} patients from Source 2")
    return patients

def load_source3_data():
    """Load Herm Zero STREPS data (JSONL)."""
    print("Loading Source 3: Herm Zero STREPS...")
    patients = {}

    if not SOURCE3_FILE.exists():
        print(f"  WARNING: STREPS file not found at {SOURCE3_FILE}")
        return patients

    with open(SOURCE3_FILE) as f:
        for line_num, line in enumerate(f, 1):
            try:
                data = json.loads(line.strip())
                patient_id = data.get("model_id")
                if patient_id:
                    patients[patient_id] = data
            except Exception as e:
                print(f"  WARNING: Failed to parse STREPS line {line_num}: {e}")

    print(f"  Loaded {len(patients)} patients from Source 3 (STREPS)")
    return patients

def load_source4_data():
    """Load Herm OC1 original model stress test data."""
    print("Loading Source 4: Herm OC1 stress test...")
    patients = {}

    if not SOURCE4_DIR.exists():
        print(f"  WARNING: Source 4 directory not found at {SOURCE4_DIR}")
        return patients

    for json_file in SOURCE4_DIR.glob("*.json"):
        try:
            with open(json_file) as f:
                data = json.load(f)

            patient_id = data.get("pair_code", json_file.stem)
            patients[patient_id] = data
        except Exception as e:
            print(f"  WARNING: Failed to load {json_file.name}: {e}")

    print(f"  Loaded {len(patients)} patients from Source 4")
    return patients

def build_exam_from_source1(data, patient_id):
    """Build examination_log entries from Kit OC1 Alpha data."""
    exams = []

    if "examinations" not in data:
        return exams

    # Dr. A OC1 certification sweeps
    dr_a = data["examinations"].get("dr_a_oc1", {})

    # Sweep 1
    sweep1 = dr_a.get("sweep_1", {})
    if sweep1.get("date"):
        exam = {
            "exam_id": "OC1-CERT-SWEEP1",
            "date": sweep1["date"],
            "doctor": DOCTOR_KIT,
            "machine": "Veron 1 (RTX 5090, Mt Pleasant SC)",
            "method": "10-sentence certification — binary quality checks per sentence",
            "protocol_script": "scripts/certify_one_model.py v2",
            "variants_tested": ["base", "lora", "ct2_int8"],
            "results": sweep1.get("results", {}),
            "notes": "Sweep 1 — source-language-aware certification"
        }
        exams.append(exam)

    # Sweep 2
    sweep2 = dr_a.get("sweep_2", {})
    if sweep2.get("date"):
        exam = {
            "exam_id": "OC1-CERT-SWEEP2",
            "date": sweep2["date"],
            "doctor": DOCTOR_KIT,
            "machine": "Veron 1 (RTX 5090, Mt Pleasant SC)",
            "method": "Re-certification with correct source language detection",
            "protocol_script": "scripts/certify_one_model.py v2",
            "variants_tested": ["base", "lora", "ct2"],
            "results": sweep2.get("results", {}),
            "notes": "Sweep 2 — recertification"
        }
        exams.append(exam)

    # Dr. B Herm0 audit (if present in Source 1)
    dr_b = data["examinations"].get("dr_b_herm0", {})
    cert_audit = dr_b.get("certification_audit", {})
    if cert_audit.get("date"):
        exam = {
            "exam_id": "H0-DEEPAUDIT",
            "date": cert_audit["date"],
            "doctor": DOCTOR_HERM_ZERO,
            "machine": "Veron 1 (RTX 5090, Mt Pleasant SC)",
            "method": "Independent replication — 10 test sentences, structural quality scoring",
            "protocol_script": "deep_audit_v4",
            "variants_tested": ["base", "lora", "ct2"],
            "results": cert_audit.get("results", {}),
            "identity_check": data.get("variant_delta_analysis", {}).get("base_vs_lora", {}),
            "notes": "h0_v4 certification"
        }
        exams.append(exam)

    return exams

def build_exam_from_source2(data, patient_id):
    """Build examination_log entry from Herm Zero Deep Audit v4."""
    exams = []

    audit_date = data.get("audit_timestamp")
    if not audit_date:
        # Try h0_v4_certification timestamp
        h0_cert = data.get("h0_v4_certification", {})
        audit_date = h0_cert.get("timestamp")

    if not audit_date:
        # Use file mtime as fallback
        audit_date = datetime.now().isoformat()

    h0_eval = data.get("h0_evaluation", {})
    variants = h0_eval.get("variants", {})

    exam = {
        "exam_id": "H0-DEEPAUDIT-20260323",
        "date": audit_date,
        "doctor": DOCTOR_HERM_ZERO,
        "machine": "Veron 1 (RTX 5090, Mt Pleasant SC)",
        "method": "Independent replication — 10 test sentences, structural quality scoring",
        "protocol_script": "deep_audit_v4",
        "variants_tested": list(variants.keys()),
        "results": {},
        "identity_check": data.get("identity_check", {}),
        "notes": "h0_v4 certification"
    }

    # Extract results
    for variant, vdata in variants.items():
        exam["results"][variant] = {
            "verdict": "PASS" if vdata.get("status") == "ok" else "ERROR",
            "quality_score": vdata.get("quality_score"),
            "checks": vdata.get("quality_checks", {})
        }

    exams.append(exam)
    return exams

def build_exam_from_source3(data, patient_id):
    """Build examination_log entry from Herm Zero STREPS."""
    exams = []

    timestamp = data.get("timestamp")
    if not timestamp:
        timestamp = datetime.now().isoformat()

    variants_data = data.get("variants", {})

    exam = {
        "exam_id": "H0-STREPS-20260324",
        "date": timestamp,
        "doctor": DOCTOR_HERM_ZERO,
        "machine": "Veron 1 (RTX 5090, Mt Pleasant SC)",
        "method": "STREPS — paragraph-length native-language input (~100 words), 7 quality checks",
        "protocol_script": "streps_audit",
        "variants_tested": list(variants_data.keys()),
        "results": {},
        "lora_comparison": data.get("variant_comparisons", {}).get("base_vs_lora", {}),
        "notes": "Full paragraph stress test with native-language input"
    }

    # Extract results for each variant
    for variant, vdata in variants_data.items():
        if vdata.get("status") == "ok":
            exam["results"][variant] = {
                "verdict": "PASS",
                "quality_score": vdata.get("quality_score"),
                "paragraph_source": data.get("paragraph_source"),
                "output_length": vdata.get("output_len")
            }
        elif vdata.get("status") == "error":
            exam["results"][variant] = {
                "verdict": "ERROR",
                "error": vdata.get("error", "loader incompatibility")
            }

    exams.append(exam)
    return exams

def build_exam_from_source4(data, patient_id):
    """Build examination_log entry from Herm OC1 stress test."""
    exams = []

    tested_date = data.get("tested")
    if not tested_date:
        tested_date = datetime.now().isoformat()

    exam = {
        "exam_id": "HOC1-ORIGSTRESS-20260324",
        "date": tested_date,
        "doctor": DOCTOR_HERM_OC1,
        "machine": "Veron 1 (RTX 5090, Mt Pleasant SC)",
        "method": "Original HF model stress test — downloaded source model from HuggingFace, 5 paragraph types",
        "protocol_script": "run_stress.py",
        "source_tested": data.get("source", "Helsinki-NLP/opus-mt-" + patient_id) + " (original from HuggingFace, NOT Windy Pro copy)",
        "results": {},
        "notes": "Independent verification of upstream source model. All paragraph types tested: business, casual, technical, literary, medical."
    }

    # GPU results
    gpu_data = data.get("gpu", {})
    if gpu_data.get("load_ok"):
        paragraphs = gpu_data.get("paragraphs", [])
        passed = sum(1 for p in paragraphs if p.get("ok"))
        total = len(paragraphs)

        exam["results"]["original_base"] = {
            "verdict": "PASS" if data.get("verdict") == "PASS" else "PARTIAL",
            "paragraphs_passed": passed,
            "paragraphs_tested": total
        }

    # CT2 results (if available)
    ct2_data = data.get("ct2", {})
    if ct2_data.get("load_ok"):
        paragraphs = ct2_data.get("paragraphs", [])
        passed = sum(1 for p in paragraphs if p.get("ok"))
        total = len(paragraphs)

        exam["results"]["original_ct2"] = {
            "verdict": "PASS" if passed == total else "PARTIAL",
            "paragraphs_passed": passed,
            "paragraphs_tested": total,
            "avg_bleu": data.get("avg_bleu"),
            "avg_chrf": data.get("avg_chrf")
        }

    exams.append(exam)
    return exams

def build_variant_cluster(source1_data, source2_data):
    """Build variant_cluster section from available data."""
    cluster = {
        "base": {"status": "missing"},
        "lora": {"status": "missing"},
        "ct2_int8": {"status": "missing"}
    }

    # Prefer Source 1 (Kit OC1 Alpha) for variant info
    if source1_data and "variants" in source1_data:
        variants_data = source1_data["variants"]

        if "base" in variants_data and variants_data["base"].get("exists"):
            base = variants_data["base"]
            cluster["base"] = {
                "status": "present",
                "format": base.get("format", "safetensors"),
                "size_bytes": base.get("size_bytes"),
                "model_dir": None  # Would need to infer from paths
            }

        if "lora" in variants_data and variants_data["lora"].get("exists"):
            lora = variants_data["lora"]
            cluster["lora"] = {
                "status": "present",
                "format": lora.get("format", "safetensors"),
                "size_bytes": lora.get("size_bytes"),
                "identical_to_base": None,  # Inferred from identity checks
                "model_dir": None
            }

        if "ct2_int8" in variants_data and variants_data["ct2_int8"].get("exists"):
            ct2 = variants_data["ct2_int8"]
            cluster["ct2_int8"] = {
                "status": "present",
                "format": ct2.get("format", "ctranslate2"),
                "loader_compatible": False,  # Known issue
                "model_dir": None
            }

    # Fallback to Source 2 if Source 1 not available
    elif source2_data and "variant_inventory" in source2_data:
        inv = source2_data["variant_inventory"]
        for variant in ["base", "lora", "ct2"]:
            if variant in inv and inv[variant].get("exists"):
                key = variant if variant != "ct2" else "ct2_int8"
                cluster[key] = {
                    "status": "present",
                    "format": "safetensors" if variant in ["base", "lora"] else "ctranslate2",
                    "size_bytes": None
                }

    return cluster

def compute_consensus(examination_log):
    """Compute consensus section from examination log."""
    if not examination_log:
        return {
            "last_updated": datetime.now().isoformat(),
            "doctors_examined": 0,
            "exams_total": 0,
            "agreements": [],
            "conflicts": [],
            "production_ready": False
        }

    doctors = set(exam["doctor"] for exam in examination_log)

    # Simplified consensus logic
    agreements = []
    conflicts = []

    # Check if base works
    base_works = any(
        exam.get("results", {}).get("base", {}).get("verdict") in ["PASS", "CERTIFIED"]
        for exam in examination_log
    )
    if base_works:
        agreements.append("base works")

    # Check CT2 issues
    ct2_issues = any(
        exam.get("results", {}).get("ct2", {}).get("verdict") == "ERROR" or
        exam.get("results", {}).get("ct2_int8", {}).get("verdict") == "ERROR"
        for exam in examination_log
    )
    if ct2_issues:
        agreements.append("ct2 loader broken")

    production_ready = base_works and not ct2_issues

    return {
        "last_updated": datetime.now().isoformat(),
        "doctors_examined": len(doctors),
        "exams_total": len(examination_log),
        "agreements": agreements,
        "conflicts": conflicts,
        "production_ready": production_ready
    }

def merge_patient(patient_id, source1, source2, source3, source4):
    """Merge all data for a single patient into unified chart."""

    # Determine source language and target language
    source_lang, target_lang = extract_language_info(patient_id)

    # Build examination log
    examination_log = []

    if source1:
        examination_log.extend(build_exam_from_source1(source1, patient_id))

    if source2:
        examination_log.extend(build_exam_from_source2(source2, patient_id))

    if source3:
        examination_log.extend(build_exam_from_source3(source3, patient_id))

    if source4:
        examination_log.extend(build_exam_from_source4(source4, patient_id))

    # Sort exams by date
    examination_log.sort(key=lambda e: e.get("date", ""))

    # Determine admission date (earliest exam)
    admitted = examination_log[0]["date"] if examination_log else datetime.now().isoformat()

    # Determine source repo
    source_repo = None
    if source1 and "provenance" in source1:
        source_repo = source1["provenance"].get("source_repo")
    elif source4:
        source_repo = source4.get("source")
    elif source2 and "lineage" in source2:
        source_repo = source2["lineage"].get("source_repo")

    if not source_repo:
        source_repo = f"Helsinki-NLP/opus-mt-{patient_id}"

    # Build architecture section
    architecture = {}
    if source1 and "architecture" in source1:
        arch = source1["architecture"]
        architecture = {
            "model_type": arch.get("model_type", "MarianMT"),
            "parameters": arch.get("total_parameters"),
            "encoder_layers": arch.get("encoder_layers"),
            "decoder_layers": arch.get("decoder_layers"),
            "max_sequence_length": arch.get("max_sequence_length")
        }
    else:
        architecture = {
            "model_type": "MarianMT",
            "parameters": None,
            "encoder_layers": 6,
            "decoder_layers": 6,
            "max_sequence_length": 512
        }

    # Build unified patient chart
    patient_chart = {
        "_schema": "windstorm_clinic_v1",
        "_last_updated": datetime.now().isoformat(),
        "_clinic_path": f"THE_CLINIC/translation-pairs/{patient_id}.json",

        "patient_id": patient_id,
        "admitted": admitted,
        "source_repo": source_repo,
        "source_language": {
            "code": source_lang,
            "name": source_lang,
            "family": "Unknown"
        },
        "target_language": {
            "code": target_lang,
            "name": target_lang,
            "family": "Unknown"
        },

        "variant_cluster": build_variant_cluster(source1, source2),
        "architecture": architecture,
        "examination_log": examination_log,
        "consensus": compute_consensus(examination_log)
    }

    # Add raw data preservation for anything we might have missed
    patient_chart["_raw_sources"] = {}
    if source1:
        patient_chart["_raw_sources"]["source1_identity"] = source1.get("identity")
    if source2:
        patient_chart["_raw_sources"]["source2_diagnosis"] = source2.get("diagnosis")
    if source3:
        patient_chart["_raw_sources"]["source3_paragraph_source"] = source3.get("paragraph_source")
    if source4:
        patient_chart["_raw_sources"]["source4_verdict"] = source4.get("verdict")

    return patient_chart

def main():
    print("=" * 80)
    print("THE CLINIC — Unified Patient File System Builder")
    print("=" * 80)
    print()

    # Load all sources
    source1_patients = load_source1_data()
    source2_patients = load_source2_data()
    source3_patients = load_source3_data()
    source4_patients = load_source4_data()

    # Collect all unique patient IDs
    all_patient_ids = set()
    all_patient_ids.update(source1_patients.keys())
    all_patient_ids.update(source2_patients.keys())
    all_patient_ids.update(source3_patients.keys())
    all_patient_ids.update(source4_patients.keys())

    print()
    print(f"Total unique patients across all sources: {len(all_patient_ids)}")
    print()

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Track statistics
    stats = {
        "total": len(all_patient_ids),
        "merged": 0,
        "source1_only": 0,
        "source2_only": 0,
        "source3_only": 0,
        "source4_only": 0,
        "all_four_sources": 0,
        "three_sources": 0,
        "two_sources": 0
    }

    # Merge each patient
    print("Merging patient files...")
    for i, patient_id in enumerate(sorted(all_patient_ids), 1):
        if i % 100 == 0:
            print(f"  Progress: {i}/{len(all_patient_ids)}...")

        s1 = source1_patients.get(patient_id)
        s2 = source2_patients.get(patient_id)
        s3 = source3_patients.get(patient_id)
        s4 = source4_patients.get(patient_id)

        # Count source coverage
        sources_present = sum([bool(s1), bool(s2), bool(s3), bool(s4)])
        if sources_present == 4:
            stats["all_four_sources"] += 1
        elif sources_present == 3:
            stats["three_sources"] += 1
        elif sources_present == 2:
            stats["two_sources"] += 1
        elif s1 and not s2 and not s3 and not s4:
            stats["source1_only"] += 1
        elif s2 and not s1 and not s3 and not s4:
            stats["source2_only"] += 1
        elif s3 and not s1 and not s2 and not s4:
            stats["source3_only"] += 1
        elif s4 and not s1 and not s2 and not s3:
            stats["source4_only"] += 1

        # Merge
        try:
            patient_chart = merge_patient(patient_id, s1, s2, s3, s4)

            # Write to file
            output_file = OUTPUT_DIR / f"{patient_id}.json"
            with open(output_file, 'w') as f:
                json.dump(patient_chart, f, indent=2)

            stats["merged"] += 1
        except Exception as e:
            print(f"  ERROR merging {patient_id}: {e}")

    print()
    print("=" * 80)
    print("MERGE COMPLETE")
    print("=" * 80)
    print(f"Total patients: {stats['total']}")
    print(f"Successfully merged: {stats['merged']}")
    print()
    print("Source Coverage:")
    print(f"  All 4 sources: {stats['all_four_sources']}")
    print(f"  3 sources: {stats['three_sources']}")
    print(f"  2 sources: {stats['two_sources']}")
    print(f"  Source 1 only: {stats['source1_only']}")
    print(f"  Source 2 only: {stats['source2_only']}")
    print(f"  Source 3 only: {stats['source3_only']}")
    print(f"  Source 4 only: {stats['source4_only']}")
    print()
    print(f"Output directory: {OUTPUT_DIR}")
    print("=" * 80)

    return 0

if __name__ == "__main__":
    sys.exit(main())

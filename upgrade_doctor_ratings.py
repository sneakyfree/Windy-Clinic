#!/usr/bin/env python3
"""
Upgrade THE CLINIC patient files:
1. Per-doctor star ratings (SEPARATE, not averaged)
2. LoRA identity verification from Herm Zero deep audit
3. Normalize all scores to 5-star half-increment scale

Star scale: raw_score / max_score * 5.0, rounded to nearest 0.5
Each doctor keeps their own rating. Average computed separately.
"""
import json, os, glob
from datetime import datetime, timezone

CLINIC = "/srv/repos/windy-pro/THE_CLINIC/translation-pairs"
DEEP_AUDIT = "/home/user1-gpu/Desktop/grants_folder/windy-pro/audit_results/deep_audit/deep_audit_results_v4.jsonl"
STREPS = "/home/user1-gpu/Desktop/grants_folder/windy-pro/audit_results/streps/streps_results.jsonl"
OC1_V2 = "/home/user1-gpu/Desktop/grants_folder/windy-pro/patient_files_v2"

def to_half_star(raw, max_score=10.0):
    """Convert raw score to 5-star scale, rounded to nearest 0.5"""
    if raw is None: return None
    stars = (float(raw) / max_score) * 5.0
    return round(stars * 2) / 2  # nearest 0.5

def to_half_star_100(raw):
    """Convert 0-100 quality_score to 5-star scale"""
    if raw is None: return None
    return to_half_star(raw, 100.0)

# Load Herm Zero deep audit data (keyed by model_id)
print("Loading Herm Zero deep audit...")
h0_audit = {}
with open(DEEP_AUDIT) as f:
    for line in f:
        d = json.loads(line)
        h0_audit[d["model_id"]] = d
print(f"  Loaded {len(h0_audit)} deep audit records")

# Load STREPS data
print("Loading STREPS data...")
h0_streps = {}
if os.path.exists(STREPS):
    with open(STREPS) as f:
        for line in f:
            d = json.loads(line)
            h0_streps[d.get("model_id", "")] = d
print(f"  Loaded {len(h0_streps)} STREPS records")

# Load OC1 v2 data for provenance enrichment
print("Loading OC1 v2 patient files...")
oc1_data = {}
if os.path.exists(OC1_V2):
    for fn in os.listdir(OC1_V2):
        if fn.endswith('.json'):
            try:
                d = json.load(open(os.path.join(OC1_V2, fn)))
                mid = d.get("identity", {}).get("model_id", "")
                if mid:
                    oc1_data[mid] = d
            except: pass
print(f"  Loaded {len(oc1_data)} OC1 v2 records")

# Process each clinic file
files = sorted(glob.glob(os.path.join(CLINIC, "*.json")))
print(f"\nProcessing {len(files)} clinic files...")

stats = {
    "total": 0, "oc1_rated": 0, "h0_rated": 0, "h0_streps_rated": 0,
    "identity_added": 0, "provenance_enriched": 0, "lora_different": 0,
    "lora_identical": 0
}

for fpath in files:
    with open(fpath) as f:
        patient = json.load(f)

    pid = patient["patient_id"]
    stats["total"] += 1

    # --- 1. Build per-doctor ratings ---
    doctor_ratings = {}

    # Dr. A (Kit OC1) — scores from exam results
    for exam in patient.get("examination_log", []):
        doc = exam.get("doctor", "")
        results = exam.get("results", {})

        if "Kit OC1" in doc:
            doctor_key = "kit_oc1_alpha"
            for variant in ["base", "lora", "ct2"]:
                vr = results.get(variant, {})
                if isinstance(vr, dict) and vr.get("score") is not None:
                    if doctor_key not in doctor_ratings:
                        doctor_ratings[doctor_key] = {
                            "doctor": "Kit OC1 Alpha (Dr. A)",
                            "exams": [],
                            "variant_scores": {}
                        }
                    exam_entry = {
                        "exam_id": exam.get("exam_id"),
                        "variant": variant,
                        "raw_score": vr["score"],
                        "max_score": vr.get("total", 10),
                        "stars": to_half_star(vr["score"], vr.get("total", 10))
                    }
                    doctor_ratings[doctor_key]["exams"].append(exam_entry)
                    # Keep best score per variant
                    existing = doctor_ratings[doctor_key]["variant_scores"].get(variant, {}).get("stars", 0)
                    new_stars = exam_entry["stars"]
                    if new_stars and (not existing or new_stars > existing):
                        doctor_ratings[doctor_key]["variant_scores"][variant] = {
                            "raw_score": vr["score"],
                            "max_score": vr.get("total", 10),
                            "stars": new_stars,
                            "source_exam": exam.get("exam_id")
                        }

    # Also check OC1 v2 source for pre-existing star rating
    if pid in oc1_data:
        qr = oc1_data[pid].get("quality_rating") or {}
        if qr and qr.get("stars"):
            if "kit_oc1_alpha" not in doctor_ratings:
                doctor_ratings["kit_oc1_alpha"] = {
                    "doctor": "Kit OC1 Alpha (Dr. A)",
                    "exams": [],
                    "variant_scores": {}
                }
            doctor_ratings["kit_oc1_alpha"]["oc1_v2_stars"] = round(float(qr["stars"]) * 2) / 2

    # Dr. B (Herm Zero) — from deep audit quality_score (0-100 scale)
    if pid in h0_audit:
        h0 = h0_audit[pid]
        doctor_ratings["herm_zero"] = {
            "doctor": "Herm Zero (Dr. B)",
            "source": "deep_audit_v4",
            "timestamp": h0.get("timestamp"),
            "variant_scores": {}
        }
        for variant in ["base", "lora", "ct2"]:
            vdata = h0.get("variants", {}).get(variant, {})
            if isinstance(vdata, dict):
                qs = vdata.get("quality_checks", {}).get("quality_score")
                if qs is None:
                    qs = vdata.get("quality_score")
                if qs is not None:
                    # Herm Zero deep_audit_v4 quality_score is on 0-100 scale
                    stars = to_half_star_100(qs)
                    doctor_ratings["herm_zero"]["variant_scores"][variant] = {
                        "raw_quality_score": qs,
                        "scale": "0-100",
                        "stars": stars,
                        "status": vdata.get("status", "unknown")
                    }
        # Also store OC1 stars as seen by Herm Zero
        if h0.get("oc1_stars"):
            doctor_ratings["herm_zero"]["oc1_stars_reference"] = h0["oc1_stars"]

        stats["h0_rated"] += 1

    # Dr. B (Herm Zero) — STREPS (separate exam)
    if pid in h0_streps:
        st = h0_streps[pid]
        if "herm_zero_streps" not in doctor_ratings:
            doctor_ratings["herm_zero_streps"] = {
                "doctor": "Herm Zero (Dr. B) — STREPS",
                "source": "streps_stress_test",
                "timestamp": st.get("timestamp"),
                "variant_scores": {}
            }
        for variant in ["base", "lora", "ct2"]:
            vdata = st.get("variants", {}).get(variant, {})
            if isinstance(vdata, dict):
                qs = vdata.get("quality_checks", {}).get("quality_score")
                if qs is not None:
                    stars = to_half_star_100(qs)
                    doctor_ratings["herm_zero_streps"]["variant_scores"][variant] = {
                        "raw_quality_score": qs,
                        "scale": "0-100",
                        "stars": stars,
                        "status": vdata.get("status", "unknown")
                    }
        stats["h0_streps_rated"] += 1

    if "kit_oc1_alpha" in doctor_ratings:
        stats["oc1_rated"] += 1

    # --- 2. LoRA identity verification ---
    identity_check = None
    if pid in h0_audit:
        ic = h0_audit[pid].get("identity_check", {})
        if ic:
            identical = ic.get("files_identical", None)
            identity_check = {
                "base_hash": ic.get("base_hash"),
                "lora_hash": ic.get("lora_hash"),
                "files_identical": identical,
                "base_size_mb": ic.get("base_size_mb"),
                "lora_size_mb": ic.get("lora_size_mb"),
                "verified_by": "Herm Zero (Dr. B) deep_audit_v4",
                "verification_date": h0_audit[pid].get("timestamp")
            }
            if identical == False:
                identity_check["legal_status"] = "DISTINCT_BINARY — LoRA weights differ from base (different SHA-256)"
                stats["lora_different"] += 1
            elif identical == True:
                identity_check["legal_status"] = "IDENTICAL — LoRA weights match base exactly"
                stats["lora_identical"] += 1
            stats["identity_added"] += 1

    # --- 3. Provenance enrichment from OC1 v2 ---
    if pid in oc1_data:
        prov = oc1_data[pid].get("provenance", {})
        if prov.get("download_date") and not patient.get("provenance", {}).get("download_date"):
            if "provenance" not in patient:
                patient["provenance"] = {}
            patient["provenance"]["download_date"] = prov["download_date"]
            patient["provenance"]["original_license"] = prov.get("original_license")
            patient["provenance"]["is_pivot_model"] = prov.get("is_pivot_model")
            patient["provenance"]["downloaded_by"] = "Kit OC1 Alpha (batch download pipeline)"
            stats["provenance_enriched"] += 1

    # --- 4. Write into patient file ---
    patient["doctor_ratings"] = doctor_ratings
    if identity_check:
        patient["lora_identity_check"] = identity_check

    # Update last_updated
    patient["_last_updated"] = datetime.now(timezone.utc).isoformat()

    with open(fpath, "w") as f:
        json.dump(patient, f, indent=2, default=str, ensure_ascii=False)

# Print stats
print(f"\n{'='*60}")
print(f"UPGRADE COMPLETE")
print(f"{'='*60}")
print(f"Total files processed:     {stats['total']}")
print(f"Kit OC1 rated:             {stats['oc1_rated']}")
print(f"Herm Zero rated:           {stats['h0_rated']}")
print(f"Herm Zero STREPS rated:    {stats['h0_streps_rated']}")
print(f"Identity checks added:     {stats['identity_added']}")
print(f"  LoRA DIFFERENT from base:{stats['lora_different']}")
print(f"  LoRA IDENTICAL to base:  {stats['lora_identical']}")
print(f"Provenance enriched:       {stats['provenance_enriched']}")

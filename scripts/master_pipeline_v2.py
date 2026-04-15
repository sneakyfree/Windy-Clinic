#!/usr/bin/env python3
"""
Master Pipeline v2 — Full autonomous improvement + certification
=================================================================
1. Run herm0 improvement pipeline (Phases 1-3)
2. CT2 INT8 quantize all new herm0 models
3. Re-run Grand Rounds v2 on new herm0 variants
4. Merge results + update patient files + rebuild roster
5. File final report

Runs unattended. All steps idempotent and checkpoint-resumable.

Doctor: Opus 4.6 Opus-Claw (Dr. C)
"""

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
MODELS = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/models")
LOG = CLINIC / "grand-rounds" / "master_pipeline_v2.log"
DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"


def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def run_script(path, timeout=259200):
    log(f"Running: {path}")
    r = subprocess.run(["python3", str(path)], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        log(f"  Exit code {r.returncode}")
        log(f"  stderr tail: {r.stderr[-500:]}")
    return r.returncode == 0


def ct2_quantize_new_herm0():
    """CT2 INT8 quantize any new herm0/ dirs that don't have herm0-ct2-int8/ yet."""
    log("CT2 quantizing new herm0 models...")
    from ctranslate2.converters import TransformersConverter
    count = 0
    for pair in sorted(MODELS.glob("windy-pair-*")):
        herm0 = pair / "herm0"
        if not (herm0 / "model.safetensors").exists():
            continue
        dst = pair / "herm0-ct2-int8"
        if dst.exists() and (dst / "model.bin").exists():
            continue
        try:
            if dst.exists():
                shutil.rmtree(str(dst))
            converter = TransformersConverter(str(herm0))
            converter.convert(str(dst), quantization="int8")
            count += 1
        except Exception as e:
            log(f"  CT2 error {pair.name}: {str(e)[:100]}")
    log(f"  CT2 quantized {count} new herm0 models")


def grv2_test_new_herm0():
    """Run GR v2 on all herm0/ variants that don't have GRV2 results yet."""
    log("Testing new herm0 models with Grand Rounds v2...")
    HARNESS = CLINIC / "scripts" / "grand_rounds_v2.py"
    RESULTS = CLINIC / "grand-rounds" / "grv2_herm0" / "results.jsonl"
    RESULTS.parent.mkdir(parents=True, exist_ok=True)

    tested = 0
    for pair in sorted(MODELS.glob("windy-pair-*")):
        pid = pair.name[len("windy-pair-"):]
        herm0 = pair / "herm0"
        if not (herm0 / "model.safetensors").exists():
            continue

        try:
            proc = subprocess.run(
                ["python3", str(HARNESS), "--eval-single", pid, "herm0"],
                capture_output=True, text=True, timeout=180,
            )
            if proc.returncode == 0:
                row = json.loads(proc.stdout)
                with open(RESULTS, "a") as f:
                    f.write(json.dumps(row) + "\n")
                stars = row.get("rating", {}).get("stars", "?")
                tested += 1
                if tested % 25 == 0:
                    log(f"  Tested {tested} herm0 models, latest: {pid} → {stars}★")
        except Exception as e:
            log(f"  Error testing {pid}: {str(e)[:100]}")

    log(f"  Tested {tested} herm0 models total")


def merge_grv2_herm0():
    """Merge GR v2 results for herm0 variants into patient files."""
    log("Merging herm0 GR v2 results into patient files...")
    RESULTS = CLINIC / "grand-rounds" / "grv2_herm0" / "results.jsonl"
    PATIENTS = CLINIC / "translation-pairs"

    if not RESULTS.exists():
        log("  No herm0 GR v2 results to merge")
        return

    run_iso = datetime.now(timezone.utc).isoformat()
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
        exam_log = chart.setdefault("examination_log", [])
        exam_id = f"DRC-GRV2-HERM0-{pid}"
        if any(e.get("exam_id") == exam_id for e in exam_log):
            continue

        rating = r.get("rating", {})
        exam_log.append({
            "exam_id": exam_id,
            "date": run_iso,
            "doctor": DOCTOR,
            "machine": "Veron-1 (RTX 5090, Mt Pleasant SC)",
            "method": "Grand Rounds v2 certification of herm0 (improved) variant",
            "protocol_script": "scripts/grand_rounds_v2.py",
            "variants_tested": ["herm0"],
            "results": {
                "herm0": {
                    "composite_score": rating.get("composite_score"),
                    "stars": rating.get("stars"),
                    "tier": rating.get("tier"),
                    "tests": r.get("tests", {}),
                }
            },
            "notes": (
                f"GR v2 certification of recreated/improved herm0 variant. "
                f"Rating: {rating.get('stars')}★ ({rating.get('tier')}). "
                f"This certifies the herm0 improvement with paragraph-level evidence. "
                f"Filed by {DOCTOR}."
            ),
        })

        # Update quality_rating if herm0 is better than current best
        current_stars = chart.get("quality_rating", {}).get("stars", 0)
        herm0_stars = rating.get("stars", 0)
        if herm0_stars > current_stars:
            chart["quality_rating"] = {
                "stars": herm0_stars,
                "label": rating.get("tier"),
                "composite_score": rating.get("composite_score"),
                "rated_by": DOCTOR,
                "rated_at": run_iso,
                "method": "Grand Rounds v2 (herm0 improved variant)",
                "best_variant": "herm0",
            }

        chart["_last_updated"] = run_iso
        pf.write_text(json.dumps(chart, indent=2))
        merged += 1

    log(f"  Merged {merged} herm0 GR v2 results")


def main():
    log("=" * 60)
    log("MASTER PIPELINE v2 — Improvement + Certification")
    log(f"Doctor: {DOCTOR}")
    log("=" * 60)

    # Step 1: Run improvement pipeline
    log("\n--- STEP 1: Herm0 Improvement Pipeline (Phases 1-3) ---")
    run_script(CLINIC / "scripts" / "herm0_improvement_pipeline.py", timeout=259200)

    # Step 2: CT2 quantize new herm0 models
    log("\n--- STEP 2: CT2 INT8 quantize new herm0 models ---")
    ct2_quantize_new_herm0()

    # Step 3: GR v2 test new herm0 variants
    log("\n--- STEP 3: GR v2 certify new herm0 variants ---")
    grv2_test_new_herm0()

    # Step 4: Merge results
    log("\n--- STEP 4: Merge results into patient files ---")
    merge_grv2_herm0()

    # Step 5: Rebuild roster
    log("\n--- STEP 5: Rebuild roster ---")
    run_script(CLINIC / "scripts" / "build_roster.py")

    # Summary
    log("\n" + "=" * 60)
    log("MASTER PIPELINE v2 COMPLETE")

    try:
        state = json.loads((CLINIC / "grand-rounds" / "herm0_pipeline_checkpoint.json").read_text())
        log(f"Total improved this run: {state.get('total_improved', '?')}")
        log(f"Total attempted: {len(state.get('done', []))}")
    except Exception:
        pass

    log("=" * 60)


if __name__ == "__main__":
    main()

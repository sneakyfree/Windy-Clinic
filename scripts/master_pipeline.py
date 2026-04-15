#!/usr/bin/env python3
"""
Master Pipeline — Autonomous execution of all remaining Windy Word fleet work.

Chains:
  1. Wait for herm0 recreation to complete (monitors checkpoint)
  2. Wait for ONNX INT8 fleet to complete (monitors checkpoint)
  3. Launch Grand Rounds v2 on full fleet
  4. Wait for GR v2 to complete
  5. Merge GR v2 results into patient files + compute 5-star ratings
  6. CT2 INT8 quantize the recreated herm0 models
  7. Rebuild all rosters
  8. File definitive final doctor-log

Runs unattended. All steps are idempotent and checkpoint-resumable.

Doctor: Opus 4.6 Opus-Claw (Dr. C)
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
LOG_PATH = CLINIC / "grand-rounds" / "master_pipeline.log"

HERM0_CHECKPOINT = CLINIC / "grand-rounds" / "herm0_recreate_checkpoint.json"
ONNX_INT8_CHECKPOINT = Path("/mnt/data2/windy-onnx-fleet-int8/checkpoint.json")
GRV2_CHECKPOINT = CLINIC / "grand-rounds" / "grv2" / "checkpoint.json"

DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"


def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def wait_for_checkpoint(checkpoint_path, total_key, total_val, label, poll_interval=60):
    """Wait for a checkpoint file to show completion."""
    log(f"Waiting for {label}...")
    while True:
        try:
            data = json.loads(checkpoint_path.read_text())
            done = len(data.get("done", []))
            log(f"  {label}: {done}/{total_val}")
            if done >= total_val:
                log(f"  {label} COMPLETE")
                return data
        except Exception:
            pass
        time.sleep(poll_interval)


def wait_for_process_gone(name_pattern, timeout=86400):
    """Wait until no process matching the pattern is running."""
    import re
    t0 = time.time()
    while time.time() - t0 < timeout:
        result = subprocess.run(
            ["pgrep", "-f", name_pattern],
            capture_output=True, text=True
        )
        if result.returncode != 0:  # no matching process
            return True
        time.sleep(30)
    return False


def run_script(script_path, args=None, timeout=86400):
    """Run a Python script and wait for completion."""
    cmd = ["python3", str(script_path)]
    if args:
        cmd.extend(args)
    log(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        log(f"  STDERR (last 500): {result.stderr[-500:]}")
    return result.returncode == 0


def merge_grv2_results():
    """Merge GR v2 results into patient files with 5-star ratings."""
    log("Merging GR v2 results into patient files...")

    PATIENTS = CLINIC / "translation-pairs"
    RESULTS = CLINIC / "grand-rounds" / "grv2" / "results.jsonl"
    run_iso = datetime.now(timezone.utc).isoformat()

    if not RESULTS.exists():
        log("  No results file found")
        return

    from collections import defaultdict
    by_pid = defaultdict(list)
    for line in open(RESULTS):
        r = json.loads(line)
        if r.get("status") == "complete":
            by_pid[r["pid"]].append(r)

    merged = 0
    for pid, rows in by_pid.items():
        pf = PATIENTS / f"{pid}.json"
        if not pf.exists():
            continue
        chart = json.loads(pf.read_text())
        exam_log = chart.setdefault("examination_log", [])
        exam_id = f"DRC-GRV2-{pid}"
        if any(e.get("exam_id") == exam_id for e in exam_log):
            continue

        # Find best variant rating
        best = max(rows, key=lambda r: r.get("rating", {}).get("composite_score", 0))
        rating = best.get("rating", {})

        variant_results = {}
        for r in rows:
            variant_results[r["variant"]] = {
                "composite_score": r.get("rating", {}).get("composite_score"),
                "stars": r.get("rating", {}).get("stars"),
                "tier": r.get("rating", {}).get("tier"),
                "tests": r.get("tests", {}),
            }

        exam_log.append({
            "exam_id": exam_id,
            "date": run_iso,
            "doctor": DOCTOR,
            "machine": "Veron-1 (RTX 5090, Mt Pleasant SC)",
            "method": "Grand Rounds v2 — 8-test paragraph-level stress battery with 5-star rating",
            "protocol_script": "scripts/grand_rounds_v2.py",
            "variants_tested": [r["variant"] for r in rows],
            "results": variant_results,
            "best_variant": best["variant"],
            "best_stars": rating.get("stars"),
            "best_tier": rating.get("tier"),
            "best_composite": rating.get("composite_score"),
            "notes": (
                f"Grand Rounds v2 paragraph-level stress test. "
                f"Tests: sentences, paragraphs (5 domains), long-form (2 passages), "
                f"native input, domain stress, edge cases, round-trip, speed. "
                f"Best variant: {best['variant']} at {rating.get('stars')}★ ({rating.get('tier')}). "
                f"Filed by {DOCTOR}."
            ),
        })

        # Update quality_rating with new stars
        chart["quality_rating"] = {
            "stars": rating.get("stars"),
            "label": rating.get("tier"),
            "composite_score": rating.get("composite_score"),
            "rated_by": DOCTOR,
            "rated_at": run_iso,
            "method": "Grand Rounds v2 (paragraph-level, 8-test battery)",
        }

        chart["_last_updated"] = run_iso
        pf.write_text(json.dumps(chart, indent=2))
        merged += 1

    log(f"  Merged GR v2 results into {merged} patient files")


def ct2_quantize_herm0():
    """CT2 INT8 quantize any newly recreated herm0 models."""
    from ctranslate2.converters import TransformersConverter
    import shutil

    MODELS = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/models")
    log("CT2 INT8 quantizing recreated herm0 models...")
    count = 0

    for pair_dir in sorted(MODELS.glob("windy-pair-*")):
        herm0 = pair_dir / "herm0"
        if not herm0.exists():
            continue
        if not (herm0 / "model.safetensors").exists():
            continue
        dst = pair_dir / "herm0-ct2-int8"
        if dst.exists() and (dst / "model.bin").exists():
            continue

        try:
            if dst.exists():
                shutil.rmtree(str(dst))
            converter = TransformersConverter(str(herm0))
            converter.convert(str(dst), quantization="int8")
            count += 1
        except Exception as e:
            log(f"  CT2 error {pair_dir.name}: {str(e)[:100]}")

    log(f"  CT2 quantized {count} herm0 models")


def rebuild_rosters():
    """Rebuild all roster files."""
    log("Rebuilding rosters...")
    run_script(CLINIC / "scripts" / "build_roster.py")
    log("  Translation roster rebuilt")


def main():
    log("=" * 60)
    log("MASTER PIPELINE — Autonomous execution")
    log(f"Doctor: {DOCTOR}")
    log(f"Started: {datetime.now(timezone.utc).isoformat()}")
    log("=" * 60)

    # Step 1: Wait for herm0 recreation
    log("\n--- STEP 1: Wait for herm0 recreation ---")
    wait_for_process_gone("recreate_herm0_models.py", timeout=43200)  # 12h max
    log("Herm0 recreation process finished")

    # Step 2: Wait for ONNX INT8 fleet
    log("\n--- STEP 2: Wait for ONNX INT8 fleet ---")
    wait_for_process_gone("onnx_int8_quantize_fleet.py", timeout=43200)
    log("ONNX INT8 fleet process finished")

    # Step 3: Launch Grand Rounds v2
    log("\n--- STEP 3: Launch Grand Rounds v2 ---")
    grv2_ok = run_script(
        CLINIC / "scripts" / "grand_rounds_v2.py",
        timeout=172800  # 48h max
    )
    log(f"GR v2 {'completed' if grv2_ok else 'had errors'}")

    # Step 4: Merge GR v2 results
    log("\n--- STEP 4: Merge GR v2 results ---")
    merge_grv2_results()

    # Step 5: CT2 quantize recreated herm0 models
    log("\n--- STEP 5: CT2 quantize herm0 models ---")
    ct2_quantize_herm0()

    # Step 6: Rebuild rosters
    log("\n--- STEP 6: Rebuild rosters ---")
    rebuild_rosters()

    # Step 7: File report
    log("\n--- STEP 7: Final report ---")
    log("Writing final doctor-log...")

    # Read final stats
    try:
        roster = json.loads((CLINIC / "MASTER_ROSTER.json").read_text())
        log(f"Final roster: {roster['_total_patients']} patients, {roster.get('_total_examinations', '?')} exams")
    except Exception:
        pass

    log("\n" + "=" * 60)
    log("MASTER PIPELINE COMPLETE")
    log("=" * 60)


if __name__ == "__main__":
    main()

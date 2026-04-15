#!/usr/bin/env python3
"""
Post-Phase 4 Orchestrator
==========================
Waits for the parallel Phase 4 pipeline to complete, then runs:
  1. CT2 INT8 quantize all herm0/ without herm0-ct2-int8/
  2. GR v2 re-certify all herm0 variants (subprocess-isolated)
  3. Merge GR v2 herm0 results into patient files + 5-star ratings
  4. Rebuild roster
  5. File final doctor log

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
PATIENTS = CLINIC / "translation-pairs"
LOG = CLINIC / "grand-rounds" / "post_phase4_orchestrator.log"
DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"


def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def wait_for_phase4_done():
    """Wait until the parallel Phase 4 pipeline is done (no active workers, all targets done)."""
    log("Waiting for Phase 4 parallel pipeline to complete...")
    poll_count = 0
    while True:
        # Check if workers are still running
        r = subprocess.run(["pgrep", "-f", "herm0_pipeline_parallel"], capture_output=True)
        workers_alive = r.returncode == 0
        if not workers_alive:
            log("No Phase 4 workers running. Moving to Step 2.")
            return
        # Also check checkpoint state
        cp_path = CLINIC / "grand-rounds" / "herm0_pipeline_checkpoint.json"
        if cp_path.exists():
            cp = json.loads(cp_path.read_text())
            targets = set(cp.get("targets", []))
            done = set(cp.get("done", []))
            remaining = targets - done
            if not remaining:
                log("All Phase 4 targets done. Moving to Step 2.")
                return
            poll_count += 1
            if poll_count % 12 == 0:  # every ~10 minutes
                log(f"Phase 4: {len(done)} done, {len(remaining)} remaining. Still waiting.")
        time.sleep(60)


def step2_ct2_quantize():
    """CT2 INT8 quantize all herm0/ models that don't have herm0-ct2-int8/ yet."""
    log("\n=== STEP 2: CT2 INT8 quantize new herm0 models ===")
    from ctranslate2.converters import TransformersConverter

    count = 0
    errors = 0
    targets = list(MODELS.glob("windy-pair-*/herm0/model.safetensors"))
    log(f"Found {len(targets)} herm0 models total")

    for sf in targets:
        pair = sf.parent.parent
        pid = pair.name[len("windy-pair-"):]
        src = pair / "herm0"
        dst = pair / "herm0-ct2-int8"
        if dst.exists() and (dst / "model.bin").exists():
            continue

        try:
            if dst.exists():
                shutil.rmtree(str(dst))
            converter = TransformersConverter(str(src))
            converter.convert(str(dst), quantization="int8")
            count += 1

            # Update patient file
            pf = PATIENTS / f"{pid}.json"
            if pf.exists():
                chart = json.loads(pf.read_text())
                vc = chart.setdefault("variant_cluster", {})
                size_mb = sum(f.stat().st_size for f in dst.rglob("*") if f.is_file()) / (1024*1024)
                vc["herm0_ct2_int8"] = {
                    "status": "present",
                    "format": "ctranslate2_int8",
                    "derived_from": "herm0/ (OPUS deep fine-tune)",
                    "on_disk_path": str(dst),
                    "on_disk_bytes": int(size_mb * 1024 * 1024),
                    "quantized_at": datetime.now(timezone.utc).isoformat(),
                    "quantized_by": DOCTOR,
                }
                log_list = chart.setdefault("examination_log", [])
                exam_id = f"DRC-HERM0CT2-{pid}"
                if not any(e.get("exam_id") == exam_id for e in log_list):
                    log_list.append({
                        "exam_id": exam_id,
                        "date": datetime.now(timezone.utc).isoformat(),
                        "doctor": DOCTOR,
                        "machine": "Veron-1 (RTX 5090, Mt Pleasant SC)",
                        "method": "CTranslate2 INT8 quantization of herm0/ (deeply-improved proprietary weights)",
                        "protocol_script": "scripts/post_phase4_orchestrator.py",
                        "notes": f"Quantized herm0/model.safetensors → herm0-ct2-int8/model.bin ({size_mb:.0f} MB, ~25% of source). Filed by {DOCTOR}.",
                    })
                chart["_last_updated"] = datetime.now(timezone.utc).isoformat()
                pf.write_text(json.dumps(chart, indent=2))

            if count % 25 == 0:
                log(f"  CT2 quantized {count} models...")
        except Exception as e:
            errors += 1
            log(f"  CT2 error {pid}: {str(e)[:100]}")

    log(f"Step 2 done: {count} quantized, {errors} errors")


def step3_grv2_certify():
    """Run GR v2 on all herm0 variants (subprocess-isolated)."""
    log("\n=== STEP 3: GR v2 re-certify herm0 variants ===")
    HARNESS = CLINIC / "scripts" / "grand_rounds_v2.py"
    OUT = CLINIC / "grand-rounds" / "grv2_herm0"
    OUT.mkdir(parents=True, exist_ok=True)
    RESULTS = OUT / "results.jsonl"

    # Build list of herm0 variants to test
    targets = []
    for sf in MODELS.glob("windy-pair-*/herm0/model.safetensors"):
        pid = sf.parent.parent.name[len("windy-pair-"):]
        targets.append(pid)

    # Load existing results
    done = set()
    if RESULTS.exists():
        for line in open(RESULTS):
            r = json.loads(line)
            if r.get("status") == "complete":
                done.add(r.get("pid"))

    remaining = [pid for pid in targets if pid not in done]
    log(f"Target herm0 variants: {len(targets)}, already tested: {len(done)}, remaining: {len(remaining)}")

    tested = 0
    for pid in remaining:
        try:
            proc = subprocess.run(
                ["python3", str(HARNESS), "--eval-single", pid, "herm0"],
                capture_output=True, text=True, timeout=180,
            )
            if proc.returncode == 0:
                row = json.loads(proc.stdout)
                with open(RESULTS, "a") as f:
                    f.write(json.dumps(row) + "\n")
                tested += 1
                if tested % 25 == 0:
                    stars = row.get("rating", {}).get("stars", "?")
                    log(f"  Tested {tested} herm0 models, latest: {pid} → {stars}★")
        except Exception as e:
            log(f"  GR v2 error {pid}: {str(e)[:100]}")

    log(f"Step 3 done: {tested} new certifications")


def step4_merge_grv2_herm0():
    """Merge GR v2 herm0 certifications into patient files."""
    log("\n=== STEP 4: Merge GR v2 herm0 results into patient files ===")
    RESULTS = CLINIC / "grand-rounds" / "grv2_herm0" / "results.jsonl"
    if not RESULTS.exists():
        log("  No GR v2 results to merge")
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
        log_list = chart.setdefault("examination_log", [])
        exam_id = f"DRC-GRV2-HERM0-{pid}"
        if any(e.get("exam_id") == exam_id for e in log_list):
            continue

        rating = r.get("rating", {})
        log_list.append({
            "exam_id": exam_id,
            "date": run_iso,
            "doctor": DOCTOR,
            "machine": "Veron-1 (RTX 5090, Mt Pleasant SC)",
            "method": "Grand Rounds v2 certification of herm0 (OPUS-improved) variant",
            "protocol_script": "scripts/grand_rounds_v2.py via post_phase4_orchestrator.py",
            "variants_tested": ["herm0"],
            "results": {"herm0": {
                "composite_score": rating.get("composite_score"),
                "stars": rating.get("stars"),
                "tier": rating.get("tier"),
                "tests": r.get("tests", {}),
            }},
            "notes": (
                f"GR v2 certification of herm0 (proprietary deeply-improved) variant. "
                f"Rating: {rating.get('stars')}★ ({rating.get('tier')}). "
                f"Filed by {DOCTOR}."
            ),
        })

        # Update quality_rating if herm0 is better
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


def step5_rebuild_roster():
    """Rebuild roster."""
    log("\n=== STEP 5: Rebuild roster ===")
    r = subprocess.run(["python3", str(CLINIC / "scripts" / "build_roster.py")],
                        capture_output=True, text=True)
    log(f"  Roster rebuilt (exit {r.returncode})")


def main():
    log("=" * 60)
    log("POST-PHASE 4 ORCHESTRATOR")
    log(f"Doctor: {DOCTOR}")
    log("=" * 60)

    wait_for_phase4_done()
    step2_ct2_quantize()
    step3_grv2_certify()
    step4_merge_grv2_herm0()
    step5_rebuild_roster()

    log("\n" + "=" * 60)
    log("POST-PHASE 4 ORCHESTRATOR COMPLETE")
    log("=" * 60)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Phase 3b — Full-fleet base variant re-run (after partners restored).

Uses phase3a_retest.py's driver pattern but with a different target list:
every base model that has safetensors on disk (including the restored set).

Run this AFTER link_restored_to_models.py has populated the restored bases.

Doctor: Opus 4.6 Opus-Claw (Dr. C)
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HARNESS = "/home/user1-gpu/Desktop/grants_folder/windy-pro/grand_rounds_harness.py"
HARNESS_CWD = "/home/user1-gpu/Desktop/grants_folder/windy-pro"
MODELS_DIR = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/models")

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
OUT_DIR = CLINIC / "grand-rounds" / "phase3b_fullfleet"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_JSONL = OUT_DIR / "phase3b_results.jsonl"
CHECKPOINT = OUT_DIR / "phase3b_checkpoint.json"
LOG_PATH = OUT_DIR / "phase3b_run.log"

DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"
PER_MODEL_TIMEOUT_S = 300


def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def enumerate_targets():
    """Find all windy-pair-*/base dirs that look loadable."""
    targets = []
    for pair_dir in sorted(MODELS_DIR.glob("windy-pair-*")):
        base = pair_dir / "base"
        if not base.exists():
            continue
        if (base / "config.json").exists() and (
            (base / "pytorch_model.bin").exists() or (base / "model.safetensors").exists()
        ):
            pid = pair_dir.name[len("windy-pair-"):]
            targets.append(pid)
    return targets


def run_one(pid):
    import time
    t0 = time.time()
    try:
        proc = subprocess.run(
            ["python3", HARNESS, "--eval-single", f"windy-pair-{pid}", "base"],
            cwd=HARNESS_CWD, capture_output=True, text=True, timeout=PER_MODEL_TIMEOUT_S,
        )
        if proc.returncode != 0:
            return {"pid": pid, "status": "harness_error", "stderr_tail": proc.stderr[-500:]}
        row = json.loads(proc.stdout)
        row["pid"] = pid
        row["status"] = "complete"
        row["_phase3b_filed_by"] = DOCTOR
        row["_phase3b_filed_at"] = datetime.now(timezone.utc).isoformat()
        row["_phase3b_elapsed_s"] = round(time.time() - t0, 1)
        return row
    except subprocess.TimeoutExpired:
        return {"pid": pid, "status": "timeout"}
    except Exception as e:
        return {"pid": pid, "status": "driver_error", "error": str(e)}


def main():
    targets = enumerate_targets()
    log(f"Phase 3b full fleet — {len(targets)} base variants")

    state = {}
    if CHECKPOINT.exists():
        state = json.loads(CHECKPOINT.read_text())
    done = set(state.get("done", []))

    remaining = [t for t in targets if t not in done]
    log(f"Remaining: {len(remaining)}")

    for i, pid in enumerate(remaining, 1):
        log(f"[{i}/{len(remaining)}] {pid}")
        r = run_one(pid)
        with open(RESULTS_JSONL, "a") as f:
            f.write(json.dumps(r) + "\n")
        if r.get("status") == "complete":
            done.add(pid)
            log(f"    {r.get('composite_grade')}/{r.get('composite_score')}")
        else:
            log(f"    ERROR {r.get('status')}")
        state["done"] = list(done)
        CHECKPOINT.write_text(json.dumps(state, indent=2))

    log(f"Phase 3b done: {len(done)}/{len(targets)}")


if __name__ == "__main__":
    main()

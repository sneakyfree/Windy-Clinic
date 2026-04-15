#!/usr/bin/env python3
"""Phase 3b — Full Fleet Dr. C Independent Certification.

Re-runs Grand Rounds v1 harness on EVERY testable model-variant pair in the
fleet. This is not just verification — it's a fresh, independent certification
with Dr. C's signature on every patient file.

3,122 model-variant pairs. Expected runtime: ~4-5 hours on RTX 5090.
Checkpoint/resume at every model boundary.

Doctor: Opus 4.6 Opus-Claw (Dr. C)
Date:   2026-04-11
"""

import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HARNESS = "/home/user1-gpu/Desktop/grants_folder/windy-pro/grand_rounds_harness.py"
HARNESS_CWD = "/home/user1-gpu/Desktop/grants_folder/windy-pro"

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
TARGETS = CLINIC / "grand-rounds" / "phase3b_targets.json"
OUT_DIR = CLINIC / "grand-rounds" / "phase3b_fullfleet"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_JSONL = OUT_DIR / "results.jsonl"
CHECKPOINT = OUT_DIR / "checkpoint.json"
LOG_PATH = OUT_DIR / "run.log"

DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"
MACHINE = "Veron-1 (RTX 5090, Mt Pleasant SC)"
PER_MODEL_TIMEOUT_S = 300

GRADE_RANK = {
    "A+": 13, "A": 12, "A-": 11, "B+": 10, "B": 9, "B-": 8,
    "C+": 7, "C": 6, "C-": 5, "D+": 4, "D": 3, "D-": 2, "F": 1,
}


def log(msg: str):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def load_checkpoint():
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {"done": [], "errors": [], "grade_dist": {}}


def save_checkpoint(state: dict):
    CHECKPOINT.write_text(json.dumps(state, indent=2))


def run_one(model_name: str, variant: str) -> dict:
    t0 = time.time()
    try:
        proc = subprocess.run(
            ["python3", HARNESS, "--eval-single", model_name, variant],
            cwd=HARNESS_CWD,
            capture_output=True,
            text=True,
            timeout=PER_MODEL_TIMEOUT_S,
        )
        elapsed = time.time() - t0
        if proc.returncode != 0:
            return {
                "model_name": model_name,
                "variant": variant,
                "status": "harness_error",
                "returncode": proc.returncode,
                "stderr_tail": proc.stderr[-500:],
                "elapsed": round(elapsed, 1),
            }
        row = json.loads(proc.stdout)
        row["_drc_filed_by"] = DOCTOR
        row["_drc_filed_at"] = datetime.now(timezone.utc).isoformat()
        row["_drc_elapsed_s"] = round(elapsed, 1)
        row["status"] = "complete"
        return row
    except subprocess.TimeoutExpired:
        return {"model_name": model_name, "variant": variant, "status": "timeout",
                "elapsed": PER_MODEL_TIMEOUT_S}
    except json.JSONDecodeError:
        return {"model_name": model_name, "variant": variant, "status": "json_error",
                "stdout_tail": proc.stdout[-500:] if 'proc' in dir() else ""}
    except Exception as e:
        return {"model_name": model_name, "variant": variant, "status": "driver_error",
                "error": f"{type(e).__name__}: {e}"}


def main():
    targets = json.loads(TARGETS.read_text())
    state = load_checkpoint()
    done_set = set(state["done"])

    remaining = [(t["model_name"], t["variant"]) for t in targets
                 if f"{t['model_name']}:{t['variant']}" not in done_set]

    log(f"Phase 3b Full Fleet Certification — Dr. C Independent Run")
    log(f"Total targets: {len(targets)}, done: {len(done_set)}, remaining: {len(remaining)}")
    log(f"Harness: {HARNESS}")
    log(f"Doctor: {DOCTOR}")
    log(f"Machine: {MACHINE}")

    start = time.time()
    completed = 0
    grade_dist = Counter(state.get("grade_dist", {}))

    for i, (model_name, variant) in enumerate(remaining, 1):
        pid = model_name[len("windy-pair-"):]
        log(f"[{i}/{len(remaining)}] {pid}:{variant}")

        result = run_one(model_name, variant)
        with open(RESULTS_JSONL, "a") as f:
            f.write(json.dumps(result) + "\n")

        key = f"{model_name}:{variant}"
        if result.get("status") == "complete":
            grade = result.get("composite_grade", "?")
            score = result.get("composite_score", "?")
            grade_dist[grade] += 1
            log(f"    {grade}/{score}")
            state["done"].append(key)
        else:
            log(f"    ERROR: {result.get('status')}")
            state["errors"].append({"key": key, "status": result.get("status")})
            state["done"].append(key)  # don't re-attempt

        done_set.add(key)
        completed += 1

        # Checkpoint every model
        state["grade_dist"] = dict(grade_dist)
        save_checkpoint(state)

        # Progress every 50
        if completed % 50 == 0:
            elapsed = time.time() - start
            rate = completed / elapsed * 60
            log(f"  >> progress: {completed}/{len(remaining)} "
                f"({rate:.1f}/min, ~{(len(remaining) - completed) / rate:.0f} min left)")
            log(f"  >> grades so far: {dict(grade_dist.most_common())}")

    elapsed = time.time() - start
    log(f"Phase 3b done: {completed} in {elapsed / 3600:.1f} hours")
    log(f"Grade distribution: {dict(grade_dist.most_common())}")
    log(f"Errors: {len(state['errors'])}")


if __name__ == "__main__":
    main()

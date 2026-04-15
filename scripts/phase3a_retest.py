#!/usr/bin/env python3
"""Phase 3a — Independent re-test of failing base models.

Calls Herm Zero's grand_rounds_harness.py --eval-single MODEL base for each of
the 230 failing base models that still have safetensors on disk. Collects
results into a fresh JSONL, compares against GR1, and records a signed Dr. C
exam in each patient file.

This is independent execution of the SAME harness. If grades match GR1, that's
evidence the original results are trustworthy. If grades disagree, that's a
methodology bug that needs investigation.

Doctor: Opus 4.6 Opus-Claw (Dr. C)
Date:   2026-04-11
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HARNESS = "/home/user1-gpu/Desktop/grants_folder/windy-pro/grand_rounds_harness.py"
HARNESS_CWD = "/home/user1-gpu/Desktop/grants_folder/windy-pro"

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
OUT_DIR = CLINIC / "grand-rounds" / "phase3a_retest"
OUT_DIR.mkdir(parents=True, exist_ok=True)
TARGETS_JSON = CLINIC / "grand-rounds" / "phase3a_targets.json"
RESULTS_JSONL = OUT_DIR / "phase3a_retest_results.jsonl"
CHECKPOINT = OUT_DIR / "phase3a_checkpoint.json"
LOG_PATH = OUT_DIR / "phase3a_run.log"

DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"
MACHINE = "Veron-1 (RTX 5090, Mt Pleasant SC)"

PER_MODEL_TIMEOUT_S = 300  # 5 min per model


def log(msg: str):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def load_checkpoint():
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {"done": [], "errors": []}


def save_checkpoint(state: dict):
    CHECKPOINT.write_text(json.dumps(state, indent=2))


def run_one(pid: str) -> dict:
    model_name = f"windy-pair-{pid}"
    t0 = time.time()
    try:
        proc = subprocess.run(
            ["python3", HARNESS, "--eval-single", model_name, "base"],
            cwd=HARNESS_CWD,
            capture_output=True,
            text=True,
            timeout=PER_MODEL_TIMEOUT_S,
        )
        elapsed = time.time() - t0
        if proc.returncode != 0:
            return {
                "pid": pid,
                "status": "harness_error",
                "returncode": proc.returncode,
                "stderr_tail": proc.stderr[-500:],
                "elapsed": round(elapsed, 1),
            }
        try:
            row = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return {
                "pid": pid,
                "status": "json_parse_error",
                "stdout_tail": proc.stdout[-500:],
                "elapsed": round(elapsed, 1),
            }
        row["_phase3a_filed_by"] = DOCTOR
        row["_phase3a_filed_at"] = datetime.now(timezone.utc).isoformat()
        row["_phase3a_elapsed_s"] = round(elapsed, 1)
        row["status"] = "complete"
        row["pid"] = pid
        return row
    except subprocess.TimeoutExpired:
        return {"pid": pid, "status": "timeout", "elapsed": PER_MODEL_TIMEOUT_S}
    except Exception as e:
        return {
            "pid": pid,
            "status": "driver_error",
            "error": f"{type(e).__name__}: {e}",
            "elapsed": round(time.time() - t0, 1),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="Run only first N targets")
    ap.add_argument("--fresh", action="store_true", help="Ignore checkpoint")
    args = ap.parse_args()

    targets = json.loads(TARGETS_JSON.read_text())
    if args.limit:
        targets = targets[: args.limit]

    checkpoint = {"done": [], "errors": []} if args.fresh else load_checkpoint()
    done = set(checkpoint["done"])

    remaining = [t for t in targets if t["pid"] not in done]
    log(f"Phase 3a retest: {len(remaining)}/{len(targets)} remaining (done={len(done)})")
    log(f"Doctor: {DOCTOR}")
    log(f"Harness: {HARNESS}")

    start = time.time()
    completed = 0

    for i, target in enumerate(remaining, 1):
        pid = target["pid"]
        orig_grade = target.get("original_grade")
        orig_score = target.get("original_score")

        log(f"[{i}/{len(remaining)}] {pid}  (original: {orig_grade}/{orig_score})")
        result = run_one(pid)
        result["original_grade"] = orig_grade
        result["original_score"] = orig_score

        # Compare
        if result.get("status") == "complete":
            new_grade = result.get("composite_grade")
            new_score = result.get("composite_score")
            agreement = "match" if new_grade == orig_grade else "mismatch"
            result["grade_agreement"] = agreement
            log(f"    -> {new_grade}/{new_score}  ({agreement})")
            checkpoint["done"].append(pid)
        else:
            log(f"    -> ERROR: {result.get('status')}: {result.get('error', result.get('stderr_tail', ''))[:200]}")
            checkpoint["errors"].append({"pid": pid, "status": result.get("status")})

        with open(RESULTS_JSONL, "a") as f:
            f.write(json.dumps(result) + "\n")
        save_checkpoint(checkpoint)
        completed += 1

        # Periodic progress
        if i % 10 == 0:
            elapsed = time.time() - start
            rate = completed / elapsed * 60  # per minute
            log(f"    progress: {completed}/{len(remaining)}  rate: {rate:.1f}/min")

    log(f"Phase 3a done: {completed} completed, {len(checkpoint['errors'])} errors")

    # Quick summary
    complete_rows = []
    with open(RESULTS_JSONL) as f:
        for line in f:
            r = json.loads(line)
            if r.get("status") == "complete":
                complete_rows.append(r)
    if complete_rows:
        matches = sum(1 for r in complete_rows if r.get("grade_agreement") == "match")
        log(f"Grade agreement: {matches}/{len(complete_rows)} "
            f"({matches/len(complete_rows)*100:.1f}%) match GR1")


if __name__ == "__main__":
    main()

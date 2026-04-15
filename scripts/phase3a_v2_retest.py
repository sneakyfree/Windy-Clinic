#!/usr/bin/env python3
"""Phase 3a-v2 — Retest the 71 ONNX-only failing base models (now restored).

Same harness as phase3a_retest.py but targets the 71 patients whose base
safetensors were deleted in the 2026-03-29 ONNX event and have now been
restored from Helsinki-NLP HuggingFace.

IMPORTANT: these are testing the RESTORED ORIGINAL Helsinki-NLP base weights,
which should reproduce GR1's base-row grades exactly (since GR1 also ran on
those same original weights before the deletion).

Doctor: Opus 4.6 Opus-Claw (Dr. C)
"""

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

HARNESS = "/home/user1-gpu/Desktop/grants_folder/windy-pro/grand_rounds_harness.py"
HARNESS_CWD = "/home/user1-gpu/Desktop/grants_folder/windy-pro"

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
TARGETS = CLINIC / "grand-rounds" / "phase3a_v2_targets.json"
OUT_DIR = CLINIC / "grand-rounds" / "phase3a_v2_retest"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_JSONL = OUT_DIR / "results.jsonl"
LOG_PATH = OUT_DIR / "run.log"

DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"
MACHINE = "Veron-1 (RTX 5090, Mt Pleasant SC)"


def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def run_one(pid):
    t0 = time.time()
    try:
        proc = subprocess.run(
            ["python3", HARNESS, "--eval-single", f"windy-pair-{pid}", "base"],
            cwd=HARNESS_CWD, capture_output=True, text=True, timeout=300,
        )
        if proc.returncode != 0:
            return {"pid": pid, "status": "harness_error", "stderr_tail": proc.stderr[-500:]}
        r = json.loads(proc.stdout)
        r["pid"] = pid
        r["status"] = "complete"
        r["_elapsed_s"] = round(time.time() - t0, 1)
        return r
    except Exception as e:
        return {"pid": pid, "status": "error", "error": str(e)}


def main():
    targets = json.loads(TARGETS.read_text())
    log(f"Phase 3a-v2 retest — {len(targets)} restored-base models (originally ONNX-only)")
    log(f"Doctor: {DOCTOR}")

    matches = 0
    mismatches = 0
    errors = 0

    for i, t in enumerate(targets, 1):
        pid = t["pid"]
        orig = t["original_grade"]
        orig_score = t.get("original_score")
        log(f"[{i}/{len(targets)}] {pid}  (GR1: {orig}/{orig_score})")
        r = run_one(pid)
        if r.get("status") == "complete":
            new_grade = r.get("composite_grade")
            new_score = r.get("composite_score")
            r["original_grade"] = orig
            r["original_score"] = orig_score
            r["grade_agreement"] = "match" if new_grade == orig else "mismatch"
            log(f"    -> {new_grade}/{new_score}  ({r['grade_agreement']})")
            if new_grade == orig:
                matches += 1
            else:
                mismatches += 1
        else:
            errors += 1
            log(f"    ERROR {r.get('status')}")
        with open(RESULTS_JSONL, "a") as f:
            f.write(json.dumps(r) + "\n")

    log(f"Done. match={matches} mismatch={mismatches} error={errors}")


if __name__ == "__main__":
    main()

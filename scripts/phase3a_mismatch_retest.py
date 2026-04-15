#!/usr/bin/env python3
"""Re-run the 57 phase3a mismatches, now that reverse partners are restored.

This is effectively phase3a_retest.py pointed at the mismatch list, writing
to a different output file so we can compare the three-way result:
  GR1 (Herm Zero) -> phase3a (Dr. C, missing partners) -> phase3a_v2 (Dr. C, partners restored)

If phase3a_v2 matches GR1 again, we confirm the mismatches were partner-artifacts.
If phase3a_v2 still doesn't match GR1, something else is going on.

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
TARGETS = CLINIC / "grand-rounds" / "phase3a_mismatches_retest.json"
OUT_DIR = CLINIC / "grand-rounds" / "phase3a_mismatch_retest"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_JSONL = OUT_DIR / "results.jsonl"
LOG_PATH = OUT_DIR / "run.log"

DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"


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
            return {"pid": pid, "status": "harness_error",
                    "stderr_tail": proc.stderr[-500:]}
        r = json.loads(proc.stdout)
        r["pid"] = pid
        r["status"] = "complete"
        r["_elapsed_s"] = round(time.time() - t0, 1)
        return r
    except Exception as e:
        return {"pid": pid, "status": "error", "error": str(e)}


def main():
    targets = json.loads(TARGETS.read_text())
    log(f"Mismatch re-test: {len(targets)} targets (partners now restored)")

    confirmed_gr1_match = 0
    still_mismatch = 0
    errors = 0

    for i, t in enumerate(targets, 1):
        pid = t["pid"]
        orig_gr1 = t["original_grade"]
        log(f"[{i}/{len(targets)}] {pid}  (GR1: {orig_gr1})")
        r = run_one(pid)
        if r.get("status") == "complete":
            new_grade = r.get("composite_grade")
            new_score = r.get("composite_score")
            r["gr1_grade"] = orig_gr1
            r["gr1_score"] = t["original_score"]
            match = new_grade == orig_gr1
            r["now_matches_gr1"] = match
            log(f"    -> {new_grade}/{new_score}  ({'MATCH GR1' if match else 'still differs'})")
            if match:
                confirmed_gr1_match += 1
            else:
                still_mismatch += 1
        else:
            errors += 1
        with open(RESULTS_JSONL, "a") as f:
            f.write(json.dumps(r) + "\n")

    log(f"Done. Confirmed GR1 match: {confirmed_gr1_match}, still differs: {still_mismatch}, errors: {errors}")


if __name__ == "__main__":
    main()

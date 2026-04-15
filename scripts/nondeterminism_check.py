#!/usr/bin/env python3
"""Run each "still differs" mismatch 3 times back-to-back.

If the 3 runs give identical grades to each other but different from GR1:
    -> stable nondeterminism / environmental difference (not a variance bug)
If the 3 runs give different grades from each other:
    -> true nondeterminism in the harness
If all 3 runs match GR1:
    -> the earlier mismatch was a transient artifact; model is actually consistent

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
OUT_DIR = CLINIC / "grand-rounds" / "nondeterminism_check"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS = OUT_DIR / "results.jsonl"
LOG_PATH = OUT_DIR / "run.log"

DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"


def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def run_one(pid):
    try:
        proc = subprocess.run(
            ["python3", HARNESS, "--eval-single", f"windy-pair-{pid}", "base"],
            cwd=HARNESS_CWD, capture_output=True, text=True, timeout=300,
        )
        if proc.returncode != 0:
            return None, None
        r = json.loads(proc.stdout)
        return r.get("composite_grade"), r.get("composite_score")
    except Exception:
        return None, None


def collect_mismatches():
    """Build the combined list of 'still differs' patients."""
    mismatches = {}

    # From phase3a_mismatch_retest — those that still didn't match GR1
    for line in open(CLINIC / "grand-rounds" / "phase3a_mismatch_retest" / "results.jsonl"):
        r = json.loads(line)
        if r.get("status") == "complete" and not r.get("now_matches_gr1"):
            pid = r["pid"]
            mismatches[pid] = {
                "pid": pid,
                "gr1_grade": r.get("gr1_grade"),
                "gr1_score": r.get("gr1_score"),
                "phase3a_grade": r.get("composite_grade"),
                "phase3a_score": r.get("composite_score"),
                "source": "phase3a_mismatch_retest",
            }

    # From phase3a_v2_retest — those with mismatch
    for line in open(CLINIC / "grand-rounds" / "phase3a_v2_retest" / "results.jsonl"):
        r = json.loads(line)
        if r.get("status") == "complete" and r.get("grade_agreement") == "mismatch":
            pid = r["pid"]
            if pid not in mismatches:
                mismatches[pid] = {
                    "pid": pid,
                    "gr1_grade": r.get("original_grade"),
                    "gr1_score": r.get("original_score"),
                    "phase3a_grade": r.get("composite_grade"),
                    "phase3a_score": r.get("composite_score"),
                    "source": "phase3a_v2_retest",
                }

    return list(mismatches.values())


def main():
    targets = collect_mismatches()
    log(f"Nondeterminism check — {len(targets)} mismatched patients, 3 runs each")

    rows = []
    for i, t in enumerate(targets, 1):
        pid = t["pid"]
        log(f"[{i}/{len(targets)}] {pid}  (GR1: {t['gr1_grade']}/{t['gr1_score']}, prior: {t['phase3a_grade']}/{t['phase3a_score']})")
        runs = []
        for run_idx in range(3):
            g, s = run_one(pid)
            runs.append({"grade": g, "score": s})
            log(f"    run {run_idx + 1}: {g}/{s}")
            time.sleep(0.2)
        classification = classify(t, runs)
        log(f"    => {classification}")
        row = {
            "pid": pid,
            "gr1": {"grade": t["gr1_grade"], "score": t["gr1_score"]},
            "prior_retest": {"grade": t["phase3a_grade"], "score": t["phase3a_score"]},
            "runs": runs,
            "classification": classification,
            "date": datetime.now(timezone.utc).isoformat(),
            "doctor": DOCTOR,
        }
        rows.append(row)
        with open(RESULTS, "a") as f:
            f.write(json.dumps(row) + "\n")

    # Summary
    counts = {}
    for r in rows:
        counts[r["classification"]] = counts.get(r["classification"], 0) + 1
    log(f"Summary: {counts}")


def classify(target, runs):
    """Classify the 3-run behaviour."""
    grades = [r["grade"] for r in runs]
    scores = [r["score"] for r in runs]
    gr1 = target["gr1_grade"]

    if all(g == grades[0] for g in grades):
        # all 3 runs identical
        if grades[0] == gr1:
            return "stable_matches_gr1_on_retry"
        else:
            return "stable_differs_from_gr1_environmental"
    else:
        # grades differ across runs
        if gr1 in grades:
            return "unstable_sometimes_matches_gr1"
        else:
            return "unstable_never_matches_gr1"


if __name__ == "__main__":
    main()

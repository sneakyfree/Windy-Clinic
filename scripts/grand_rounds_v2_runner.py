#!/usr/bin/env python3
"""
Grand Rounds v2 Runner — Subprocess-isolated execution.

Calls grand_rounds_v2.py --eval-single PID VARIANT for each model,
collecting results into a JSONL. Each model runs in its own subprocess
so a CUDA crash on one model doesn't kill the rest.

Doctor: Opus 4.6 Opus-Claw (Dr. C)
"""

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HARNESS = "/srv/repos/windy-pro/THE_CLINIC/scripts/grand_rounds_v2.py"
MODELS_DIR = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/models")
CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
OUT_DIR = CLINIC / "grand-rounds" / "grv2"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_JSONL = OUT_DIR / "results.jsonl"
CHECKPOINT = OUT_DIR / "checkpoint.json"
LOG_PATH = OUT_DIR / "run.log"

DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"
PER_MODEL_TIMEOUT = 180  # 3 min per model-variant


def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def get_targets():
    targets = []
    for pair_dir in sorted(MODELS_DIR.glob("windy-pair-*")):
        pid = pair_dir.name[len("windy-pair-"):]
        for vname in ["lora", "base", "herm0", "herm0-scripture"]:
            vdir = pair_dir / vname
            real = vdir.resolve() if vdir.is_symlink() else vdir
            if not real.exists():
                continue
            if not ((real / "model.safetensors").exists() or (real / "pytorch_model.bin").exists()):
                continue
            targets.append({"pid": pid, "variant": vname})
    return targets


def run_one(pid, variant):
    t0 = time.time()
    try:
        proc = subprocess.run(
            ["python3", HARNESS, "--eval-single", pid, variant],
            capture_output=True, text=True, timeout=PER_MODEL_TIMEOUT,
        )
        elapsed = time.time() - t0
        if proc.returncode != 0:
            return {"pid": pid, "variant": variant, "status": "error",
                    "error": proc.stderr[-300:], "elapsed": round(elapsed, 1)}
        row = json.loads(proc.stdout)
        row["elapsed"] = round(elapsed, 1)
        return row
    except subprocess.TimeoutExpired:
        return {"pid": pid, "variant": variant, "status": "timeout", "elapsed": PER_MODEL_TIMEOUT}
    except json.JSONDecodeError:
        return {"pid": pid, "variant": variant, "status": "json_error",
                "stdout_tail": proc.stdout[-300:] if 'proc' in dir() else ""}
    except Exception as e:
        return {"pid": pid, "variant": variant, "status": "error", "error": str(e)[:200]}


def main():
    targets = get_targets()

    state = {"done": [], "stars_dist": {}}
    if CHECKPOINT.exists():
        state = json.loads(CHECKPOINT.read_text())
    done = set(state["done"])

    remaining = [t for t in targets if f"{t['pid']}:{t['variant']}" not in done]

    log(f"Grand Rounds v2 Runner (subprocess-isolated)")
    log(f"Doctor: {DOCTOR}")
    log(f"Total: {len(targets)}, done: {len(done)}, remaining: {len(remaining)}")

    start = time.time()
    completed = 0

    for i, target in enumerate(remaining, 1):
        pid = target["pid"]
        variant = target["variant"]
        key = f"{pid}:{variant}"

        result = run_one(pid, variant)

        with open(RESULTS_JSONL, "a") as f:
            f.write(json.dumps(result) + "\n")

        if result.get("status") == "complete":
            stars = result.get("rating", {}).get("stars", "?")
            tier = result.get("rating", {}).get("tier", "?")
            state["stars_dist"][str(stars)] = state["stars_dist"].get(str(stars), 0) + 1
            if i % 10 == 0:
                log(f"[{i}/{len(remaining)}] {pid}:{variant} → {stars}★ ({tier}) {result.get('elapsed','')}s")
        else:
            if i % 50 == 0 or result.get("status") == "error":
                log(f"[{i}/{len(remaining)}] {pid}:{variant} → {result.get('status')}")

        state["done"].append(key)
        done.add(key)
        completed += 1
        CHECKPOINT.write_text(json.dumps(state, indent=2))

        if i % 100 == 0:
            elapsed = time.time() - start
            rate = completed / elapsed * 60
            log(f"  >> {completed}/{len(remaining)} ({rate:.1f}/min) Stars: {state['stars_dist']}")

    log(f"Grand Rounds v2 complete: {completed} tested")
    log(f"Star distribution: {state['stars_dist']}")


if __name__ == "__main__":
    main()

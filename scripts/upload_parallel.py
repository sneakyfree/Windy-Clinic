#!/usr/bin/env python3
"""
Parallel HuggingFace Upload — 8 workers, file-locked checkpoint.

Builds on upload_to_huggingface.py's logic, runs Phase 1+2+3 in parallel.
Phase 0 (clinic backup) must be done before running this.

Doctor: Opus 4.6 Opus-Claw (Dr. C)
"""

import argparse
import fcntl
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from multiprocessing import Process
from pathlib import Path

# Reuse everything from the main script
sys.path.insert(0, str(Path(__file__).parent))
from upload_to_huggingface import (
    ORG, MODELS, PATIENTS, STT_PATIENTS, DOCTOR, MACHINE,
    STT_REBUILT, STT_CT2, STT_ONNX, STT_ONNX_INT8, STT_LINGUA,
    VARIANT_UPLOAD_MAP, STT_VOICE_BASE_MAP, HERM0_SKIP_PIDS,
    build_translation_readme, build_stt_readme,
    create_repo_safe, upload_variant_folder, record_upload_in_patient,
)
from huggingface_hub import upload_folder, whoami

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
OUT_DIR = CLINIC / "huggingface-uploads"
OUT_DIR.mkdir(parents=True, exist_ok=True)
CHECKPOINT = OUT_DIR / "upload_checkpoint.json"
CHECKPOINT_LOCK = OUT_DIR / "upload_checkpoint.json.lock"
RESULTS_JSONL = OUT_DIR / "upload_results.jsonl"
LOG_PATH = OUT_DIR / "upload_parallel.log"


def log(msg, worker="main"):
    line = f"[{datetime.now(timezone.utc).isoformat()}] [{worker}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def claim_next_pid():
    """Atomically claim next pid from targets, mark as in_progress.
    Skips pids that are done, in-progress, OR already errored (prevents infinite retry loops)."""
    with open(CHECKPOINT_LOCK, "w") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        try:
            state = json.loads(CHECKPOINT.read_text())
            done = set(state.get("phase1_done", []))
            in_progress = set(state.get("phase1_in_progress", []))
            errors = set(state.get("phase1_errors", []))
            for pid in state.get("phase1_targets", []):
                if pid not in done and pid not in in_progress and pid not in errors:
                    state.setdefault("phase1_in_progress", []).append(pid)
                    CHECKPOINT.write_text(json.dumps(state, indent=2))
                    return pid
            return None
        finally:
            fcntl.flock(lockf, fcntl.LOCK_UN)


def mark_done(pid, success=True):
    """Move pid from in_progress to done."""
    with open(CHECKPOINT_LOCK, "w") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        try:
            state = json.loads(CHECKPOINT.read_text())
            ip = state.setdefault("phase1_in_progress", [])
            if pid in ip:
                ip.remove(pid)
            if success:
                state.setdefault("phase1_done", []).append(pid)
            else:
                state.setdefault("phase1_errors", []).append(pid)
            CHECKPOINT.write_text(json.dumps(state, indent=2))
        finally:
            fcntl.flock(lockf, fcntl.LOCK_UN)


def upload_one_translation(pid, worker_id):
    """Upload a single translation patient's variants."""
    pf = PATIENTS / f"{pid}.json"
    if not pf.exists():
        return {"pid": pid, "status": "no_patient_file"}
    chart = json.loads(pf.read_text())
    repo_id = f"{ORG}/translate-{pid}"

    if not create_repo_safe(repo_id, repo_type="model", private=False):
        return {"pid": pid, "status": "create_repo_error"}

    uploaded = []
    for disk_name, subfolder in VARIANT_UPLOAD_MAP:
        if disk_name in ("herm0", "herm0-ct2-int8") and pid in HERM0_SKIP_PIDS:
            log(f"SKIP {disk_name} for {pid}: GR v2 regression (herm0_skiplist.json)", f"w{worker_id}")
            continue
        vdir = MODELS / f"windy-pair-{pid}" / disk_name
        real = vdir.resolve() if vdir.is_symlink() else vdir
        if not real.exists():
            continue
        if not (
            (real / "model.safetensors").exists()
            or (real / "pytorch_model.bin").exists()
            or (real / "model.bin").exists()
        ):
            continue
        if upload_variant_folder(repo_id, real, subfolder):
            uploaded.append(disk_name)

    # README
    readme = build_translation_readme(chart)
    tmp = Path(f"/tmp/_readme_w{worker_id}_{pid}")
    tmp.mkdir(exist_ok=True)
    (tmp / "README.md").write_text(readme)
    try:
        upload_folder(repo_id=repo_id, folder_path=str(tmp), repo_type="model",
                     commit_message="Add model card")
    except Exception as e:
        log(f"  README upload error {pid}: {e}", f"w{worker_id}")
    shutil.rmtree(tmp, ignore_errors=True)

    record_upload_in_patient(pid, repo_id, uploaded, subtype="translation")

    return {"pid": pid, "status": "complete", "repo_id": repo_id,
            "variants": uploaded, "worker": worker_id}


def worker_loop(worker_id):
    log(f"Worker {worker_id} started", f"w{worker_id}")
    processed = 0
    errors = 0
    consecutive_errors = 0
    while True:
        pid = claim_next_pid()
        if pid is None:
            log(f"No more targets. Exiting. Processed {processed}, errors {errors}.", f"w{worker_id}")
            return
        try:
            t0 = time.time()
            result = upload_one_translation(pid, worker_id)
            elapsed = time.time() - t0
            result["elapsed"] = round(elapsed, 1)
            with open(RESULTS_JSONL, "a") as f:
                f.write(json.dumps(result) + "\n")

            if result.get("status") == "complete":
                mark_done(pid, success=True)
                processed += 1
                consecutive_errors = 0
                if processed % 10 == 0:
                    log(f"processed={processed} latest={pid} ({elapsed:.1f}s)", f"w{worker_id}")
            else:
                mark_done(pid, success=False)
                errors += 1
                consecutive_errors += 1
                log(f"ERROR {pid}: {result.get('status')}", f"w{worker_id}")
                # Exponential backoff on consecutive errors — prevents retry storms
                if consecutive_errors >= 3:
                    wait = min(60 * (2 ** (consecutive_errors - 3)), 600)
                    log(f"  {consecutive_errors} consecutive errors, backing off {wait}s", f"w{worker_id}")
                    time.sleep(wait)
        except Exception as e:
            log(f"ERROR {pid}: {type(e).__name__}: {str(e)[:200]}", f"w{worker_id}")
            mark_done(pid, success=False)
            errors += 1
            consecutive_errors += 1
            if consecutive_errors >= 3:
                wait = min(60 * (2 ** (consecutive_errors - 3)), 600)
                log(f"  {consecutive_errors} consecutive errors, backing off {wait}s", f"w{worker_id}")
                time.sleep(wait)


def build_target_list():
    """Build the list of patients with uploadable variants."""
    with open(CHECKPOINT_LOCK, "w") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        try:
            state = json.loads(CHECKPOINT.read_text())
            if "phase1_targets" in state and state["phase1_targets"]:
                log(f"Targets already built: {len(state['phase1_targets'])}")
                return state["phase1_targets"]
            # Build
            targets = []
            for pf in sorted(PATIENTS.glob("*.json")):
                pid = pf.stem
                has_uploadable = False
                for disk_name, _ in VARIANT_UPLOAD_MAP:
                    vdir = MODELS / f"windy-pair-{pid}" / disk_name
                    if vdir.exists() and (
                        (vdir / "model.safetensors").exists()
                        or (vdir / "pytorch_model.bin").exists()
                        or (vdir / "model.bin").exists()
                    ):
                        has_uploadable = True
                        break
                if has_uploadable:
                    targets.append(pid)
            state["phase1_targets"] = targets
            state.setdefault("phase1_in_progress", [])
            CHECKPOINT.write_text(json.dumps(state, indent=2))
            log(f"Built {len(targets)} targets")
            return targets
        finally:
            fcntl.flock(lockf, fcntl.LOCK_UN)


def phase2_stt_voice():
    """Upload STT voice models (sequential — only 10 models)."""
    log("\n=== Phase 2: STT voice ===")
    state = json.loads(CHECKPOINT.read_text())
    done = set(state.get("phase2_done", []))
    for name, base_model in STT_VOICE_BASE_MAP.items():
        if name in done: continue
        src_dir = STT_REBUILT / name
        if not src_dir.exists():
            log(f"  SKIP {name}"); continue
        repo_id = f"{ORG}/listen-{name}"
        log(f"{name} → {repo_id}")
        if not create_repo_safe(repo_id, repo_type="model", private=False):
            continue
        variants = []
        if upload_variant_folder(repo_id, src_dir, "safetensors"):
            variants.append("safetensors")
        ct2 = STT_CT2 / f"{name}-ct2"
        if ct2.exists() and upload_variant_folder(repo_id, ct2, "ct2-int8"):
            variants.append("ct2-int8")
        onnx = STT_ONNX / f"{name}-onnx"
        if onnx.exists() and upload_variant_folder(repo_id, onnx, "onnx"):
            variants.append("onnx")
        onnx_int8 = STT_ONNX_INT8 / f"{name}-onnx-int8"
        if onnx_int8.exists() and upload_variant_folder(repo_id, onnx_int8, "onnx-int8"):
            variants.append("onnx-int8")
        readme = build_stt_readme(name, base_model, variants)
        tmp = Path(f"/tmp/_readme_{name}")
        tmp.mkdir(exist_ok=True)
        (tmp / "README.md").write_text(readme)
        try:
            upload_folder(repo_id=repo_id, folder_path=str(tmp), repo_type="model",
                         commit_message="Add model card")
        except Exception: pass
        shutil.rmtree(tmp, ignore_errors=True)
        record_upload_in_patient(name, repo_id, variants, subtype="stt")
        with open(CHECKPOINT_LOCK, "w") as lockf:
            fcntl.flock(lockf, fcntl.LOCK_EX)
            try:
                state = json.loads(CHECKPOINT.read_text())
                state.setdefault("phase2_done", []).append(name)
                CHECKPOINT.write_text(json.dumps(state, indent=2))
            finally:
                fcntl.flock(lockf, fcntl.LOCK_UN)
        log(f"  ✓ {len(variants)} variants")


def phase3_stt_lingua():
    log("\n=== Phase 3: STT lingua ===")
    state = json.loads(CHECKPOINT.read_text())
    done = set(state.get("phase3_done", []))
    for src_dir in sorted(STT_LINGUA.iterdir()):
        if not src_dir.is_dir(): continue
        name = src_dir.name
        if name in done: continue
        repo_id = f"{ORG}/listen-{name}"
        log(f"{name} → {repo_id}")
        if not create_repo_safe(repo_id, repo_type="model", private=False):
            continue
        variant_name = "ct2-int8" if name.endswith("-ct2") else "safetensors"
        if upload_variant_folder(repo_id, src_dir, variant_name):
            with open(CHECKPOINT_LOCK, "w") as lockf:
                fcntl.flock(lockf, fcntl.LOCK_EX)
                try:
                    state = json.loads(CHECKPOINT.read_text())
                    state.setdefault("phase3_done", []).append(name)
                    CHECKPOINT.write_text(json.dumps(state, indent=2))
                finally:
                    fcntl.flock(lockf, fcntl.LOCK_UN)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--skip-phase1", action="store_true")
    ap.add_argument("--skip-stt", action="store_true")
    args = ap.parse_args()

    log("=" * 60)
    log(f"PARALLEL UPLOAD — {args.workers} workers")
    log(f"Doctor: {DOCTOR}")
    log("=" * 60)

    try:
        info = whoami()
        log(f"Auth: {info.get('name')}")
    except Exception as e:
        log(f"Auth FAILED: {e}")
        sys.exit(1)

    if not args.skip_phase1:
        targets = build_target_list()
        state = json.loads(CHECKPOINT.read_text())
        done = set(state.get("phase1_done", []))
        # Reset in_progress from previous aborted run
        state["phase1_in_progress"] = []
        CHECKPOINT.write_text(json.dumps(state, indent=2))
        log(f"Phase 1: {len(targets)} targets, {len(done)} done, {len(targets) - len(done)} remaining")

        workers = []
        for i in range(args.workers):
            p = Process(target=worker_loop, args=(i,))
            p.start()
            workers.append(p)
            time.sleep(1)  # stagger startup

        for p in workers:
            p.join()

        log("Phase 1 parallel complete")

    if not args.skip_stt:
        phase2_stt_voice()
        phase3_stt_lingua()

    log("=" * 60)
    log("UPLOAD PIPELINE COMPLETE")
    log("=" * 60)


if __name__ == "__main__":
    main()

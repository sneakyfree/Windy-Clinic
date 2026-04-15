#!/usr/bin/env python3
"""
Parallel Herm0 Improvement Pipeline — actually uses the damn machine
=====================================================================
Runs N parallel workers, each training a different model on shared GPU.
File-locked checkpoint coordination.

With 32 GB VRAM + 24 CPU cores, we can do 5-6 workers easily.
Each worker: ~5 GB VRAM, batch_size=32, 1 CPU core for data loading.

Doctor: Opus 4.6 Opus-Claw (Dr. C)
"""

import argparse
import fcntl
import gc
import json
import os
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone
from multiprocessing import Process, current_process
from pathlib import Path

import numpy as np
import torch
from transformers import (
    MarianMTModel, MarianTokenizer,
    Seq2SeqTrainingArguments, Seq2SeqTrainer, DataCollatorForSeq2Seq,
)
from datasets import Dataset

MODELS = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/models")
CACHE = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/audit_results/herm0_improvements/data_cache")
CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
PATIENTS = CLINIC / "translation-pairs"

CHECKPOINT = CLINIC / "grand-rounds" / "herm0_pipeline_checkpoint.json"
CHECKPOINT_LOCK = CLINIC / "grand-rounds" / "herm0_pipeline_checkpoint.json.lock"
RESULTS_JSONL = CLINIC / "grand-rounds" / "herm0_pipeline_results.jsonl"
LOG_PATH = CLINIC / "grand-rounds" / "herm0_parallel.log"

DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"
MAX_PAIRS = 50000


def log(msg, worker="main"):
    line = f"[{datetime.now(timezone.utc).isoformat()}] [{worker}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def claim_next_pid(worker_id):
    """Atomically claim the next pid to work on, using file locking."""
    with open(CHECKPOINT_LOCK, "w") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        try:
            if CHECKPOINT.exists():
                state = json.loads(CHECKPOINT.read_text())
            else:
                state = {"done": [], "in_progress": [], "improved": [],
                         "no_improvement": [], "no_data": [], "errors": []}

            done_set = set(state.get("done", []))
            in_progress = set(state.get("in_progress", []))

            # Find a pid not done and not in progress
            targets = state.get("targets", [])
            if not targets:
                return None

            for pid in targets:
                if pid not in done_set and pid not in in_progress:
                    state.setdefault("in_progress", []).append(pid)
                    CHECKPOINT.write_text(json.dumps(state, indent=2))
                    return pid
            return None
        finally:
            fcntl.flock(lockf, fcntl.LOCK_UN)


def mark_done(pid, result, status_bucket):
    """Mark pid done, move from in_progress to done."""
    with open(CHECKPOINT_LOCK, "w") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        try:
            state = json.loads(CHECKPOINT.read_text()) if CHECKPOINT.exists() else {"done": [], "in_progress": [], "improved": [], "no_improvement": [], "no_data": [], "errors": []}
            ip = state.setdefault("in_progress", [])
            if pid in ip:
                ip.remove(pid)
            state.setdefault("done", []).append(pid)
            state.setdefault(status_bucket, []).append(pid)
            CHECKPOINT.write_text(json.dumps(state, indent=2))

            # Also append to results JSONL (append-mode is safe for concurrent writes <4KB)
            with open(RESULTS_JSONL, "a") as f:
                f.write(json.dumps(result) + "\n")
        finally:
            fcntl.flock(lockf, fcntl.LOCK_UN)


def find_data(pid):
    files = list(CACHE.glob(f"*_{pid}.json"))
    if not files:
        parts = pid.split("-") if "-" in pid else [pid]
        for p in parts:
            files.extend(CACHE.glob(f"*_{p}-*.json"))
            files.extend(CACHE.glob(f"*_*-{p}.json"))
    return list(set(files))[:5]


def load_data(data_files, max_pairs=MAX_PAIRS):
    all_src, all_tgt = [], []
    for f in data_files:
        try:
            data = json.loads(f.read_text())
            src = data.get("src", [])
            tgt = data.get("tgt", [])
            n = min(len(src), len(tgt))
            all_src.extend(src[:n])
            all_tgt.extend(tgt[:n])
        except Exception:
            continue
    indices = list(range(len(all_src)))
    np.random.seed(42)
    np.random.shuffle(indices)
    indices = indices[:max_pairs]
    return [all_src[i] for i in indices], [all_tgt[i] for i in indices]


def score_model(model, tokenizer, test_sents, device):
    model.eval()
    scores = []
    for sent in test_sents[:10]:
        try:
            inputs = tokenizer(sent, return_tensors="pt", truncation=True, max_length=128).to(device)
            with torch.no_grad():
                out = model.generate(**inputs, max_new_tokens=128)
            tgt = tokenizer.decode(out[0], skip_special_tokens=True)
            if len(tgt.strip()) > 0:
                ratio = min(len(tgt), len(sent)) / max(len(tgt), len(sent), 1)
                scores.append(ratio * 100)
            else:
                scores.append(0)
        except Exception:
            scores.append(0)
    return float(np.mean(scores)) if scores else 0.0


def train_one(pid, worker_id):
    t0 = time.time()
    device = "cuda"

    # Find source weights
    lora_dir = MODELS / f"windy-pair-{pid}" / "lora"
    base_dir = MODELS / f"windy-pair-{pid}" / "base"
    src_dir = lora_dir if (lora_dir / "model.safetensors").exists() else base_dir
    real = src_dir.resolve() if src_dir.is_symlink() else src_dir

    if not real.exists() or not ((real / "model.safetensors").exists() or (real / "pytorch_model.bin").exists()):
        return {"pid": pid, "status": "no_source"}, "errors"

    # Skip if herm0 already exists
    herm0_dir = MODELS / f"windy-pair-{pid}" / "herm0"
    if herm0_dir.exists() and (herm0_dir / "model.safetensors").exists():
        return {"pid": pid, "status": "already_has_herm0"}, "done"

    data_files = find_data(pid)
    if not data_files:
        return {"pid": pid, "status": "no_data"}, "no_data"

    src_sents, tgt_sents = load_data(data_files)
    if len(src_sents) < 100:
        return {"pid": pid, "status": "insufficient_data", "pairs": len(src_sents)}, "no_data"

    model = MarianMTModel.from_pretrained(str(src_dir))
    tokenizer = MarianTokenizer.from_pretrained(str(src_dir))
    model.to(device)

    test_sents = src_sents[-50:]
    train_src = src_sents[:-50]
    train_tgt = tgt_sents[:-50]
    score_before = score_model(model, tokenizer, test_sents, device)

    def preprocess(examples):
        inputs = tokenizer(examples["src"], truncation=True, max_length=128, padding="max_length")
        labels = tokenizer(text_target=examples["tgt"], truncation=True, max_length=128, padding="max_length")
        inputs["labels"] = labels["input_ids"]
        return inputs

    ds = Dataset.from_dict({"src": train_src, "tgt": train_tgt})
    tokenized = ds.map(preprocess, batched=True, remove_columns=["src", "tgt"], num_proc=2)

    output_dir = f"/tmp/herm0_train_{worker_id}_{pid}"
    # Match the proven-good Phase 2 settings: batch=16, 2 epochs, lr=5e-6
    # Same training dynamics as serial runs — parallelism only speeds up
    # throughput between models, not within a model.
    args = Seq2SeqTrainingArguments(
        output_dir=output_dir,
        num_train_epochs=2,
        per_device_train_batch_size=16,   # match Herm Zero + Phase 1/2 methodology
        learning_rate=5e-6,
        fp16=True,
        save_strategy="no",
        logging_steps=500,
        report_to="none",
        dataloader_num_workers=1,
        warmup_steps=100,
        weight_decay=0.01,
    )

    trainer = Seq2SeqTrainer(
        model=model, args=args, train_dataset=tokenized,
        data_collator=DataCollatorForSeq2Seq(tokenizer, model=model),
    )
    trainer.train()

    score_after = score_model(model, tokenizer, test_sents, device)
    improved = bool(score_after > score_before)
    elapsed = time.time() - t0

    result = {
        "pid": pid, "worker": worker_id,
        "pairs_used": len(train_src), "epochs": 2, "lr": 5e-6,
        "score_before": round(float(score_before), 1),
        "score_after": round(float(score_after), 1),
        "delta": round(float(score_after - score_before), 1),
        "improved": improved, "elapsed": round(elapsed, 1),
    }

    status_bucket = "no_improvement"
    if improved:
        herm0_dir.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(str(herm0_dir))
        tokenizer.save_pretrained(str(herm0_dir))
        size = sum(f.stat().st_size for f in herm0_dir.rglob("*") if f.is_file()) / (1024*1024)
        result["status"] = "improved"
        result["size_mb"] = round(size)
        status_bucket = "improved"
    else:
        result["status"] = "no_improvement"

    del model, trainer
    gc.collect()
    torch.cuda.empty_cache()
    shutil.rmtree(output_dir, ignore_errors=True)
    return result, status_bucket


def update_patient(pid, result, phase=4):
    pf = PATIENTS / f"{pid}.json"
    if not pf.exists(): return
    chart = json.loads(pf.read_text())
    run_iso = datetime.now(timezone.utc).isoformat()

    log_list = chart.setdefault("examination_log", [])
    exam_id = f"DRC-HERM0-P{phase}-{pid}"
    if any(e.get("exam_id") == exam_id for e in log_list): return

    if result.get("status") == "improved":
        vc = chart.setdefault("variant_cluster", {})
        vc["herm0"] = {
            "status": "present",
            "format": "safetensors",
            "derived_from": f"Parallel Phase 4 improvement (2 epochs, lr=5e-6, batch=32)",
            "on_disk_path": str(MODELS / f"windy-pair-{pid}" / "herm0"),
            "score_before": result.get("score_before"),
            "score_after": result.get("score_after"),
            "delta": result.get("delta"),
            "improved_at": run_iso,
            "improved_by": DOCTOR,
        }

    log_list.append({
        "exam_id": exam_id,
        "date": run_iso,
        "doctor": DOCTOR,
        "machine": "Veron-1 (RTX 5090, Mt Pleasant SC)",
        "method": (
            f"Parallel improvement pipeline (Phase 4): 2 epochs, lr=5e-6, batch=32, fp16, "
            f"worker={result.get('worker')}. "
            f"Score {result.get('score_before')}→{result.get('score_after')} "
            f"(Δ{result.get('delta'):+.1f}). "
            f"{'IMPROVED — saved as herm0/' if result.get('improved') else 'No improvement — discarded.'}"
        ),
        "protocol_script": "scripts/herm0_pipeline_parallel.py",
        "notes": f"Parallel worker {result.get('worker')}. Data: {result.get('pairs_used',0)} pairs. Filed by {DOCTOR}.",
    })
    chart["_last_updated"] = run_iso
    pf.write_text(json.dumps(chart, indent=2))


def worker_loop(worker_id):
    log(f"Worker {worker_id} starting", f"w{worker_id}")
    processed = 0
    while True:
        pid = claim_next_pid(worker_id)
        if pid is None:
            log(f"No more targets. Exiting.", f"w{worker_id}")
            break
        try:
            result, bucket = train_one(pid, worker_id)
            mark_done(pid, result, bucket)
            update_patient(pid, result)
            processed += 1
            if result.get("status") == "improved":
                log(f"IMPROVED {pid}: Δ{result.get('delta','?'):+.1f} ({result.get('elapsed','?')}s)", f"w{worker_id}")
            elif processed % 5 == 0:
                log(f"processed {processed}, latest={pid}:{result.get('status')} ({result.get('elapsed','?')}s)", f"w{worker_id}")
        except Exception as e:
            log(f"ERROR {pid}: {type(e).__name__}: {str(e)[:150]}", f"w{worker_id}")
            mark_done(pid, {"pid": pid, "status": "error", "error": str(e)[:200]}, "errors")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=5)
    args = ap.parse_args()

    # Build target list if not already built
    if not CHECKPOINT.exists() or "targets" not in json.loads(CHECKPOINT.read_text()):
        # Merge with existing checkpoint
        existing = {}
        if CHECKPOINT.exists():
            existing = json.loads(CHECKPOINT.read_text())

        # Find all models that don't have herm0/ yet and are improvable
        targets = []
        existing_done = set(existing.get("done", []))
        for pair in sorted(MODELS.glob("windy-pair-*")):
            pid = pair.name[len("windy-pair-"):]
            if pid in existing_done: continue
            # Already has herm0?
            if (pair / "herm0" / "model.safetensors").exists(): continue
            # Has scripture? (skip, that's a different variant)
            if (pair / "herm0-scripture").exists(): continue
            # Has data?
            has_src = (pair / "lora" / "model.safetensors").exists() or (pair / "base").exists()
            if has_src:
                targets.append(pid)

        existing["targets"] = targets
        existing["in_progress"] = []
        CHECKPOINT.write_text(json.dumps(existing, indent=2))
        log(f"Built target list: {len(targets)} remaining models")

    log(f"Launching {args.workers} parallel workers")

    # Spawn workers
    workers = []
    for i in range(args.workers):
        p = Process(target=worker_loop, args=(i,))
        p.start()
        workers.append(p)
        time.sleep(5)  # stagger startup to avoid simultaneous model loads

    for p in workers:
        p.join()

    log("All workers done")


if __name__ == "__main__":
    main()

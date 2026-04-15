#!/usr/bin/env python3
"""ONNX export the full MarianMT translation fleet.

Exports base variants of all 1,607+ Helsinki-NLP models + 292 herm0_scripture
variants to ONNX format via optimum. Each model produces encoder + decoder +
decoder_with_past ONNX graphs.

Parallelized with ProcessPoolExecutor. CPU-bound (torch.onnx.export trace).
Checkpoint/resume at model boundary.

Doctor: Opus 4.6 Opus-Claw (Dr. C)
"""

import gc
import json
import os
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

MODELS_DIR = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/models")
ONNX_DIR = Path("/mnt/data2/windy-onnx-fleet")
ONNX_DIR.mkdir(parents=True, exist_ok=True)
CHECKPOINT = ONNX_DIR / "checkpoint.json"
LOG_PATH = ONNX_DIR / "export.log"
RESULTS_JSONL = ONNX_DIR / "results.jsonl"


def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def export_one(args):
    """Export a single model to ONNX. Run in subprocess."""
    pid, src, dst = args
    if Path(dst).exists() and (Path(dst) / "encoder_model.onnx").exists():
        return {"pid": pid, "status": "already_done"}
    try:
        from optimum.onnxruntime import ORTModelForSeq2SeqLM
        from transformers import MarianTokenizer
        import warnings
        warnings.filterwarnings("ignore")

        t0 = time.time()
        model = ORTModelForSeq2SeqLM.from_pretrained(src, export=True)
        Path(dst).mkdir(parents=True, exist_ok=True)
        model.save_pretrained(dst)
        tok = MarianTokenizer.from_pretrained(src)
        tok.save_pretrained(dst)
        size = sum(f.stat().st_size for f in Path(dst).rglob("*") if f.is_file()) / (1024 * 1024)
        return {"pid": pid, "status": "success", "size_mb": round(size), "elapsed": round(time.time() - t0, 1)}
    except Exception as e:
        if Path(dst).exists():
            shutil.rmtree(dst, ignore_errors=True)
        return {"pid": pid, "status": "error", "error": f"{type(e).__name__}: {str(e)[:200]}"}


def enumerate_targets():
    targets = []
    for pair_dir in sorted(MODELS_DIR.glob("windy-pair-*")):
        pid = pair_dir.name[len("windy-pair-"):]
        base = pair_dir / "base"
        if not base.exists():
            continue
        real = base.resolve() if base.is_symlink() else base
        if not (real / "config.json").exists():
            continue
        if not any((real / n).exists() for n in ("model.safetensors", "pytorch_model.bin")):
            continue
        dst = str(ONNX_DIR / f"windy-pair-{pid}-onnx")
        targets.append((pid, str(base), dst))

    # Also herm0_scripture variants
    for pair_dir in sorted(MODELS_DIR.glob("windy-pair-*")):
        pid = pair_dir.name[len("windy-pair-"):]
        scr = pair_dir / "herm0-scripture"
        if not scr.exists():
            continue
        if not (scr / "config.json").exists():
            continue
        dst = str(ONNX_DIR / f"windy-pair-{pid}-herm0scripture-onnx")
        targets.append((pid + "-herm0scripture", str(scr), dst))

    return targets


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    targets = enumerate_targets()

    # Load checkpoint
    done = set()
    if CHECKPOINT.exists():
        done = set(json.loads(CHECKPOINT.read_text()).get("done", []))

    remaining = [t for t in targets if t[0] not in done]
    log(f"ONNX fleet export — {len(targets)} total, {len(done)} done, {len(remaining)} remaining, {workers} workers")

    completed = 0
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(export_one, t): t for t in remaining}
        for future in as_completed(futures):
            result = future.result()
            pid = result["pid"]
            done.add(pid)
            completed += 1

            with open(RESULTS_JSONL, "a") as f:
                f.write(json.dumps(result) + "\n")

            CHECKPOINT.write_text(json.dumps({"done": sorted(done)}))

            if result["status"] == "success":
                log(f"  [{completed}/{len(remaining)}] {pid}: {result['size_mb']} MB, {result['elapsed']}s")
            elif result["status"] != "already_done":
                log(f"  [{completed}/{len(remaining)}] {pid}: {result['status']}")

            if completed % 50 == 0:
                log(f"  >> {completed}/{len(remaining)} done")

    log(f"Export complete: {completed} models")


if __name__ == "__main__":
    main()

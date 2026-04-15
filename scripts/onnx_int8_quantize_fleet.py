#!/usr/bin/env python3
"""ONNX INT8 dynamic quantization of the MarianMT ONNX fleet.

Takes the FP32 ONNX models from /mnt/data2/windy-onnx-fleet/ and quantizes
encoder + decoder + decoder_with_past to INT8 using onnxruntime.quantization.

Produces ~200 MB models from ~800 MB originals (75% compression).
CPU-bound operation. Parallelizable.

Doctor: Opus 4.6 Opus-Claw (Dr. C)
"""

import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ONNX_DIR = Path("/mnt/data2/windy-onnx-fleet")
INT8_DIR = Path("/mnt/data2/windy-onnx-fleet-int8")
INT8_DIR.mkdir(parents=True, exist_ok=True)
CHECKPOINT = INT8_DIR / "checkpoint.json"
LOG_PATH = INT8_DIR / "quantize.log"


def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def quantize_one(args):
    pid, src_dir, dst_dir = args
    try:
        from onnxruntime.quantization import quantize_dynamic, QuantType
        import shutil

        src_path = Path(src_dir)
        dst_path = Path(dst_dir)
        if dst_path.exists() and (dst_path / "encoder_model.onnx").exists():
            return {"pid": pid, "status": "already_done"}

        dst_path.mkdir(parents=True, exist_ok=True)
        t0 = time.time()

        # Quantize each ONNX graph
        for graph in ["encoder_model.onnx", "decoder_model.onnx", "decoder_with_past_model.onnx"]:
            src_file = src_path / graph
            dst_file = dst_path / graph
            if not src_file.exists():
                continue
            quantize_dynamic(
                model_input=str(src_file),
                model_output=str(dst_file),
                weight_type=QuantType.QInt8,
            )

        # Copy non-ONNX files (config, tokenizer, etc.)
        for f in src_path.iterdir():
            if f.is_file() and not f.name.endswith(".onnx"):
                shutil.copy2(str(f), str(dst_path / f.name))

        size = sum(f.stat().st_size for f in dst_path.rglob("*") if f.is_file()) / (1024 * 1024)
        return {"pid": pid, "status": "success", "size_mb": round(size), "elapsed": round(time.time() - t0, 1)}
    except Exception as e:
        return {"pid": pid, "status": "error", "error": f"{type(e).__name__}: {str(e)[:200]}"}


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 4

    targets = []
    for d in sorted(ONNX_DIR.iterdir()):
        if not d.is_dir():
            continue
        if not (d / "encoder_model.onnx").exists():
            continue
        pid = d.name.replace("-onnx", "")
        dst = str(INT8_DIR / d.name.replace("-onnx", "-onnx-int8"))
        targets.append((pid, str(d), dst))

    done = set()
    if CHECKPOINT.exists():
        done = set(json.loads(CHECKPOINT.read_text()).get("done", []))

    remaining = [t for t in targets if t[0] not in done]
    log(f"ONNX INT8 quantization — {len(targets)} total, {len(done)} done, {len(remaining)} remaining, {workers} workers")

    completed = 0
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(quantize_one, t): t for t in remaining}
        for future in as_completed(futures):
            result = future.result()
            done.add(result["pid"])
            completed += 1
            CHECKPOINT.write_text(json.dumps({"done": sorted(done)}))

            if result["status"] == "success":
                log(f"  [{completed}/{len(remaining)}] {result['pid']}: {result['size_mb']} MB, {result['elapsed']}s")
            elif result["status"] != "already_done":
                log(f"  [{completed}/{len(remaining)}] {result['pid']}: {result['status']}")

            if completed % 50 == 0:
                log(f"  >> {completed}/{len(remaining)} done")

    log(f"Quantization complete: {completed} models")


if __name__ == "__main__":
    main()

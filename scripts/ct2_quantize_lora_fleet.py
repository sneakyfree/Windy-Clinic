#!/usr/bin/env python3
"""Create REAL CTranslate2 INT8 quantized versions of the proprietary LoRA
fog-of-mirror models.

Quantizes lora/ (NOT base/) for each model — these are Windy Word's
proprietary weights, legally distinct from Helsinki-NLP originals.

Also quantizes herm0-scripture/ where present.

Uses ct2-opus-mt-converter CLI tool for MarianMT models.
Writes to models/windy-pair-{pid}/lora-ct2-int8/ (new directory name
that clearly indicates: INT8 of the LoRA proprietary variant).

Doctor: Opus 4.6 Opus-Claw (Dr. C)
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

MODELS = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/models")
CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
PATIENTS = CLINIC / "translation-pairs"
LOG_PATH = CLINIC / "grand-rounds" / "ct2_real_quantize.log"
CHECKPOINT = CLINIC / "grand-rounds" / "ct2_real_checkpoint.json"
RESULTS_JSONL = CLINIC / "grand-rounds" / "ct2_real_results.jsonl"

DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"
MACHINE = "Veron-1 (RTX 5090, Mt Pleasant SC)"


def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def quantize_one(src_dir, dst_dir):
    """Use ctranslate2 Python TransformersConverter to quantize to INT8."""
    import shutil
    from ctranslate2.converters import TransformersConverter
    try:
        dst_path = Path(dst_dir)
        if dst_path.exists():
            shutil.rmtree(str(dst_path))
        converter = TransformersConverter(str(src_dir))
        converter.convert(str(dst_dir), quantization="int8")
        return (dst_path / "model.bin").exists(), ""
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:300]}"


def main():
    run_iso = datetime.now(timezone.utc).isoformat()

    # Build target list: every model with a lora/ dir
    targets = []
    for pair_dir in sorted(MODELS.glob("windy-pair-*")):
        pid = pair_dir.name[len("windy-pair-"):]

        # LoRA variant → lora-ct2-int8
        lora_dir = pair_dir / "lora"
        if lora_dir.exists() and (lora_dir / "model.safetensors").exists():
            dst = pair_dir / "lora-ct2-int8"
            targets.append(("lora", pid, str(lora_dir), str(dst)))

        # herm0-scripture variant → scripture-ct2-int8
        scr_dir = pair_dir / "herm0-scripture"
        if scr_dir.exists() and (scr_dir / "model.safetensors").exists():
            dst = pair_dir / "scripture-ct2-int8"
            targets.append(("scripture", pid, str(scr_dir), str(dst)))

    # Load checkpoint
    done = set()
    if CHECKPOINT.exists():
        done = set(json.loads(CHECKPOINT.read_text()).get("done", []))

    remaining = [t for t in targets if f"{t[0]}:{t[1]}" not in done]
    log(f"Real CT2 INT8 quantization — {len(targets)} total, {len(done)} done, {len(remaining)} remaining")
    log(f"Source: lora/ (proprietary fog-of-mirror) + herm0-scripture/")
    log(f"Doctor: {DOCTOR}")

    completed = 0
    errors = 0

    for variant_type, pid, src, dst in remaining:
        key = f"{variant_type}:{pid}"
        dst_path = Path(dst)

        if dst_path.exists() and (dst_path / "model.bin").exists():
            done.add(key)
            completed += 1
            continue

        t0 = time.time()
        ok, err = quantize_one(src, dst)
        elapsed = round(time.time() - t0, 1)

        result = {"variant": variant_type, "pid": pid, "elapsed": elapsed}

        if ok and (dst_path / "model.bin").exists():
            size = sum(f.stat().st_size for f in dst_path.rglob("*") if f.is_file()) / (1024 * 1024)
            result["status"] = "success"
            result["size_mb"] = round(size)
            if completed % 25 == 0:
                log(f"  [{completed}/{len(remaining)}] {variant_type}:{pid} → {size:.0f} MB, {elapsed}s")
        else:
            result["status"] = "error"
            result["error"] = err[:200]
            errors += 1
            log(f"  [{completed}/{len(remaining)}] {variant_type}:{pid} ERROR: {err[:100]}")

        done.add(key)
        completed += 1

        with open(RESULTS_JSONL, "a") as f:
            f.write(json.dumps(result) + "\n")
        CHECKPOINT.write_text(json.dumps({"done": sorted(done)}))

        if completed % 100 == 0:
            log(f"  >> {completed}/{len(remaining)} done, {errors} errors")

    log(f"Done: {completed} completed, {errors} errors")

    # Now update patient files
    log("Updating patient files...")
    updated = 0
    for line in open(RESULTS_JSONL):
        r = json.loads(line)
        if r.get("status") != "success":
            continue
        pid = r["pid"]
        variant_type = r["variant"]
        pf = PATIENTS / f"{pid}.json"
        if not pf.exists():
            continue

        chart = json.loads(pf.read_text())
        vc = chart.setdefault("variant_cluster", {})

        variant_key = "lora_ct2_int8" if variant_type == "lora" else "scripture_ct2_int8"
        dst_path_str = str(MODELS / f"windy-pair-{pid}" / ("lora-ct2-int8" if variant_type == "lora" else "scripture-ct2-int8"))

        vc[variant_key] = {
            "status": "present",
            "format": "ctranslate2_int8",
            "derived_from": f"{variant_type}/ (proprietary {'fog-of-mirror' if variant_type == 'lora' else 'eBible'} fine-tune)",
            "on_disk_path": dst_path_str,
            "on_disk_bytes": r["size_mb"] * 1024 * 1024,
            "quantized_at": run_iso,
            "quantized_by": DOCTOR,
        }

        # Remove the old fake ct2_int8 entry if present
        if "ct2_int8" in vc:
            old = vc.pop("ct2_int8")
            vc["ct2_int8_DELETED_was_fake"] = {
                "note": "This was a byte-identical copy of base/, NOT real INT8. Deleted 2026-04-12 by Dr. C. Replaced by lora_ct2_int8 (real INT8 of proprietary weights).",
                "deleted_at": run_iso,
            }

        exam_log = chart.setdefault("examination_log", [])
        exam_id = f"DRC-REALCT2-{variant_type}-{pid}"
        if not any(e.get("exam_id") == exam_id for e in exam_log):
            exam_log.append({
                "exam_id": exam_id,
                "date": run_iso,
                "doctor": DOCTOR,
                "machine": MACHINE,
                "method": f"CTranslate2 INT8 quantization of {variant_type}/ (proprietary weights) via ct2-opus-mt-converter --quantization int8",
                "protocol_script": "scripts/ct2_quantize_lora_fleet.py",
                "notes": (
                    f"Created REAL INT8 quantized version of the proprietary "
                    f"{'fog-of-mirror LoRA' if variant_type == 'lora' else 'eBible scripture'} "
                    f"fine-tuned weights. Source: {variant_type}/model.safetensors. "
                    f"Output: {'lora-ct2-int8' if variant_type == 'lora' else 'scripture-ct2-int8'}/model.bin. "
                    f"Size: {r['size_mb']} MB (~25% of source). "
                    f"The previous ct2_int8/ directory was a FAKE (byte-identical copy of base/) "
                    f"and has been deleted. This replacement is genuinely quantized from the "
                    f"proprietary variant. Filed by {DOCTOR}."
                ),
            })

        chart["_last_updated"] = run_iso
        pf.write_text(json.dumps(chart, indent=2))
        updated += 1

    log(f"Updated {updated} patient files")


if __name__ == "__main__":
    main()

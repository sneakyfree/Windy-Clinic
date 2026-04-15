#!/usr/bin/env python3
"""Phase 3d — STT/ASR Quality Harness for Windy Lingua models.

Tests whisper-based Windy Lingua STT models on a small FLEURS sample per
language. Measures:
  - WER (word error rate) against reference transcripts
  - Latency per clip (ms)
  - RTF (real-time factor)
  - Peak GPU memory

Output: per-model JSONL row + per-patient signed Dr. C exam entry.

Usage:
  python3 phase3d_stt_harness.py [--models PID ...] [--samples N] [--fresh]

This harness is separate from grand_rounds_harness.py because GR1 targets
MarianMT seq2seq translation, not speech. Speech needs a different
methodology (WER, audio robustness, RTF).

Doctor: Opus 4.6 Opus-Claw (Dr. C)
Date:   2026-04-11
"""

import argparse
import gc
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import tarfile
import tempfile
import csv
import soundfile as sf
import numpy as np
import torch
from huggingface_hub import hf_hub_download
from transformers import WhisperForConditionalGeneration, WhisperProcessor

import jiwer  # noqa: needed for wer

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
STT_DIR = CLINIC / "stt-models"
OUT_DIR = CLINIC / "grand-rounds" / "phase3d_stt"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_JSONL = OUT_DIR / "phase3d_results.jsonl"
LOG_PATH = OUT_DIR / "phase3d_run.log"
CHECKPOINT = OUT_DIR / "phase3d_checkpoint.json"

STT_RESTORE = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/restore_20260411/stt")

DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"
MACHINE = "Veron-1 (RTX 5090, Mt Pleasant SC)"

# FLEURS language code mapping. windy-lingua-{pid} -> fleurs subset.
# FLEURS uses BCP-47-ish codes; we pick the most common variant per language.
LANG_MAP = {
    "windy-lingua-spanish": {"fleurs": "es_419", "whisper_lang": "spanish", "iso": "es"},
    "windy-lingua-chinese": {"fleurs": "cmn_hans_cn", "whisper_lang": "chinese", "iso": "zh"},
    "windy-lingua-hindi":   {"fleurs": "hi_in", "whisper_lang": "hindi", "iso": "hi"},
    "windy-lingua-french":  {"fleurs": "fr_fr", "whisper_lang": "french", "iso": "fr"},
    "windy-lingua-arabic":  {"fleurs": "ar_eg", "whisper_lang": "arabic", "iso": "ar"},
    # ct2 variants have the same underlying model
    "windy-lingua-hindi-ct2": {"fleurs": "hi_in", "whisper_lang": "hindi", "iso": "hi",
                                "skip_reason": "ct2 format not loadable via transformers; needs separate CTranslate2 harness"},
}


def log(msg: str):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def load_checkpoint():
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {"done": [], "errors": []}


def save_checkpoint(state):
    CHECKPOINT.write_text(json.dumps(state, indent=2))


def normalize_for_wer(text: str) -> str:
    """Minimal normalization for WER. Lowercase, strip punctuation."""
    import re
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


FLEURS_CACHE = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/restore_20260411/_fleurs_cache")


def load_fleurs_samples(subset: str, n: int = 15):
    """Download dev split from google/fleurs (direct file pull, no datasets lib)."""
    FLEURS_CACHE.mkdir(parents=True, exist_ok=True)
    lang_cache = FLEURS_CACHE / subset
    lang_cache.mkdir(parents=True, exist_ok=True)

    # Download dev tsv and dev audio archive
    tsv_path = hf_hub_download(
        repo_id="google/fleurs",
        filename=f"data/{subset}/dev.tsv",
        repo_type="dataset",
        cache_dir=str(FLEURS_CACHE / "hf_cache"),
    )
    audio_tar = hf_hub_download(
        repo_id="google/fleurs",
        filename=f"data/{subset}/audio/dev.tar.gz",
        repo_type="dataset",
        cache_dir=str(FLEURS_CACHE / "hf_cache"),
    )

    # Parse TSV: format is id\tfilename\traw_transcription\tnormalized\tnum_samples\tgender
    rows = []
    with open(tsv_path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 4:
                rows.append({"filename": parts[1], "raw": parts[2], "norm": parts[3]})

    # Extract the first n audio files
    audio_dir = lang_cache / "audio_dev"
    audio_dir.mkdir(exist_ok=True)
    needed = {r["filename"] for r in rows[:n]}
    with tarfile.open(audio_tar) as tar:
        for member in tar.getmembers():
            fname = os.path.basename(member.name)
            if fname in needed:
                # Extract just this file
                f = tar.extractfile(member)
                if f:
                    (audio_dir / fname).write_bytes(f.read())

    samples = []
    for r in rows[:n]:
        audio_path = audio_dir / r["filename"]
        if not audio_path.exists():
            continue
        audio, sr = sf.read(str(audio_path))
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        samples.append({
            "audio": audio.astype("float32"),
            "sampling_rate": sr,
            "reference": r["norm"] or r["raw"],
        })
    return samples


def evaluate_model(patient_id: str, model_path: Path, cfg: dict, samples: list, device: str) -> dict:
    """Load model, transcribe samples, compute WER/RTF/latency."""
    log(f"  loading {patient_id} from {model_path}")

    t_load = time.time()
    processor = WhisperProcessor.from_pretrained(str(model_path))
    model = WhisperForConditionalGeneration.from_pretrained(str(model_path))
    model.to(device)
    model.eval()
    load_time_s = time.time() - t_load

    # Fix fine-tuned whisper models that ship an empty suppress_tokens list
    # (causes IndexError in transformers generate).
    gc_cfg = model.generation_config
    if getattr(gc_cfg, "suppress_tokens", None) is not None and len(gc_cfg.suppress_tokens) < 2:
        gc_cfg.suppress_tokens = None
    if getattr(gc_cfg, "begin_suppress_tokens", None) is not None and len(gc_cfg.begin_suppress_tokens) < 1:
        gc_cfg.begin_suppress_tokens = None

    gpu_mem_before = torch.cuda.memory_allocated() / (1024 ** 2) if device == "cuda" else 0
    torch.cuda.reset_peak_memory_stats() if device == "cuda" else None

    forced_decoder_ids = None
    try:
        forced_decoder_ids = processor.get_decoder_prompt_ids(
            language=cfg["whisper_lang"], task="transcribe"
        )
    except Exception:
        pass  # fall back to model defaults

    refs = []
    hyps = []
    latencies = []
    audio_durations = []

    with torch.inference_mode():
        for s in samples:
            audio = s["audio"]
            sr = s["sampling_rate"]
            duration_s = len(audio) / sr
            audio_durations.append(duration_s)

            inputs = processor(audio, sampling_rate=sr, return_tensors="pt")
            input_features = inputs.input_features.to(device)

            t0 = time.time()
            gen_kwargs = {}
            if forced_decoder_ids is not None:
                gen_kwargs["forced_decoder_ids"] = forced_decoder_ids
            try:
                pred = model.generate(input_features, max_new_tokens=200, **gen_kwargs)
            except Exception as e:
                # Retry without forced_decoder_ids
                pred = model.generate(input_features, max_new_tokens=200)
            latencies.append((time.time() - t0) * 1000)

            hyp = processor.batch_decode(pred, skip_special_tokens=True)[0]
            refs.append(normalize_for_wer(s["reference"]))
            hyps.append(normalize_for_wer(hyp))

    peak_gpu_mb = torch.cuda.max_memory_allocated() / (1024 ** 2) if device == "cuda" else 0

    wer = jiwer.wer(refs, hyps)
    cer = jiwer.cer(refs, hyps)

    mean_latency_ms = sum(latencies) / len(latencies)
    total_audio_s = sum(audio_durations)
    total_inference_s = sum(latencies) / 1000
    rtf = total_inference_s / total_audio_s  # <1 is real-time

    # Cleanup
    del model, processor
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()

    return {
        "patient_id": patient_id,
        "n_samples": len(samples),
        "wer": round(wer, 4),
        "cer": round(cer, 4),
        "mean_latency_ms": round(mean_latency_ms, 1),
        "p95_latency_ms": round(sorted(latencies)[int(0.95 * len(latencies))], 1) if len(latencies) >= 20 else round(max(latencies), 1),
        "total_audio_s": round(total_audio_s, 2),
        "rtf": round(rtf, 4),
        "peak_gpu_mb": round(peak_gpu_mb, 1),
        "load_time_s": round(load_time_s, 2),
        "samples": [
            {"ref": r[:100], "hyp": h[:100]} for r, h in zip(refs[:5], hyps[:5])
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=None, help="Filter to specific patient IDs")
    ap.add_argument("--samples", type=int, default=20, help="FLEURS samples per model")
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log(f"Phase 3d STT harness — device={device}")
    log(f"Doctor: {DOCTOR}")
    log(f"Samples per model: {args.samples}")

    checkpoint = {"done": [], "errors": []} if args.fresh else load_checkpoint()
    done = set(checkpoint["done"])

    targets = list(LANG_MAP.keys())
    if args.models:
        targets = [t for t in targets if t in args.models]

    # Cache samples per language to avoid re-downloading
    samples_cache = {}

    for pid in targets:
        if pid in done:
            log(f"  {pid}: already done")
            continue

        cfg = LANG_MAP[pid]
        if "skip_reason" in cfg:
            log(f"  {pid}: SKIP — {cfg['skip_reason']}")
            checkpoint["errors"].append({"pid": pid, "reason": "skipped_" + cfg["skip_reason"][:50]})
            save_checkpoint(checkpoint)
            continue

        # Model path
        model_path = STT_RESTORE / pid
        if not (model_path / "model.safetensors").exists():
            log(f"  {pid}: SKIP — model not present at {model_path}")
            checkpoint["errors"].append({"pid": pid, "reason": "model_not_local"})
            save_checkpoint(checkpoint)
            continue

        # Load FLEURS samples
        fleurs = cfg["fleurs"]
        if fleurs not in samples_cache:
            log(f"  loading FLEURS {fleurs} ({args.samples} samples)")
            try:
                samples_cache[fleurs] = load_fleurs_samples(fleurs, args.samples)
            except Exception as e:
                log(f"    FLEURS load error: {type(e).__name__}: {e}")
                checkpoint["errors"].append({"pid": pid, "reason": f"fleurs_{type(e).__name__}"})
                save_checkpoint(checkpoint)
                continue

        # Run
        try:
            t0 = time.time()
            result = evaluate_model(pid, model_path, cfg, samples_cache[fleurs], device)
            result["_phase3d_filed_by"] = DOCTOR
            result["_phase3d_filed_at"] = datetime.now(timezone.utc).isoformat()
            result["_phase3d_elapsed_s"] = round(time.time() - t0, 1)
            result["language"] = cfg["iso"]
            result["fleurs_subset"] = fleurs

            with open(RESULTS_JSONL, "a") as f:
                f.write(json.dumps(result) + "\n")
            log(f"  {pid}: WER={result['wer']}, RTF={result['rtf']}, "
                f"lat={result['mean_latency_ms']}ms, gpu={result['peak_gpu_mb']}MB")
            checkpoint["done"].append(pid)
        except Exception as e:
            import traceback
            log(f"  {pid}: ERROR {type(e).__name__}: {e}")
            log(traceback.format_exc())
            checkpoint["errors"].append({"pid": pid, "reason": f"{type(e).__name__}: {e}"})

        save_checkpoint(checkpoint)

    log(f"Phase 3d done. Completed: {len(checkpoint['done'])}, errors: {len(checkpoint['errors'])}")


if __name__ == "__main__":
    main()

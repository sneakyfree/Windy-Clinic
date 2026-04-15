#!/usr/bin/env python3
"""Full STT certification — test ALL rebuilt + existing Windy STT models.

Includes the 10 English voice models (rebuilt from whisper adapters) and the
5 Lingua per-language models. Each gets a signed Dr. C quality certification
entry in its patient file.

Uses FLEURS dev splits for each language.
English: en_us
Spanish: es_419
Chinese: cmn_hans_cn
Hindi: hi_in
French: fr_fr
Arabic: ar_eg

Doctor: Opus 4.6 Opus-Claw (Dr. C)
"""

import gc
import json
import os
import re
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from huggingface_hub import hf_hub_download
from transformers import WhisperForConditionalGeneration, WhisperProcessor

import jiwer

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
STT_DIR = CLINIC / "stt-models"
OUT_DIR = CLINIC / "grand-rounds" / "phase3d_full_stt"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS = OUT_DIR / "results.jsonl"
LOG_PATH = OUT_DIR / "run.log"

REBUILT = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/restore_20260411/stt_rebuilt")
LINGUA = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/restore_20260411/stt")
FLEURS_CACHE = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/restore_20260411/_fleurs_cache")

DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"
MACHINE = "Veron-1 (RTX 5090, Mt Pleasant SC)"

MODELS = [
    # 10 English voice models
    {"pid": "windy-nano", "path": REBUILT / "windy-nano", "fleurs": "en_us", "lang": "english"},
    {"pid": "windy-lite", "path": REBUILT / "windy-lite", "fleurs": "en_us", "lang": "english"},
    {"pid": "windy-core", "path": REBUILT / "windy-core", "fleurs": "en_us", "lang": "english"},
    {"pid": "windy-plus", "path": REBUILT / "windy-plus", "fleurs": "en_us", "lang": "english"},
    {"pid": "windy-turbo", "path": REBUILT / "windy-turbo", "fleurs": "en_us", "lang": "english"},
    {"pid": "windy-pro-engine", "path": REBUILT / "windy-pro-engine", "fleurs": "en_us", "lang": "english"},
    {"pid": "windy-edge", "path": REBUILT / "windy-edge", "fleurs": "en_us", "lang": "english"},
    {"pid": "windy-distil-small", "path": REBUILT / "windy-distil-small", "fleurs": "en_us", "lang": "english"},
    {"pid": "windy-distil-medium", "path": REBUILT / "windy-distil-medium", "fleurs": "en_us", "lang": "english"},
    {"pid": "windy-distil-large", "path": REBUILT / "windy-distil-large", "fleurs": "en_us", "lang": "english"},
    # 5 Lingua per-language models
    {"pid": "windy-lingua-spanish", "path": LINGUA / "windy-lingua-spanish", "fleurs": "es_419", "lang": "spanish"},
    {"pid": "windy-lingua-chinese", "path": LINGUA / "windy-lingua-chinese", "fleurs": "cmn_hans_cn", "lang": "chinese"},
    {"pid": "windy-lingua-hindi", "path": LINGUA / "windy-lingua-hindi", "fleurs": "hi_in", "lang": "hindi"},
    {"pid": "windy-lingua-french", "path": LINGUA / "windy-lingua-french", "fleurs": "fr_fr", "lang": "french"},
    {"pid": "windy-lingua-arabic", "path": LINGUA / "windy-lingua-arabic", "fleurs": "ar_eg", "lang": "arabic"},
]

N_SAMPLES = 15


def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def normalize_for_wer(text):
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def load_fleurs(subset, n=15):
    lang_cache = FLEURS_CACHE / subset
    lang_cache.mkdir(parents=True, exist_ok=True)
    tsv_path = hf_hub_download("google/fleurs", f"data/{subset}/dev.tsv",
                                repo_type="dataset", cache_dir=str(FLEURS_CACHE / "hf_cache"))
    audio_tar = hf_hub_download("google/fleurs", f"data/{subset}/audio/dev.tar.gz",
                                 repo_type="dataset", cache_dir=str(FLEURS_CACHE / "hf_cache"))
    rows = []
    with open(tsv_path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 4:
                rows.append({"filename": parts[1], "raw": parts[2], "norm": parts[3]})
    audio_dir = lang_cache / "audio_dev"
    audio_dir.mkdir(exist_ok=True)
    needed = {r["filename"] for r in rows[:n]}
    with tarfile.open(audio_tar) as tar:
        for member in tar.getmembers():
            fname = os.path.basename(member.name)
            if fname in needed and not (audio_dir / fname).exists():
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


def test_model(pid, model_path, lang, samples, device="cuda"):
    processor = WhisperProcessor.from_pretrained(str(model_path))
    model = WhisperForConditionalGeneration.from_pretrained(str(model_path))
    model.to(device).eval()

    gc_cfg = model.generation_config
    if getattr(gc_cfg, "suppress_tokens", None) is not None and len(gc_cfg.suppress_tokens) < 2:
        gc_cfg.suppress_tokens = None
    if getattr(gc_cfg, "begin_suppress_tokens", None) is not None and len(gc_cfg.begin_suppress_tokens) < 1:
        gc_cfg.begin_suppress_tokens = None

    forced = None
    try:
        forced = processor.get_decoder_prompt_ids(language=lang, task="transcribe")
    except Exception:
        pass

    torch.cuda.reset_peak_memory_stats()
    refs, hyps, latencies, durations = [], [], [], []
    with torch.inference_mode():
        for s in samples:
            dur = len(s["audio"]) / s["sampling_rate"]
            durations.append(dur)
            inputs = processor(s["audio"], sampling_rate=s["sampling_rate"], return_tensors="pt")
            feats = inputs.input_features.to(device)
            t0 = time.time()
            kwargs = {}
            if forced:
                kwargs["forced_decoder_ids"] = forced
            try:
                pred = model.generate(feats, max_new_tokens=200, **kwargs)
            except Exception:
                pred = model.generate(feats, max_new_tokens=200)
            latencies.append((time.time() - t0) * 1000)
            hyp = processor.batch_decode(pred, skip_special_tokens=True)[0]
            refs.append(normalize_for_wer(s["reference"]))
            hyps.append(normalize_for_wer(hyp))

    peak_gpu = torch.cuda.max_memory_allocated() / (1024**2)
    wer = jiwer.wer(refs, hyps) if refs else 1.0
    cer = jiwer.cer(refs, hyps) if refs else 1.0
    total_audio = sum(durations)
    total_infer = sum(latencies) / 1000
    rtf = total_infer / total_audio if total_audio > 0 else 0

    result = {
        "patient_id": pid,
        "n_samples": len(samples),
        "wer": round(wer, 4),
        "cer": round(cer, 4),
        "mean_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
        "p95_latency_ms": round(sorted(latencies)[int(0.95 * len(latencies))], 1) if len(latencies) >= 10 else round(max(latencies, default=0), 1),
        "rtf": round(rtf, 4),
        "peak_gpu_mb": round(peak_gpu, 1),
        "language": lang,
        "samples": [{"ref": r[:100], "hyp": h[:100]} for r, h in zip(refs[:5], hyps[:5])],
    }

    del model, processor
    gc.collect()
    torch.cuda.empty_cache()
    return result


def update_patient(pid, result):
    pf = STT_DIR / f"{pid}.json"
    if not pf.exists():
        return
    chart = json.loads(pf.read_text())
    log_list = chart.setdefault("examination_log", [])
    exam_id = f"DRC-STTCERT-{pid}"
    if any(e.get("exam_id") == exam_id for e in log_list):
        return
    wer_pct = result["wer"] * 100
    if wer_pct <= 10:
        grade = "A"
    elif wer_pct <= 20:
        grade = "B"
    elif wer_pct <= 40:
        grade = "C"
    elif wer_pct <= 60:
        grade = "D"
    else:
        grade = "F"

    log_list.append({
        "exam_id": exam_id,
        "date": datetime.now(timezone.utc).isoformat(),
        "doctor": DOCTOR,
        "machine": MACHINE,
        "method": f"Phase 3d STT certification — FLEURS {result['language']} dev ({result['n_samples']} samples), WER + CER + RTF + latency + peak VRAM",
        "protocol_script": "scripts/phase3d_full_stt_cert.py",
        "variants_tested": ["base"],
        "results": {
            "base": {
                "wer": result["wer"],
                "cer": result["cer"],
                "wer_pct": round(wer_pct, 1),
                "grade": grade,
                "mean_latency_ms": result["mean_latency_ms"],
                "p95_latency_ms": result["p95_latency_ms"],
                "rtf": result["rtf"],
                "peak_gpu_mb": result["peak_gpu_mb"],
                "n_samples": result["n_samples"],
                "language": result["language"],
                "fleurs_subset": result.get("fleurs_subset"),
                "sample_transcriptions": result.get("samples", []),
            }
        },
        "notes": (
            f"Dr. C independent STT quality certification. "
            f"WER: {wer_pct:.1f}% ({grade}). "
            f"RTF: {result['rtf']:.4f} (real-time factor, <1 = faster than real-time). "
            f"Mean latency: {result['mean_latency_ms']:.1f} ms. "
            f"Peak GPU: {result['peak_gpu_mb']:.0f} MB. "
            f"Tested on FLEURS {result['language']} dev split ({result['n_samples']} clips). "
            f"Filed by {DOCTOR} on 2026-04-12."
        ),
    })
    consensus = chart.setdefault("consensus", {})
    consensus["stt_wer"] = result["wer"]
    consensus["stt_grade"] = grade
    consensus["stt_certified_by"] = DOCTOR
    consensus["stt_certified_at"] = datetime.now(timezone.utc).isoformat()

    chart["_last_updated"] = datetime.now(timezone.utc).isoformat()
    pf.write_text(json.dumps(chart, indent=2))


def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    log(f"Full STT certification — {len(MODELS)} models, {N_SAMPLES} samples each")
    log(f"Doctor: {DOCTOR}, device: {device}")

    fleurs_cache = {}
    for m in MODELS:
        pid = m["pid"]
        model_path = m["path"]
        fleurs_key = m["fleurs"]
        lang = m["lang"]

        if not model_path.exists():
            log(f"  SKIP {pid}: model not found at {model_path}")
            continue
        has_weights = (model_path / "model.safetensors").exists() or \
                      (model_path / "model-00001-of-00002.safetensors").exists()
        if not has_weights:
            log(f"  SKIP {pid}: no weight files")
            continue

        if fleurs_key not in fleurs_cache:
            log(f"  Loading FLEURS {fleurs_key}")
            try:
                fleurs_cache[fleurs_key] = load_fleurs(fleurs_key, N_SAMPLES)
            except Exception as e:
                log(f"    FLEURS error: {e}")
                continue
        samples = fleurs_cache[fleurs_key]
        if not samples:
            log(f"  SKIP {pid}: no FLEURS samples loaded")
            continue

        log(f"  Testing {pid} ({lang}, {len(samples)} samples)")
        try:
            t0 = time.time()
            result = test_model(pid, model_path, lang, samples, device)
            result["_elapsed_s"] = round(time.time() - t0, 1)
            result["fleurs_subset"] = fleurs_key
            result["_filed_by"] = DOCTOR
            result["_filed_at"] = datetime.now(timezone.utc).isoformat()

            with open(RESULTS, "a") as f:
                f.write(json.dumps(result) + "\n")
            update_patient(pid, result)
            log(f"    WER={result['wer']*100:.1f}%  RTF={result['rtf']:.3f}  lat={result['mean_latency_ms']:.0f}ms  gpu={result['peak_gpu_mb']:.0f}MB")
        except Exception as e:
            import traceback
            log(f"    ERROR: {type(e).__name__}: {e}")
            log(traceback.format_exc())

    log("Done")


if __name__ == "__main__":
    main()

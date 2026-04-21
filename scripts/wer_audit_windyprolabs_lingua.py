#!/usr/bin/env python3
"""WER audit: test all WindyProLabs/windy-lingua-* STT models against FLEURS.

Why: the 46 windy-lingua-* models were uploaded 2026-03-10 (Dr. A era) with no
quality certification in our current methodology. They are built on 35 different
community Whisper fine-tunes of wildly varying sizes and base dialects (including
a Swiss-German model misfiled under "de" and tiny-Whisper for Japanese and Igbo).
Before we duplicate_repo any of them to WindyWord/listen-windy-lingua-*, we need
WER numbers we trust.

Method: for each non-ct2 lingua model (ct2 variants are CPU-only copies of the
same weights), download via the Veron1 token, stream 50 FLEURS clips of the
target language, transcribe, compute WER/CER/RTF + peak-VRAM. Write one JSONL
row per model to /srv/repos/windy-pro/THE_CLINIC/grand-rounds/wpl_audit/.

Output doubles as input to the port-vs-retrain decision per language.

Doctor: Opus 4.6 Opus-Claw (Dr. C)
"""
import argparse
import gc
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Load the Veron1 token from the lockbox (fetched earlier this session)
LOCKBOX = Path("/tmp/lockbox.md")
if LOCKBOX.exists():
    _content = LOCKBOX.read_text()
    _m = re.search(r"\*\*HuggingFaceVeron1\*\*.*?\*\*Token:\*\*\s*`(hf_[A-Za-z0-9]+)`", _content, re.DOTALL)
    if _m:
        os.environ["HF_TOKEN"] = _m.group(1)

import tarfile
import tempfile
import csv

import soundfile as sf
import numpy as np
import torch
import jiwer
from huggingface_hub import hf_hub_download, snapshot_download
from transformers import WhisperForConditionalGeneration, WhisperProcessor

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
OUT_DIR = CLINIC / "grand-rounds" / "wpl_audit"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS = OUT_DIR / "wer_results.jsonl"
LOG = OUT_DIR / "wer_run.log"
CKPT = OUT_DIR / "wer_checkpoint.json"

DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"
MACHINE = "Veron-1 (RTX 5090, Mt Pleasant SC)"

# Map WindyProLabs windy-lingua-{slug} → (FLEURS subset, whisper language name, ISO)
LINGUA_MAP = {
    "am":       ("am_et",       "amharic",      "am"),
    "arabic":   ("ar_eg",       "arabic",       "ar"),
    "az":       ("az_az",       "azerbaijani",  "az"),
    "bn":       ("bn_in",       "bengali",      "bn"),
    "ca":       ("ca_es",       "catalan",      "ca"),
    "chinese":  ("cmn_hans_cn", "chinese",      "zh"),
    "cs":       ("cs_cz",       "czech",        "cs"),
    "de":       ("de_de",       "german",       "de"),
    "fa":       ("fa_ir",       "persian",      "fa"),
    "fi":       ("fi_fi",       "finnish",      "fi"),
    "french":   ("fr_fr",       "french",       "fr"),
    "gu":       ("gu_in",       "gujarati",     "gu"),
    "he":       ("he_il",       "hebrew",       "he"),
    "hindi":    ("hi_in",       "hindi",        "hi"),
    "hu":       ("hu_hu",       "hungarian",    "hu"),
    "hy":       ("hy_am",       "armenian",     "hy"),
    "ig":       ("ig_ng",       "igbo",         "ig"),
    "it":       ("it_it",       "italian",      "it"),
    "ja":       ("ja_jp",       "japanese",     "ja"),
    "kk":       ("kk_kz",       "kazakh",       "kk"),
    "km":       ("km_kh",       "khmer",        "km"),
    "ml":       ("ml_in",       "malayalam",    "ml"),
    "mn":       ("mn_mn",       "mongolian",    "mn"),
    "mr":       ("mr_in",       "marathi",      "mr"),
    "ms":       ("ms_my",       "malay",        "ms"),
    "nl":       ("nl_nl",       "dutch",        "nl"),
    "no":       ("nb_no",       "norwegian",    "no"),
    "pa":       ("pa_in",       "punjabi",      "pa"),
    "ps":       ("ps_af",       "pashto",       "ps"),
    "pt":       ("pt_br",       "portuguese",   "pt"),
    "ro":       ("ro_ro",       "romanian",     "ro"),
    "si":       ("si_lk",       "sinhalese",    "si"),  # "sinhalese" is whisper's name for si
    "spanish":  ("es_419",      "spanish",      "es"),
    "te":       ("te_in",       "telugu",       "te"),
}

FLEURS_REPO = "google/fleurs"
SAMPLES_PER_MODEL = 50  # fewer than Phase 3d's 100, more than audit's 15


def log(msg: str):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def load_fleurs_samples(subset: str, n: int = SAMPLES_PER_MODEL):
    """Download FLEURS dev set for a language and return n audio+transcript pairs."""
    # FLEURS has audio tars and metadata TSVs on HF. Fetch dev metadata + audio tar.
    try:
        meta_path = hf_hub_download(FLEURS_REPO, f"data/{subset}/dev.tsv", repo_type="dataset")
    except Exception as e:
        return None, f"meta download failed: {str(e)[:120]}"
    try:
        tar_path = hf_hub_download(FLEURS_REPO, f"data/{subset}/audio/dev.tar.gz", repo_type="dataset")
    except Exception as e:
        return None, f"audio tar download failed: {str(e)[:120]}"

    # Parse tsv
    entries = {}
    with open(meta_path, encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        for row in reader:
            if len(row) < 4:
                continue
            # Format: id, filename, raw_transcription, normalized, num_samples, gender
            fid, fname = row[0], row[1]
            ref = row[3] if len(row) > 3 else row[2]
            entries[fname] = ref

    samples = []
    with tarfile.open(tar_path, "r:gz") as tar:
        for member in tar:
            if not member.isfile() or not member.name.endswith(".wav"):
                continue
            base = os.path.basename(member.name)
            if base not in entries:
                continue
            ref = entries[base]
            f = tar.extractfile(member)
            audio, sr = sf.read(f)
            samples.append({"audio": audio, "sr": sr, "ref": ref})
            if len(samples) >= n:
                break
    return samples, None


def evaluate(model_repo: str, samples: list, whisper_lang: str, device: str = "cuda"):
    """Load model, transcribe samples, return metrics."""
    t0 = time.time()
    try:
        local = snapshot_download(model_repo, allow_patterns=["*.safetensors", "*.json", "*.txt"])
    except Exception as e:
        return {"status": "load_error", "error": f"snapshot: {str(e)[:160]}"}
    try:
        processor = WhisperProcessor.from_pretrained(local)
        model = WhisperForConditionalGeneration.from_pretrained(local).to(device).eval()
    except Exception as e:
        return {"status": "load_error", "error": f"from_pretrained: {str(e)[:160]}"}
    load_time = time.time() - t0

    # Clear any pre-set forced_decoder_ids — we'll pass language/task explicitly.
    # Some community Whisper fine-tunes have non-standard decoder prompt layouts
    # that conflict with forced_decoder_ids set on model.config.
    try:
        model.config.forced_decoder_ids = None
        if hasattr(model, "generation_config"):
            model.generation_config.forced_decoder_ids = None
    except Exception:
        pass

    refs, hyps, lats = [], [], []
    total_audio = 0.0
    peak_mem = 0
    torch.cuda.reset_peak_memory_stats(device)
    try:
        for s in samples:
            audio = s["audio"]
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            audio = audio.astype(np.float32)
            if s["sr"] != 16000:
                import scipy.signal
                audio = scipy.signal.resample_poly(audio, 16000, s["sr"]).astype(np.float32)
            duration = len(audio) / 16000.0
            total_audio += duration

            t1 = time.time()
            try:
                with torch.inference_mode():
                    inputs = processor(audio, sampling_rate=16000, return_tensors="pt").input_features.to(device)
                    # Prefer modern language/task kwargs (supported in transformers >=4.38)
                    try:
                        ids = model.generate(inputs, max_length=200, language=whisper_lang, task="transcribe")
                    except TypeError:
                        # Older transformers path — fall back to no kwargs
                        ids = model.generate(inputs, max_length=200)
                    text = processor.batch_decode(ids, skip_special_tokens=True)[0].strip()
            except Exception as per_sample_e:
                # Skip this sample but keep accumulating
                text = ""
                if len(refs) == 0 and "index" in str(per_sample_e):
                    raise  # surface error if it's the first sample (probably model-wide bug)
            lats.append((time.time() - t1) * 1000.0)
            refs.append(s["ref"])
            hyps.append(text)
        peak_mem = torch.cuda.max_memory_allocated(device) / 1e6
    except Exception as e:
        del model
        gc.collect()
        torch.cuda.empty_cache()
        return {"status": "infer_error", "error": str(e)[:200], "load_time_s": round(load_time, 2)}

    try:
        wer = jiwer.wer(refs, hyps)
        cer = jiwer.cer(refs, hyps)
    except Exception:
        wer = cer = None

    del model
    gc.collect()
    torch.cuda.empty_cache()

    return {
        "status": "complete",
        "n_samples": len(samples),
        "wer": round(wer, 4) if wer is not None else None,
        "cer": round(cer, 4) if cer is not None else None,
        "mean_latency_ms": round(float(np.mean(lats)), 1) if lats else None,
        "p95_latency_ms": round(float(np.percentile(lats, 95)), 1) if lats else None,
        "total_audio_s": round(total_audio, 1),
        "rtf": round(sum(lats) / 1000.0 / total_audio, 4) if total_audio > 0 else None,
        "peak_gpu_mb": round(peak_mem, 1),
        "load_time_s": round(load_time, 2),
        "samples": [{"ref": r[:200], "hyp": h[:200]} for r, h in list(zip(refs, hyps))[:3]],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", help="Specific slugs only (e.g. de ja ig)")
    ap.add_argument("--samples", type=int, default=SAMPLES_PER_MODEL)
    ap.add_argument("--resume", action="store_true", help="Skip already-done models")
    args = ap.parse_args()

    log(f"WER audit for WindyProLabs windy-lingua-* models")
    log(f"Doctor: {DOCTOR}")
    log(f"Samples per model: {args.samples}")

    targets = list(LINGUA_MAP.items())
    if args.models:
        targets = [(k, v) for k, v in targets if k in args.models]

    done = set()
    if args.resume and RESULTS.exists():
        with open(RESULTS) as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    if r.get("status") == "complete":
                        done.add(r["slug"])
    log(f"Total targets: {len(targets)}, already done: {len(done)}")

    for i, (slug, (fleurs_subset, whisper_lang, iso)) in enumerate(targets, 1):
        if slug in done:
            log(f"[{i}/{len(targets)}] {slug}: skip (resume)")
            continue
        log(f"[{i}/{len(targets)}] {slug} ← FLEURS {fleurs_subset}, whisper lang '{whisper_lang}'")
        t0 = time.time()

        samples, err = load_fleurs_samples(fleurs_subset, args.samples)
        if samples is None:
            row = {
                "slug": slug, "repo": f"WindyProLabs/windy-lingua-{slug}",
                "fleurs_subset": fleurs_subset, "whisper_lang": whisper_lang, "iso": iso,
                "status": "fleurs_unavailable", "error": err,
                "_filed_at": datetime.now(timezone.utc).isoformat(),
            }
            with open(RESULTS, "a") as f:
                f.write(json.dumps(row) + "\n")
            log(f"    FLEURS unavailable: {err}")
            continue

        result = evaluate(f"WindyProLabs/windy-lingua-{slug}", samples, whisper_lang)
        result.update({
            "slug": slug,
            "repo": f"WindyProLabs/windy-lingua-{slug}",
            "fleurs_subset": fleurs_subset,
            "whisper_lang": whisper_lang,
            "iso": iso,
            "elapsed_s": round(time.time() - t0, 1),
            "_filed_at": datetime.now(timezone.utc).isoformat(),
            "_filed_by": DOCTOR,
        })
        with open(RESULTS, "a") as f:
            f.write(json.dumps(result) + "\n")

        summary = ""
        if result.get("status") == "complete":
            summary = f"WER={result['wer']} CER={result['cer']} RTF={result['rtf']} lat={result['mean_latency_ms']}ms"
        else:
            summary = f"status={result.get('status')} err={str(result.get('error',''))[:80]}"
        log(f"    {summary}  ({result.get('elapsed_s','?')}s)")

    log("Complete.")


if __name__ == "__main__":
    main()

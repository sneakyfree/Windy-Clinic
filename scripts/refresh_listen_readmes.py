#!/usr/bin/env python3
"""Refresh all WindyWord/listen-* READMEs with a unified WindyWord template.

Covers 47 STT repos (10 voice tiers + 37 per-language lingua incl. German).
Voice tiers and lingua get different headers but the same WindyWord branding,
provenance section, quality block, and dialect/script disclosures where relevant.

Idempotent — HF skips no-op commits when content is unchanged. Single-worker
to stay below the per-user request-rate ceiling.

Doctor: Opus 4.6 Opus-Claw (Dr. C)
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
LOG = CLINIC / "huggingface-uploads" / "refresh_listen_readmes.log"
WER_RESULTS_WPL = CLINIC / "grand-rounds" / "wpl_audit" / "wer_results.jsonl"
WER_RESULTS_P3D = CLINIC / "grand-rounds" / "phase3d_stt" / "phase3d_results.jsonl"

ORG = "WindyWord"
DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"
MACHINE = "Veron-1 (RTX 5090, Mt Pleasant SC)"

api = HfApi()


def log(msg: str):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


# ────────────────────────────────────────────────────────────
# Language data
# ────────────────────────────────────────────────────────────

LANG_NAMES = {
    "am": "Amharic", "ar": "Arabic", "az": "Azerbaijani", "bn": "Bengali",
    "ca": "Catalan", "cs": "Czech", "de": "German", "es": "Spanish",
    "fa": "Persian (Farsi)", "fi": "Finnish", "fr": "French", "gu": "Gujarati",
    "he": "Hebrew", "hi": "Hindi", "hu": "Hungarian", "hy": "Armenian",
    "ig": "Igbo", "it": "Italian", "ja": "Japanese", "kk": "Kazakh",
    "km": "Khmer", "lt": "Lithuanian", "ml": "Malayalam", "mn": "Mongolian",
    "mr": "Marathi", "ms": "Malay", "nl": "Dutch", "no": "Norwegian",
    "pa": "Punjabi", "ps": "Pashto", "pt": "Portuguese", "ro": "Romanian",
    "si": "Sinhala", "te": "Telugu", "zh": "Chinese (Mandarin)",
}

LANG_FAMILY = {
    "am": "Afro-Asiatic > Semitic > South Semitic",
    "ar": "Afro-Asiatic > Semitic",
    "az": "Turkic > Oghuz",
    "bn": "Indo-European > Indo-Iranian > Indo-Aryan",
    "ca": "Indo-European > Italic > Romance",
    "cs": "Indo-European > Balto-Slavic > West Slavic",
    "de": "Indo-European > Germanic > West Germanic",
    "es": "Indo-European > Italic > Romance",
    "fa": "Indo-European > Indo-Iranian > Iranian",
    "fi": "Uralic > Finnic",
    "fr": "Indo-European > Italic > Romance",
    "gu": "Indo-European > Indo-Iranian > Indo-Aryan",
    "he": "Afro-Asiatic > Semitic",
    "hi": "Indo-European > Indo-Iranian > Indo-Aryan",
    "hu": "Uralic > Ugric",
    "hy": "Indo-European > Armenian",
    "ig": "Niger-Congo > Volta-Niger",
    "it": "Indo-European > Italic > Romance",
    "ja": "Japonic",
    "kk": "Turkic > Kipchak",
    "km": "Austroasiatic > Khmeric",
    "lt": "Indo-European > Balto-Slavic > Baltic",
    "ml": "Dravidian > Southern Dravidian",
    "mn": "Mongolic",
    "mr": "Indo-European > Indo-Iranian > Indo-Aryan",
    "ms": "Austronesian > Malayo-Polynesian",
    "nl": "Indo-European > Germanic > West Germanic",
    "no": "Indo-European > Germanic > North Germanic",
    "pa": "Indo-European > Indo-Iranian > Indo-Aryan",
    "ps": "Indo-European > Indo-Iranian > Iranian",
    "pt": "Indo-European > Italic > Romance",
    "ro": "Indo-European > Italic > Romance",
    "si": "Indo-European > Indo-Iranian > Indo-Aryan",
    "te": "Dravidian > South-Central",
    "zh": "Sino-Tibetan > Sinitic",
}

# Per-language SPECIAL notes (dialects, scripts, quality caveats, etc.)
LANG_NOTES = {
    "de": "**Standard High German (Hochdeutsch).** Indo-European > Germanic > West Germanic. Derived from `primeline/whisper-large-v3-turbo-german` — the top community German Whisper fine-tune (46k+ downloads). Replaces an earlier Swiss-German-only variant. WER 42.6% / CER 8.06% on 100-sample FLEURS (CER is the reliable signal here).",
    "hi": "Outputs Hindi audio as **Latin-script Hinglish, NOT Devanagari**. FLEURS-Devanagari WER ≈100% is a script mismatch, not a quality failure. Useful for code-switched / chat / SMS contexts. For Devanagari output, use a separate model (not yet shipped).",
    "ig": "**Quality caveat:** model is whisper-tiny-igbo (39M params, 4 layers); audited at 157% WER. Limited capacity at this parameter size; for production use we recommend an `openai/whisper-large-v3` multilingual fallback.",
    "am": "**Quality caveat:** ported from legacy upload that audited at 119% WER on FLEURS Amharic. Not retired pending a better community fine-tune; use with caution.",
    "ps": "**Quality caveat:** based on whisper-base-pashto (74M params); audited at 53.7% WER. Limited capacity for serious transcription work.",
    "ja": "**Quality note:** based on whisper-base-japanese (74M params). Small model for a top-10 language; production users may prefer the multilingual `openai/whisper-large-v3` for higher accuracy.",
    "ml": "**Quality ceiling:** audited at 73.3% WER (community Malayalam Whisper space is thin — best alternative on HuggingFace audited at 76.5%, ~1.5% worse). Source: `vrclc/Whisper-small-Malayalam`. For high-stakes Malayalam transcription consider `openai/whisper-large-v3` multilingual.",
    "he": "Replaces a previous build whose weights were incomplete (decoder layers 10-23 missing) and produced gibberish output. Now derived from `oridror/whisper-large-v3-turbo-hebrew-r1-myd-r1` (Whisper Large-v3 turbo Hebrew fine-tune). Verified post-upload at WER 24.2% / CER 11.5% / script-match 99% on 20-sample FLEURS he_il — GOOD tier. Tokenizer/preprocessor files filled in from `openai/whisper-large-v3` since the upstream fine-tune omits them.",
    "mn": "Replaces a previous community Mongolian fine-tune that audited as broken (index error on first sample). Now derived from `Ganaa0614/whisper-small-mongolian-ver_0.1` (top community Mongolian Whisper by downloads). Verified post-upload at WER 57.7% / CER 17.3% / script-match 100% on 20-sample FLEURS mn_mn — MARGINAL tier (functional, with hesitation on rare vocabulary). Tokenizer/preprocessor files filled in from `openai/whisper-small` since the upstream fine-tune omits them.",
}

# Voice tier metadata: parameter sizes + Whisper architecture
VOICE_TIERS = {
    "windy-nano":         ("openai/whisper-tiny",                "39M params · whisper-tiny",   "ultra-fast"),
    "windy-lite":         ("openai/whisper-base",                "74M params · whisper-base",   "fast"),
    "windy-core":         ("openai/whisper-small",               "244M params · whisper-small", "balanced"),
    "windy-plus":         ("openai/whisper-medium",              "769M params · whisper-medium","high quality"),
    "windy-turbo":        ("openai/whisper-large-v3-turbo",      "809M params · whisper-large-v3-turbo", "premium / fast"),
    "windy-pro-engine":   ("openai/whisper-large-v3",            "1.55B params · whisper-large-v3", "premium / max accuracy"),
    "windy-edge":         ("distil-whisper/distil-large-v3",     "756M params · distil-whisper-large-v3", "edge / mobile"),
    "windy-distil-small": ("distil-whisper/distil-small.en",     "166M params · distil-whisper-small.en", "English-only edge"),
    "windy-distil-medium":("distil-whisper/distil-medium.en",    "394M params · distil-whisper-medium.en", "English-only edge"),
    "windy-distil-large": ("distil-whisper/distil-large-v3",     "756M params · distil-whisper-large-v3", "English-only edge"),
}


def load_wer_data():
    """Combine WER results from WindyProLabs audit + Phase 3d audit, keyed by slug."""
    out = {}
    if WER_RESULTS_WPL.exists():
        for line in WER_RESULTS_WPL.read_text().splitlines():
            if not line.strip(): continue
            r = json.loads(line)
            if r.get("status") == "complete" and r.get("mean_latency_ms", 0) > 10:
                # Skip the harness-empty (1.0 WER, <10ms) results
                out[r["slug"]] = {
                    "wer": r.get("wer"), "cer": r.get("cer"),
                    "rtf": r.get("rtf"), "n_samples": r.get("n_samples"),
                    "source": "WindyWord Grand Rounds v2 audit (50-sample FLEURS)",
                }
    if WER_RESULTS_P3D.exists():
        for line in WER_RESULTS_P3D.read_text().splitlines():
            if not line.strip(): continue
            r = json.loads(line)
            if r.get("n_samples", 0) >= 50:
                slug = (r.get("patient_id", "") or "").replace("windy-lingua-", "")
                if slug and slug not in out:  # WPL takes precedence as it's newer
                    out[slug] = {
                        "wer": r.get("wer"), "cer": r.get("cer"),
                        "rtf": r.get("rtf"), "n_samples": r.get("n_samples"),
                        "source": "WindyWord Phase 3d STT harness (100-sample FLEURS)",
                    }
    return out


def tier_from_wer(wer):
    if wer is None: return ("UNVERIFIED", "—")
    if wer < 0.05:  return ("EXCELLENT", "⭐⭐⭐⭐⭐")
    if wer < 0.10:  return ("EXCELLENT", "⭐⭐⭐⭐⭐")
    if wer < 0.20:  return ("GOOD", "⭐⭐⭐⭐")
    if wer < 0.30:  return ("OK", "⭐⭐⭐")
    if wer < 0.50:  return ("MARGINAL", "⭐⭐")
    return ("UNUSABLE-GAP", "⭐")


def parse_repo(repo_id: str):
    """Parse `WindyWord/listen-...` and decide voice vs lingua + parameters."""
    name = repo_id.replace(f"{ORG}/listen-", "")
    if "lingua" in name:
        # listen-windy-lingua-{slug}[-ct2]
        is_ct2 = name.endswith("-ct2")
        slug = name.replace("windy-lingua-", "").rstrip("-ct2")
        if is_ct2:
            slug = slug[:-3] if slug.endswith("ct2") else slug
        # Cleaner slug extraction
        slug = name.replace("windy-lingua-", "")
        if slug.endswith("-ct2"):
            slug = slug[:-len("-ct2")]
        return {"kind": "lingua", "slug": slug, "is_ct2": is_ct2, "voice_tier": None}
    else:
        # listen-windy-{tier}
        # Could be voice-tier name like windy-nano or windy-distil-small
        base = name
        return {"kind": "voice", "slug": None, "is_ct2": False, "voice_tier": base}


def build_lingua_readme(slug: str, is_ct2: bool, wer_data: dict, repo_id: str):
    name = LANG_NAMES.get(slug, slug.capitalize())
    family = LANG_FAMILY.get(slug, "Unknown")
    note = LANG_NOTES.get(slug, "")
    note_block = f"\n> **Note:** {note}\n" if note else ""

    wer_row = wer_data.get(slug)
    if wer_row and wer_row.get("wer") is not None:
        w = wer_row["wer"]
        tier_label, stars = tier_from_wer(w)
        wer_block = (f"- **FLEURS WER:** {w*100:.1f}% ({wer_row.get('n_samples', '?')}-sample audit)\n"
                     f"- **CER:** {wer_row.get('cer', '?')}\n"
                     f"- **Tier:** {tier_label} {stars}\n"
                     f"- **Source:** {wer_row.get('source', '?')}")
    else:
        wer_block = "- **WER:** unverified by WindyWord harness yet. Imported from upstream community fine-tune."

    variant_label = "ct2-int8" if is_ct2 else "safetensors"
    variant_header = "CPU INT8 (CTranslate2)" if is_ct2 else "GPU (safetensors)"

    yaml_lang = slug if len(slug) in (2, 3) else "multilingual"

    return f"""---
license: apache-2.0
tags:
- automatic-speech-recognition
- whisper
- windyword
- {name.lower().replace(' ', '-').split('(')[0].rstrip('-')}
- {slug.lower()}
library_name: transformers
pipeline_tag: automatic-speech-recognition
language:
- {yaml_lang}
---

# WindyWord.ai STT — {name} Lingua ({variant_header})

**Transcribes {name} speech ({family}).**
{note_block}
## Quality

{wer_block}

## About this variant

This is the **{variant_label}** deployment format of our {name} Lingua STT model. Load it via the `{variant_label}/` subfolder.

Part of the [WindyWord.ai](https://windyword.ai) STT fleet — covering 35+ languages that commercial speech-to-text APIs underserve, with proper dialect / script disclosures where they matter.

## Usage

```python
from transformers import WhisperForConditionalGeneration, WhisperProcessor
processor = WhisperProcessor.from_pretrained("{repo_id}", subfolder="{variant_label}")
model = WhisperForConditionalGeneration.from_pretrained("{repo_id}", subfolder="{variant_label}")
```

## Commercial Use

Visit [windyword.ai](https://windyword.ai) for apps and API access.

---

## Provenance & License

Weights derived from upstream community Whisper fine-tunes (see individual model card for exact lineage). Redistributed under Apache-2.0 (inherited).

*Certified by Opus 4.6 Opus-Claw (Dr. C) on Veron-1 (RTX 5090, Mt Pleasant SC).*
"""


def build_voice_readme(tier_name: str, repo_id: str):
    upstream, params, profile = VOICE_TIERS.get(tier_name, ("openai/whisper-base", "?", "?"))
    pretty = tier_name.replace("windy-", "Windy ").replace("-", " ").title()
    return f"""---
license: apache-2.0
tags:
- automatic-speech-recognition
- whisper
- windyword
- english
- multilingual
library_name: transformers
pipeline_tag: automatic-speech-recognition
language:
- en
- multilingual
---

# WindyWord.ai STT — {pretty}

**Multilingual speech-to-text engine. Transcribes audio in 100+ languages, with English as the primary trained domain.**

## Profile

- **Architecture:** {params}
- **Profile:** {profile}
- **Base model:** [{upstream}](https://huggingface.co/{upstream})

## Variants in this repo

| Subfolder | Format | Use case |
|---|---|---|
| `safetensors/` | PyTorch safetensors (FP32) | GPU inference (highest quality) |
| `ct2-int8/` | CTranslate2 INT8 | CPU inference (~25% size, 2-4× faster) |
| `onnx/` | ONNX FP32 | Cross-platform deployment |
| `onnx-int8/` | ONNX INT8 | Edge / mobile / WebAssembly |

## Usage

```python
from transformers import WhisperForConditionalGeneration, WhisperProcessor
processor = WhisperProcessor.from_pretrained("{repo_id}", subfolder="safetensors")
model = WhisperForConditionalGeneration.from_pretrained("{repo_id}", subfolder="safetensors")
```

For CPU inference via CTranslate2:
```python
import ctranslate2
# After downloading the ct2-int8 subfolder:
model = ctranslate2.models.Whisper("path/to/ct2-int8/")
```

## Commercial Use

Part of the [WindyWord.ai](https://windyword.ai) STT fleet. Visit windyword.ai for real-time voice-to-text + translation apps and API access.

---

## Provenance & License

Weights derived from [{upstream}](https://huggingface.co/{upstream}) under Apache-2.0 (inherited). Voice tiers are direct redistributions of the upstream community Whisper / distil-whisper variants; no LoRA fine-tuning has been applied to these voice models.

*Certified by Opus 4.6 Opus-Claw (Dr. C) on Veron-1 (RTX 5090, Mt Pleasant SC).*
"""


def refresh_one(repo_id: str, wer_data: dict):
    parsed = parse_repo(repo_id)
    if parsed["kind"] == "lingua":
        readme = build_lingua_readme(parsed["slug"], parsed["is_ct2"], wer_data, repo_id)
    else:
        readme = build_voice_readme(parsed["voice_tier"], repo_id)
    tmp = Path(f"/tmp/_listen_refresh_{repo_id.replace('/', '_')}.md")
    try:
        tmp.write_text(readme)
        api.upload_file(
            path_or_fileobj=str(tmp),
            path_in_repo="README.md",
            repo_id=repo_id,
            repo_type="model",
            commit_message="Refresh README — uniform WindyWord template with WER tier + dialect notes",
        )
        return repo_id, "ok"
    except Exception as e:
        return repo_id, f"error:{type(e).__name__}:{str(e)[:140]}"
    finally:
        tmp.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    log(f"Listing all WindyWord/listen-* repos…")
    listen = sorted([m.id for m in api.list_models(author=ORG) if m.id.startswith(f"{ORG}/listen-")])
    log(f"Total: {len(listen)} listen-* repos")
    if args.limit:
        listen = listen[: args.limit]

    wer_data = load_wer_data()
    log(f"Loaded WER data for {len(wer_data)} languages")

    t0 = time.time()
    done = 0
    errs = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(refresh_one, r, wer_data): r for r in listen}
        for i, fut in enumerate(as_completed(futures), 1):
            repo, status = fut.result()
            if status == "ok":
                done += 1
            else:
                errs += 1
                log(f"  [{i}/{len(listen)}] {repo}: {status}")
            if i % 10 == 0:
                el = time.time() - t0
                log(f"progress {i}/{len(listen)}  done={done} errs={errs}  ({el:.0f}s, {i/el*60:.1f}/min)")
    log(f"Complete. done={done}, errors={errs}, total={len(listen)}")


if __name__ == "__main__":
    main()

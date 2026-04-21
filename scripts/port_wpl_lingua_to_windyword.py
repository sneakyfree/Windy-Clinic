#!/usr/bin/env python3
"""Port WindyProLabs windy-lingua-* models to WindyWord/listen-windy-lingua-*.

Uses both tokens (Veron1 for WPL read, WindyWordGodAPI1 for WW write — there
is no single cross-org token). Download via Veron1 → upload to WW via the
default token; architecture mirrors WindyWord Phase-3 convention:
  parent GPU model   → WindyWord/listen-windy-lingua-{lang}/safetensors/
  parent CT2 variant → WindyWord/listen-windy-lingua-{lang}-ct2/ct2-int8/

Each port writes a WindyWord-branded README including:
  - spelled-out language name + family
  - WER tier (EXCELLENT/GOOD/OK/MARGINAL/UNUSABLE/UNVERIFIED)
  - upstream base model attribution
  - dialect caveats where relevant

Also signs a per-language STT patient file in the clinic.

Doctor: Opus 4.6 Opus-Claw (Dr. C)  2026-04-21
"""
import argparse
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import HfApi, create_repo, snapshot_download
from huggingface_hub.errors import HfHubHTTPError

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
LOG = CLINIC / "huggingface-uploads" / "port_wpl_lingua.log"
CHECKPOINT = CLINIC / "huggingface-uploads" / "port_wpl_lingua.checkpoint.json"
STT_PATIENTS = CLINIC / "stt-models"
WER_RESULTS = CLINIC / "grand-rounds" / "wpl_audit" / "wer_results.jsonl"

DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"
MACHINE = "Veron-1 (RTX 5090, Mt Pleasant SC)"

# Load both tokens
_lockbox = Path("/tmp/lockbox.md").read_text()
VERON1 = re.search(r"\*\*HuggingFaceVeron1\*\*.*?\*\*Token:\*\*\s*`(hf_[A-Za-z0-9]+)`", _lockbox, re.DOTALL).group(1)
WW_TOKEN = Path("/home/user1-gpu/.cache/huggingface/token").read_text().strip()

# Language name map (copied subset from upload_to_huggingface.py for script independence)
LANG_NAMES = {
    "am": "Amharic", "arabic": "Arabic", "az": "Azerbaijani", "bn": "Bengali",
    "ca": "Catalan", "chinese": "Chinese (Mandarin)", "cs": "Czech", "de": "German",
    "fa": "Persian (Farsi)", "fi": "Finnish", "french": "French", "gu": "Gujarati",
    "he": "Hebrew", "hindi": "Hindi", "hu": "Hungarian", "hy": "Armenian",
    "ig": "Igbo", "it": "Italian", "ja": "Japanese", "kk": "Kazakh",
    "km": "Khmer", "lt": "Lithuanian", "ml": "Malayalam", "mn": "Mongolian",
    "mr": "Marathi", "ms": "Malay", "nl": "Dutch", "no": "Norwegian",
    "pa": "Punjabi", "ps": "Pashto", "pt": "Portuguese", "ro": "Romanian",
    "si": "Sinhala", "spanish": "Spanish", "te": "Telugu",
}

LANG_NOTES = {
    "de": "This variant's base model is Swiss German, which audits poorly against standard (High) German (WER 56.7% vs de_de FLEURS). Use only for Swiss German content.",
    "hindi": "Outputs Hindi audio as Latin-script Hinglish, not Devanagari. FLEURS-Devanagari WER ≈100% is a script mismatch, not a quality failure. Useful for code-switched / chat contexts.",
    "am": "Quality note: model scored 118% WER on FLEURS Amharic. Use with caution; may output garbage on production audio.",
    "ig": "Quality note: model is whisper-tiny-igbo (39M params, 4 layers). Scored 157% WER. Limited capacity; recommend fallback.",
}

# Family codes for context
LANG_FAMILY = {
    "am": "Afro-Asiatic > Semitic > South Semitic",
    "arabic": "Afro-Asiatic > Semitic",
    "az": "Turkic > Oghuz",
    "bn": "Indo-European > Indo-Iranian > Indo-Aryan",
    "ca": "Indo-European > Italic > Romance",
    "chinese": "Sino-Tibetan > Sinitic",
    "cs": "Indo-European > Balto-Slavic > West Slavic",
    "de": "Indo-European > Germanic > West Germanic",
    "fa": "Indo-European > Indo-Iranian > Iranian",
    "fi": "Uralic > Finnic",
    "french": "Indo-European > Italic > Romance",
    "gu": "Indo-European > Indo-Iranian > Indo-Aryan",
    "he": "Afro-Asiatic > Semitic",
    "hindi": "Indo-European > Indo-Iranian > Indo-Aryan",
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
    "spanish": "Indo-European > Italic > Romance",
    "te": "Dravidian > South-Central",
}


def log(msg: str):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def load_ckpt():
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {"done": [], "errors": []}


def save_ckpt(s):
    CHECKPOINT.write_text(json.dumps(s, indent=2))


def get_wer_row(slug: str):
    """Return the WER audit row for this slug, or None."""
    if not WER_RESULTS.exists():
        return None
    with open(WER_RESULTS) as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("slug") == slug:
                return r
    return None


def build_readme(slug: str, is_ct2: bool, upstream_base: str, wer_row: dict):
    name = LANG_NAMES.get(slug, slug.capitalize())
    family = LANG_FAMILY.get(slug, "Unknown")
    note = LANG_NOTES.get(slug, "")

    # Quality tier from WER
    if wer_row and wer_row.get("status") == "complete" and wer_row.get("wer") is not None:
        w = wer_row["wer"]
        if w < 0.10:     tier = ("EXCELLENT (⭐⭐⭐⭐⭐)", "premium")
        elif w < 0.20:   tier = ("GOOD (⭐⭐⭐⭐)", "standard")
        elif w < 0.30:   tier = ("OK (⭐⭐⭐)", "basic")
        elif w < 0.50:   tier = ("MARGINAL (⭐⭐)", "marginal")
        else:            tier = ("UNUSABLE (⭐)", "unusable")
        wer_block = f"- **FLEURS dev WER**: {w*100:.1f}% (50-sample audit, WindyWord Grand Rounds v2 methodology)\n- **CER**: {wer_row.get('cer', '?')}\n- **Tier**: {tier[0]}"
    else:
        tier = ("UNVERIFIED", "unverified")
        wer_block = "- **FLEURS WER**: not yet verified via our harness. Model imported from legacy WindyProLabs upload (2026-03-10)."

    note_block = f"\n> **Note:** {note}\n" if note else ""
    variant_label = "ct2-int8" if is_ct2 else "safetensors"
    variant_header = "CPU INT8 (CTranslate2)" if is_ct2 else "GPU (safetensors)"
    repo_name = f"WindyWord/listen-windy-lingua-{slug}-ct2" if is_ct2 else f"WindyWord/listen-windy-lingua-{slug}"

    yaml_lang = slug if len(slug) == 2 else {"arabic": "ar", "chinese": "zh", "french": "fr", "hindi": "hi", "spanish": "es"}.get(slug, "multilingual")

    return f"""---
license: apache-2.0
tags:
- automatic-speech-recognition
- whisper
- windyword
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

This is the **{variant_label}** deployment format of our {name} Lingua STT model. Load it via the `{variant_label}/` subfolder of this repo.

Part of the [WindyWord.ai](https://windyword.ai) STT fleet — covering 35+ underserved languages that commercial speech-to-text APIs don't.

## Base model

Derived from [{upstream_base}](https://huggingface.co/{upstream_base}) (upstream Whisper fine-tune).

## Commercial Use

Visit [windyword.ai](https://windyword.ai) for apps and API access. WindyWord.ai specializes in real-time voice-to-text and translation for languages commercial APIs underserve.

---

## Provenance & License

Weights derived from the upstream Whisper fine-tune cited above. Redistributed under Apache-2.0 (inherited). Ported 2026-04-21 from legacy `WindyProLabs/windy-lingua-{slug}{'-ct2' if is_ct2 else ''}` (Dr. A era, 2026-03-10) into the canonical `WindyWord/` org after Grand Rounds v2 WER audit.

*Certified by Opus 4.6 Opus-Claw (Dr. C) on Veron-1 (RTX 5090, Mt Pleasant SC).*
"""


def port_one(slug: str, is_ct2: bool, ckpt):
    variant_suffix = "-ct2" if is_ct2 else ""
    src = f"WindyProLabs/windy-lingua-{slug}{variant_suffix}"
    dst = f"WindyWord/listen-windy-lingua-{slug}{variant_suffix}"
    key = dst

    if key in ckpt["done"]:
        log(f"SKIP (already ported): {key}")
        return "skip"

    api_wpl = HfApi(token=VERON1)
    api_ww = HfApi(token=WW_TOKEN)

    # 1. Verify source exists
    try:
        src_info = api_wpl.model_info(src)
    except HfHubHTTPError as e:
        log(f"  SRC MISSING {src}: {str(e)[:100]}")
        ckpt["errors"].append({"repo": key, "reason": f"src missing: {str(e)[:100]}"})
        save_ckpt(ckpt)
        return "src_missing"

    # 2. Try to read upstream base from config.json (only for non-ct2)
    upstream_base = "unknown (CTranslate2 format, no config metadata)" if is_ct2 else "unknown"
    if not is_ct2:
        try:
            from huggingface_hub import hf_hub_download
            p = hf_hub_download(src, "config.json", token=VERON1)
            cfg = json.loads(open(p).read())
            upstream_base = cfg.get("_name_or_path", "unknown")
        except Exception:
            pass

    # 3. Download source
    log(f"  downloading {src} via Veron1…")
    try:
        local = snapshot_download(src, token=VERON1)
    except Exception as e:
        log(f"  DOWNLOAD ERR {src}: {str(e)[:140]}")
        ckpt["errors"].append({"repo": key, "reason": f"download: {str(e)[:140]}"})
        save_ckpt(ckpt)
        return "download_err"

    # 4. Create destination (public)
    log(f"  creating {dst}…")
    try:
        create_repo(repo_id=dst, repo_type="model", private=False, exist_ok=True, token=WW_TOKEN)
    except Exception as e:
        log(f"  CREATE ERR {dst}: {str(e)[:140]}")
        ckpt["errors"].append({"repo": key, "reason": f"create: {str(e)[:140]}"})
        save_ckpt(ckpt)
        return "create_err"

    # 5. Upload model files to subfolder
    subfolder = "ct2-int8" if is_ct2 else "safetensors"
    log(f"  uploading files to {dst}/{subfolder}…")
    try:
        api_ww.upload_folder(
            folder_path=local,
            path_in_repo=subfolder,
            repo_id=dst,
            repo_type="model",
            commit_message=f"Port from WindyProLabs/windy-lingua-{slug}{variant_suffix} (2026-03-10)",
            token=WW_TOKEN,
            ignore_patterns=["*.md", ".gitattributes"],
        )
    except Exception as e:
        log(f"  UPLOAD ERR {dst}: {str(e)[:200]}")
        ckpt["errors"].append({"repo": key, "reason": f"upload: {str(e)[:200]}"})
        save_ckpt(ckpt)
        return "upload_err"

    # 6. Write README
    wer_row = get_wer_row(slug)
    readme = build_readme(slug, is_ct2, upstream_base, wer_row)
    tmp = Path(f"/tmp/_readme_port_{slug}{variant_suffix}.md")
    tmp.write_text(readme)
    try:
        api_ww.upload_file(
            path_or_fileobj=str(tmp),
            path_in_repo="README.md",
            repo_id=dst,
            repo_type="model",
            commit_message="Add WindyWord model card",
            token=WW_TOKEN,
        )
    except Exception as e:
        log(f"  README ERR {dst}: {str(e)[:140]}")
    tmp.unlink(missing_ok=True)

    ckpt["done"].append(key)
    save_ckpt(ckpt)
    log(f"  ✓ ported {src} → {dst}")
    return "ok"


def sign_patient_file(slug: str, ported_parents: list, ported_ct2s: list):
    """Create/update STT patient file for a Lingua language we just ported."""
    name = LANG_NAMES.get(slug, slug.capitalize())
    pf = STT_PATIENTS / f"windy-lingua-{slug}.json"
    now = datetime.now(timezone.utc).isoformat()
    wer_row = get_wer_row(slug)

    existing = {}
    if pf.exists():
        existing = json.loads(pf.read_text())

    chart = {
        "_schema": "windstorm_clinic_stt_v1",
        "_last_updated": now,
        "_clinic_path": f"stt-models/windy-lingua-{slug}.json",
        "patient_id": f"windy-lingua-{slug}",
        "kind": "stt_lingua",
        "name": f"Windy Lingua {name}",
        "admitted": existing.get("admitted", now),
        "admitted_by": DOCTOR,
        "language": slug,
        "language_name": name,
        "source_repo_origin": f"WindyProLabs/windy-lingua-{slug}",
        "hf_repos_windyword": [],
        "variant_cluster": {},
        "examination_log": existing.get("examination_log", []),
    }

    if slug in ported_parents:
        chart["hf_repos_windyword"].append(f"WindyWord/listen-windy-lingua-{slug}")
        chart["variant_cluster"]["safetensors"] = {
            "status": "present",
            "hf_repo": f"WindyWord/listen-windy-lingua-{slug}",
            "subfolder": "safetensors",
            "format": "safetensors",
            "ported_at": now,
        }
    if slug in ported_ct2s:
        chart["hf_repos_windyword"].append(f"WindyWord/listen-windy-lingua-{slug}-ct2")
        chart["variant_cluster"]["ct2-int8"] = {
            "status": "present",
            "hf_repo": f"WindyWord/listen-windy-lingua-{slug}-ct2",
            "subfolder": "ct2-int8",
            "format": "ctranslate2_int8",
            "ported_at": now,
        }

    exam_id = f"DRC-PORT-LINGUA-{slug}"
    log_entries = chart["examination_log"]
    if not any(e.get("exam_id") == exam_id for e in log_entries):
        wer_block = None
        if wer_row and wer_row.get("status") == "complete":
            wer_block = {
                "wer": wer_row.get("wer"),
                "cer": wer_row.get("cer"),
                "rtf": wer_row.get("rtf"),
                "mean_latency_ms": wer_row.get("mean_latency_ms"),
                "n_samples": wer_row.get("n_samples"),
                "fleurs_subset": wer_row.get("fleurs_subset"),
            }
        log_entries.append({
            "exam_id": exam_id,
            "date": now,
            "doctor": DOCTOR,
            "machine": MACHINE,
            "method": "Cross-org port WindyProLabs → WindyWord with signed WER audit metadata",
            "ported_variants": list(chart["variant_cluster"].keys()),
            "wer_audit_result": wer_block,
            "upstream_note": f"Model originally uploaded to WindyProLabs on 2026-03-10 by Dr. A / Kit OC1 Alpha. Underlying base is a community Whisper fine-tune (see individual HF model card for lineage).",
            "notes": f"Filed by {DOCTOR}.",
        })
    pf.write_text(json.dumps(chart, indent=2, ensure_ascii=False))


# ────────────────────────────────────────────────────────────────
# PORT PLAN
# ────────────────────────────────────────────────────────────────
# Based on /tmp/wpl_port_plan.json + human override for "everything not unusable"
PORT_PARENTS = [
    # Tier 1 OK-confirmed
    "it", "pt", "fa", "nl", "ca", "ms",
    # Tier 3 marginal
    "fi", "no", "cs", "hy", "az",
    # Tier 2 harness-unclear (likely fine in production)
    "bn", "gu", "hu", "kk", "km", "mr", "pa", "ro", "te",
    # Uncertain / error — port with disclosure
    "si", "ja",
]

# CT2 sidekicks we also want (and which WPL actually has)
PORT_CT2 = [
    "ca", "fa", "it", "ms", "nl",  # OK-tier parents
    "az",                           # marginal
    "ja",                           # error
]

# Orphan CT2 (no GPU parent): lt-ct2 only, no lt.  Ship as standalone -ct2 repo.
PORT_CT2_ORPHAN = ["lt"]  # will ship as WindyWord/listen-windy-lingua-lt-ct2 without a GPU sibling


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="Port only these slugs")
    ap.add_argument("--ct2-only", action="store_true")
    ap.add_argument("--skip-parents", action="store_true")
    args = ap.parse_args()

    ckpt = load_ckpt()
    log(f"Port run — {len(ckpt['done'])} already done")

    ported_parents = set()
    ported_ct2s = set()

    # Phase 1: parent GPU models
    if not args.ct2_only:
        parents = PORT_PARENTS if not args.only else [s for s in PORT_PARENTS if s in args.only]
        for i, slug in enumerate(parents, 1):
            log(f"[parent {i}/{len(parents)}] {slug}")
            r = port_one(slug, is_ct2=False, ckpt=ckpt)
            if r == "ok" or r == "skip":
                ported_parents.add(slug)

    # Phase 2: CT2 sidekicks
    if not args.skip_parents:
        ct2s = PORT_CT2 if not args.only else [s for s in PORT_CT2 if s in args.only]
        for i, slug in enumerate(ct2s, 1):
            log(f"[ct2 {i}/{len(ct2s)}] {slug}-ct2")
            r = port_one(slug, is_ct2=True, ckpt=ckpt)
            if r == "ok" or r == "skip":
                ported_ct2s.add(slug)

        # Phase 3: CT2 orphans
        for slug in (args.only or PORT_CT2_ORPHAN):
            if slug not in PORT_CT2_ORPHAN:
                continue
            log(f"[orphan ct2] {slug}-ct2")
            r = port_one(slug, is_ct2=True, ckpt=ckpt)
            if r == "ok" or r == "skip":
                ported_ct2s.add(slug)

    # Sign clinic patient files for every language we touched
    all_languages = ported_parents | ported_ct2s
    log(f"\n=== Signing {len(all_languages)} patient files ===")
    for slug in sorted(all_languages):
        sign_patient_file(slug, ported_parents, ported_ct2s)

    log(f"\n=== SUMMARY ===")
    log(f"Parents ported: {len(ported_parents)}  ({sorted(ported_parents)})")
    log(f"CT2s ported:    {len(ported_ct2s)}  ({sorted(ported_ct2s)})")
    log(f"Errors:         {len(ckpt['errors'])}")


if __name__ == "__main__":
    main()

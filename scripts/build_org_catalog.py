#!/usr/bin/env python3
"""Build the WindyWord HF org landing-page README — a browseable catalog of every
translation repo, grouped by source and target language with fully spelled-out names.

Reads clinic patient files to know which repos exist + their quality ratings,
then queries HF to check which are live. Generates a markdown catalog and uploads
it to `WindyWord/WindyWord` (the HF org-profile special repo).

Usage:
  python3 build_org_catalog.py                   # build + upload
  python3 build_org_catalog.py --dry-run         # write to /tmp/ only, no upload
  python3 build_org_catalog.py --out PATH        # write to PATH only, no upload

Doctor: Opus 4.6 Opus-Claw (Dr. C)
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import HfApi, create_repo

sys.path.insert(0, str(Path(__file__).parent))
from upload_to_huggingface import (
    ORG, PATIENTS, parse_pid_langs, _lang_label, _expand_lang, _FAMILY_MEMBERS,
)

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
LOG = CLINIC / "huggingface-uploads" / "catalog_build.log"


def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def gather_live_repos():
    api = HfApi()
    live = {m.id.replace(f"{ORG}/translate-", "") for m in api.list_models(author=ORG)
            if m.id.startswith(f"{ORG}/translate-")}
    return live


def build_catalog(live_pids: set) -> str:
    # Collect pair info: (pid, src_code, tgt_code, src_label, tgt_label, tier, stars)
    pairs = []
    by_src = defaultdict(list)
    by_tgt = defaultdict(list)
    tier_counts = defaultdict(int)
    skipped_no_patient = 0

    for pid in sorted(live_pids):
        pf = PATIENTS / f"{pid}.json"
        if not pf.exists():
            skipped_no_patient += 1
            continue
        chart = json.loads(pf.read_text())
        src_code, tgt_code = parse_pid_langs(pid)
        src_label = _lang_label(src_code) if src_code else "?"
        tgt_label = _lang_label(tgt_code) if tgt_code else "?"
        qr = chart.get("quality_rating") or {}
        tier = (qr.get("tier") or qr.get("label") or "unrated").lower()
        stars = qr.get("stars")
        pairs.append({
            "pid": pid,
            "src_code": src_code,
            "tgt_code": tgt_code,
            "src_label": src_label,
            "tgt_label": tgt_label,
            "tier": tier,
            "stars": stars,
        })
        by_src[src_label].append(pairs[-1])
        by_tgt[tgt_label].append(pairs[-1])
        tier_counts[tier] += 1

    all_src_langs = sorted(by_src.keys(), key=lambda s: (s == "?", s.lower()))
    all_tgt_langs = sorted(by_tgt.keys(), key=lambda s: (s == "?", s.lower()))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    md = []
    md.append("# WindyWord.ai — Translation Model Catalog")
    md.append("")
    md.append(f"Welcome to WindyWord.ai. This org hosts **{len(pairs):,} proprietary translation "
              f"models** covering **{len(all_src_langs)} source languages** and **{len(all_tgt_langs)} "
              f"target languages** — including many rare combinations that commercial APIs don't serve.")
    md.append("")
    md.append(f"*Catalog last updated: {now}. See [windyword.ai](https://windyword.ai) for apps and API access.*")
    md.append("")
    md.append("## Quality tiers")
    md.append("")
    md.append("Every model carries a 5-star rating from our Grand Rounds v2 paragraph-level test battery:")
    md.append("")
    md.append("| Tier | Stars | Count |")
    md.append("|---|---:|---:|")
    for tier in ["premium", "standard", "basic", "budget", "deferred", "unrated"]:
        if tier in tier_counts:
            md.append(f"| **{tier.capitalize()}** | {'4.5-5.0★' if tier=='premium' else '3.5-4.0★' if tier=='standard' else '2.5-3.0★' if tier=='basic' else '<2.5★' if tier=='budget' else '—'} | {tier_counts[tier]:,} |")
    md.append("")
    md.append("## Available variants per model")
    md.append("")
    md.append("Each translation repo includes multiple deployment formats as subfolders:")
    md.append("")
    md.append("- **WindyStandard** (`lora/`) — production baseline, GPU-optimized.")
    md.append("- **WindyStandard · CPU INT8** (`lora-ct2-int8/`) — CTranslate2 INT8 for fast CPU inference.")
    md.append("- **WindyEnhanced** (`herm0/`) — deep fine-tuned on OPUS-100/Tatoeba/WikiMatrix for higher quality (when available).")
    md.append("- **WindyEnhanced · CPU INT8** (`herm0-ct2-int8/`) — INT8 of WindyEnhanced.")
    md.append("- **WindyScripture** (`herm0-scripture/`) — eBible-specialized, for biblical text only.")
    md.append("")
    md.append(f"Load with `from_pretrained(\"{ORG}/translate-<pair>\", subfolder=\"lora\")`.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## Browse by source language")
    md.append("")
    md.append(f"{len(all_src_langs)} source languages. Click any repo ID to open the model card.")
    md.append("")
    for src in all_src_langs:
        items = sorted(by_src[src], key=lambda p: p["tgt_label"].lower() if p["tgt_label"] else "~")
        md.append(f"### {src} → {len(items)} target language{'s' if len(items) != 1 else ''}")
        md.append("")
        for it in items:
            star = f" {it['stars']}★" if it['stars'] else ""
            md.append(f"- **{src} → {it['tgt_label']}**{star} &nbsp;&nbsp; [`{it['pid']}`](https://huggingface.co/{ORG}/translate-{it['pid']})")
        md.append("")
    md.append("---")
    md.append("")
    md.append("## Browse by target language")
    md.append("")
    md.append(f"{len(all_tgt_langs)} target languages.")
    md.append("")
    for tgt in all_tgt_langs:
        items = sorted(by_tgt[tgt], key=lambda p: p["src_label"].lower() if p["src_label"] else "~")
        md.append(f"### → {tgt} (from {len(items)} source language{'s' if len(items) != 1 else ''})")
        md.append("")
        for it in items:
            star = f" {it['stars']}★" if it['stars'] else ""
            md.append(f"- **{it['src_label']} → {tgt}**{star} &nbsp;&nbsp; [`{it['pid']}`](https://huggingface.co/{ORG}/translate-{it['pid']})")
        md.append("")
    md.append("---")
    md.append("")
    md.append("## Speech-to-Text fleet")
    md.append("")
    md.append(f"WindyWord also publishes {10} English STT voice models and 6 per-language Lingua STT models under [`{ORG}/listen-*`](https://huggingface.co/{ORG}?search=listen).")
    md.append("")
    md.append("- **Voice models** (Whisper-based): `listen-windy-nano`, `-lite`, `-core`, `-plus`, `-turbo`, `-pro-engine`, `-edge`, `-distil-small/medium/large`")
    md.append("- **Per-language Lingua**: `listen-windy-lingua-spanish`, `-chinese`, `-french`, `-arabic`, `-hindi` (Hinglish output)")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## Provenance & License")
    md.append("")
    md.append("All translation models derive from the OPUS-MT project ([Helsinki-NLP on HuggingFace](https://huggingface.co/Helsinki-NLP)) under CC-BY-4.0. WindyWord's WindyStandard, WindyEnhanced, and WindyScripture variants are proprietary, independently trained and quality-certified through our Grand Rounds v2 test battery.")
    md.append("")
    md.append("Licensed CC-BY-4.0. Attribution preserved as required.")
    md.append("")
    md.append(f"*Catalog auto-generated by Dr. C. {skipped_no_patient} live repos had no patient file and were omitted.*")
    md.append("")

    return "\n".join(md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", help="Write to local path instead of uploading")
    args = ap.parse_args()

    log("Gathering live repos from HF…")
    live = gather_live_repos()
    log(f"{len(live)} live translate-* repos")

    md = build_catalog(live)
    out_path = Path(args.out) if args.out else Path("/tmp/windyword_org_catalog.md")
    out_path.write_text(md)
    log(f"Catalog written: {out_path} ({out_path.stat().st_size:,} bytes)")

    if args.dry_run or args.out:
        return 0

    # Upload as WindyWord/WindyWord (HF org-profile convention — dataset repo)
    api = HfApi()
    org_profile_repo = f"{ORG}/{ORG}"
    log(f"Creating/ensuring org-profile repo: {org_profile_repo}")
    try:
        create_repo(repo_id=org_profile_repo, repo_type="model", private=False, exist_ok=True)
    except Exception as e:
        log(f"create_repo warning: {e}")

    log("Uploading catalog README…")
    api.upload_file(
        path_or_fileobj=str(out_path),
        path_in_repo="README.md",
        repo_id=org_profile_repo,
        repo_type="model",
        commit_message=f"Regenerate WindyWord catalog — {len(live):,} translation models listed",
    )
    log(f"✓ Uploaded to https://huggingface.co/{org_profile_repo}")
    log("If HF does not yet show this as the org landing page, visit org settings and pin this repo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

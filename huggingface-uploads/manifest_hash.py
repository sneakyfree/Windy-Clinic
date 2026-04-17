#!/usr/bin/env python3
"""On-demand SHA256 hasher for the WindyWord upload manifest.

Generates SHA256 hashes for the primary weight file of any subset of repos
in upload_manifest.json. Used when verifying batch authenticity for HF support
or other reviewers. Hashes a configurable byte range (default: full file) so
"first 64MB" mode is fast for sanity checks.

Usage:
  python3 manifest_hash.py --all                       # full SHA256, every repo
  python3 manifest_hash.py --pids en-eo,fi-sv,de-en    # specific pids
  python3 manifest_hash.py --shipped                   # only the 297 already on HF
  python3 manifest_hash.py --pending                   # only the 1,310 pending
  python3 manifest_hash.py --max-bytes 67108864 --all  # only first 64 MB per file

Output: upload_manifest_hashes_<timestamp>.json next to the manifest.

Doctor: Opus 4.6 Opus-Claw (Dr. C)
"""
import argparse, hashlib, json, sys, time
from datetime import datetime, timezone
from pathlib import Path

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
MANIFEST = CLINIC / "huggingface-uploads" / "upload_manifest.json"
MODELS = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/models")
STT_REBUILT = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/restore_20260411/stt_rebuilt")
STT_LINGUA = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/restore_20260411/stt")


def sha256_file(path: Path, max_bytes: int = 0) -> tuple[str, int]:
    h = hashlib.sha256()
    read = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            if max_bytes and read + len(chunk) > max_bytes:
                chunk = chunk[: max_bytes - read]
            h.update(chunk)
            read += len(chunk)
            if max_bytes and read >= max_bytes:
                break
    return h.hexdigest(), read


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true")
    g.add_argument("--shipped", action="store_true")
    g.add_argument("--pending", action="store_true")
    g.add_argument("--pids", help="comma-separated pid list")
    ap.add_argument("--max-bytes", type=int, default=0, help="0 = full file")
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text())
    repos = manifest["translation_repos"]
    if args.shipped:
        repos = [r for r in repos if r["shipped"]]
    elif args.pending:
        repos = [r for r in repos if not r["shipped"]]
    elif args.pids:
        sel = set(args.pids.split(","))
        repos = [r for r in repos if r["pid"] in sel]

    print(f"Hashing {len(repos)} translation repos (max_bytes={args.max_bytes or 'full'})...")
    out = {
        "_generated_at": datetime.now(timezone.utc).isoformat(),
        "_doctor": "Opus 4.6 Opus-Claw (Dr. C)",
        "_max_bytes": args.max_bytes,
        "translation_hashes": {},
        "stt_voice_hashes": {},
        "stt_lingua_hashes": {},
    }
    t0 = time.time()
    for i, r in enumerate(repos, 1):
        pdir = MODELS / f"windy-pair-{r['pid']}"
        per_variant = {}
        for v in r["variants_planned"]:
            wp = pdir / v["subfolder"] / v["weight_file"]
            if wp.exists():
                h, n = sha256_file(wp, args.max_bytes)
                per_variant[v["subfolder"]] = {"sha256": h, "bytes_hashed": n}
        out["translation_hashes"][r["pid"]] = per_variant
        if i % 50 == 0:
            print(f"  {i}/{len(repos)}  ({time.time()-t0:.1f}s)")

    for d in sorted(STT_REBUILT.iterdir()):
        if not d.is_dir():
            continue
        weight = next((d / c for c in ("model.safetensors", "pytorch_model.bin") if (d / c).exists()), None)
        if weight:
            h, n = sha256_file(weight, args.max_bytes)
            out["stt_voice_hashes"][d.name] = {"sha256": h, "bytes_hashed": n}

    for d in sorted(STT_LINGUA.iterdir()):
        if not d.is_dir():
            continue
        weight = next((d / c for c in ("model.safetensors", "pytorch_model.bin", "model.bin") if (d / c).exists()), None)
        if weight:
            h, n = sha256_file(weight, args.max_bytes)
            out["stt_lingua_hashes"][d.name] = {"sha256": h, "bytes_hashed": n}

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = CLINIC / "huggingface-uploads" / f"upload_manifest_hashes_{stamp}.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {out_path} ({out_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Parallel HuggingFace downloader for fleet restoration + STT sync.

Reads a JSON list of {pid, source_repo} items and snapshot_downloads each
into a target directory. Resumable (skips directories that already have a
model file). Writes a progress JSON + a per-run log.

Invocation:
  python3 restore_downloads.py <list.json> <dest_dir> [--workers N] [--label TAG]

Doctor: Opus 4.6 Opus-Claw (Dr. C)
Date:   2026-04-11
"""

import argparse
import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import snapshot_download
from huggingface_hub.errors import RepositoryNotFoundError, HfHubHTTPError

# What files to pull. Skip the ones we don't need (flax, tf, onnx, etc.)
ALLOW_PATTERNS = [
    "*.safetensors",
    "pytorch_model.bin",
    "model.bin",          # ctranslate2
    "*.npz",              # Marian native (HPLT)
    "config.json",
    "tokenizer_config.json",
    "tokenizer.json",
    "source.spm",
    "target.spm",
    "*.spm",              # HPLT uses model.en-nb.spm naming
    "*.vocab",            # HPLT .vocab
    "vocabulary.json",    # ctranslate2
    "vocab.json",
    "generation_config.json",
    "special_tokens_map.json",
    "spiece.model",
    "preprocessor_config.json",
    "added_tokens.json",
    "normalizer.json",
    "merges.txt",
    "README.md",
]


def already_done(dest: Path) -> bool:
    """True if dest has at least one weight file."""
    if not dest.exists():
        return False
    for f in dest.rglob("*"):
        if not f.is_file():
            continue
        if f.name in ("model.safetensors", "pytorch_model.bin", "model.bin"):
            return True
        if f.suffix in (".npz", ".safetensors"):
            return True
    return False


def download_one(item: dict, dest_dir: Path, logf) -> dict:
    pid = item["pid"]
    repo = item["source_repo"]
    dest = dest_dir / pid

    result = {"pid": pid, "repo": repo, "dest": str(dest)}
    t0 = time.time()

    if already_done(dest):
        result["status"] = "already_done"
        result["elapsed"] = 0
        logf.write(f"[{datetime.now(timezone.utc).isoformat()}] SKIP {pid} (already_done)\n")
        logf.flush()
        return result

    try:
        snapshot_download(
            repo_id=repo,
            local_dir=str(dest),
            allow_patterns=ALLOW_PATTERNS,
            max_workers=2,  # per-download worker count
        )
        # Verify
        if already_done(dest):
            result["status"] = "success"
        else:
            result["status"] = "incomplete"
        # Compute size
        size = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())
        result["bytes"] = size
    except RepositoryNotFoundError:
        result["status"] = "not_found"
    except HfHubHTTPError as e:
        result["status"] = "http_error"
        result["error"] = str(e)
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"{type(e).__name__}: {e}"
    result["elapsed"] = round(time.time() - t0, 1)

    logf.write(f"[{datetime.now(timezone.utc).isoformat()}] {result['status'].upper()} {pid} "
               f"({result['elapsed']}s"
               + (f", {result.get('bytes', 0) // (1024*1024)} MB" if 'bytes' in result else '')
               + (f", err={result.get('error', '')[:120]}" if 'error' in result else '')
               + ")\n")
    logf.flush()
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("list_json")
    ap.add_argument("dest_dir")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--label", default="restore")
    args = ap.parse_args()

    items = json.loads(Path(args.list_json).read_text())
    dest_dir = Path(args.dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    run_dir = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/restore_20260411/_logs")
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / f"{args.label}.log"
    progress_path = run_dir / f"{args.label}_progress.json"
    results_path = run_dir / f"{args.label}_results.jsonl"

    print(f"Label:     {args.label}")
    print(f"Items:     {len(items)}")
    print(f"Dest:      {dest_dir}")
    print(f"Workers:   {args.workers}")
    print(f"Log:       {log_path}")

    results = []
    completed = 0

    with open(log_path, "a") as logf, open(results_path, "a") as rf:
        logf.write(f"\n\n=== {args.label} run started at {datetime.now(timezone.utc).isoformat()} ===\n")
        logf.flush()

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(download_one, it, dest_dir, logf): it for it in items}
            for fut in as_completed(futures):
                try:
                    r = fut.result()
                except Exception as e:
                    r = {"pid": futures[fut]["pid"], "status": "driver_error", "error": str(e)}
                results.append(r)
                rf.write(json.dumps(r) + "\n")
                rf.flush()
                completed += 1

                # Update progress
                status_counts = {}
                for x in results:
                    status_counts[x["status"]] = status_counts.get(x["status"], 0) + 1
                progress = {
                    "label": args.label,
                    "total": len(items),
                    "completed": completed,
                    "status_counts": status_counts,
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                }
                progress_path.write_text(json.dumps(progress, indent=2))

                if completed % 10 == 0 or completed == len(items):
                    print(f"  [{completed}/{len(items)}]  {status_counts}")

        logf.write(f"=== {args.label} run finished at {datetime.now(timezone.utc).isoformat()} ===\n")

    # Final summary
    summary = {
        "label": args.label,
        "total": len(items),
        "completed": len(results),
        "status_counts": {s: sum(1 for r in results if r["status"] == s) for s in set(r["status"] for r in results)},
    }
    print()
    print("SUMMARY:", json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

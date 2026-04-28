#!/usr/bin/env python3
"""Rebuild and re-upload README.md for all live WindyWord/translate-* repos.

Uses the current build_translation_readme() from upload_to_huggingface.py, so
README content reflects whatever naming / attribution / parsing is live in
that script at runtime. Only uploads README.md — no variant files, no repo
creation (safe to run outside the daily 300/creation-cap window).

Usage:
  python3 refresh_readmes.py                      # all live translate-* repos
  python3 refresh_readmes.py --pids a,b,c         # specific pids only
  python3 refresh_readmes.py --dry-run            # print first 5 READMEs, no upload
  python3 refresh_readmes.py --limit 10           # cap at 10 repos (smoke test)
  python3 refresh_readmes.py --workers 4          # parallel upload

Doctor: Opus 4.6 Opus-Claw (Dr. C)
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import HfApi

sys.path.insert(0, str(Path(__file__).parent))
from upload_to_huggingface import (
    ORG, PATIENTS, build_translation_readme, log as _upload_log,
)

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
LOG = CLINIC / "huggingface-uploads" / "refresh_readmes.log"
api = HfApi()


def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def list_live_translate_repos():
    """Return set of pids currently live under WindyWord/translate-*."""
    return {m.id.replace("WindyWord/translate-", "") for m in api.list_models(author=ORG)
            if m.id.startswith("WindyWord/translate-")}


def refresh_one(pid):
    pf = PATIENTS / f"{pid}.json"
    if not pf.exists():
        return pid, "no_patient_file"
    chart = json.loads(pf.read_text())
    readme = build_translation_readme(chart)
    tmp = Path(f"/tmp/_readme_refresh_{pid}")
    tmp.mkdir(exist_ok=True)
    try:
        (tmp / "README.md").write_text(readme)
        api.upload_file(
            path_or_fileobj=str(tmp / "README.md"),
            path_in_repo="README.md",
            repo_id=f"{ORG}/translate-{pid}",
            repo_type="model",
            commit_message="Refresh README with updated variant naming and language labels",
        )
        return pid, "ok"
    except Exception as e:
        return pid, f"error:{type(e).__name__}:{str(e)[:120]}"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pids", help="Comma-separated pid list (overrides full scan)")
    ap.add_argument("--limit", type=int, default=0, help="Process at most N repos")
    ap.add_argument("--workers", type=int, default=4, help="Parallel upload workers")
    ap.add_argument("--dry-run", action="store_true", help="Print first 5 READMEs only")
    args = ap.parse_args()

    if args.pids:
        pids = args.pids.split(",")
    else:
        log("Listing live translate-* repos on HF…")
        pids = sorted(list_live_translate_repos())
    if args.limit:
        pids = pids[: args.limit]

    log(f"Refresh target: {len(pids)} repos")

    if args.dry_run:
        for pid in pids[:5]:
            pf = PATIENTS / f"{pid}.json"
            if not pf.exists():
                print(f"--- {pid}: NO PATIENT FILE ---")
                continue
            print(f"--- {pid} ---")
            print(build_translation_readme(json.loads(pf.read_text())))
            print()
        return 0

    t0 = time.time()
    done = 0
    errs = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(refresh_one, pid): pid for pid in pids}
        for i, fut in enumerate(as_completed(futures), 1):
            pid, status = fut.result()
            if status == "ok":
                done += 1
            else:
                errs += 1
                log(f"[{i}/{len(pids)}] {pid}: {status}")
            if i % 50 == 0:
                elapsed = time.time() - t0
                log(f"progress {i}/{len(pids)}  done={done} errs={errs}  ({elapsed:.0f}s, {i/elapsed*60:.1f}/min)")
    log(f"Complete. done={done}, errors={errs}, total={len(pids)}")
    return 0 if errs == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

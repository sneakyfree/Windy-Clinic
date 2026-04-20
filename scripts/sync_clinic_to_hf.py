#!/usr/bin/env python3
"""Sync the local clinic directory to the private HF dataset repo.

Pushes /srv/repos/windy-pro/THE_CLINIC/ (everything except gitignored noise
and large model weights) to `WindyWord/clinic-patient-records` as a private
dataset. Idempotent — safe to re-run after every clinic commit.

Usage:
  python3 sync_clinic_to_hf.py [--message "..."]

Doctor: Opus 4.6 Opus-Claw (Dr. C)
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import HfApi, create_repo

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
DATASET_REPO = "WindyWord/clinic-patient-records"

# Mirror the spirit of .gitignore so we don't push noise or large weights to HF
IGNORE = [
    "__pycache__/**",
    "**/__pycache__/**",
    "**/*.pyc",
    "**/*.pyo",
    "**/*.pyd",
    "*.tmp",
    "*.lock",
    "**/*.lock",
    ".lockfile",
    "backups/pre-*/**",
    "backups/pre-v2-update/**",
    "**/*.bin",
    "**/*.safetensors",
    "**/*.ckpt",
    "_train_temp/**",
    ".DS_Store",
    "Thumbs.db",
    ".vscode/**",
    ".idea/**",
    "**/*.swp",
    "**/*.swo",
    "node_modules/**",
    ".ipynb_checkpoints/**",
    ".env",
    "**/*.local",
    ".git/**",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--message", help="Commit message on the HF dataset")
    args = ap.parse_args()

    api = HfApi()
    try:
        create_repo(repo_id=DATASET_REPO, repo_type="dataset", private=True, exist_ok=True)
    except Exception as e:
        print(f"create_repo failed: {e}", file=sys.stderr)
        return 1

    msg = args.message or (
        f"Clinic sync at {datetime.now(timezone.utc).isoformat()} "
        f"by Opus 4.6 Opus-Claw (Dr. C)"
    )
    print(f"Syncing {CLINIC} → {DATASET_REPO} …")
    api.upload_folder(
        folder_path=str(CLINIC),
        repo_id=DATASET_REPO,
        repo_type="dataset",
        commit_message=msg,
        ignore_patterns=IGNORE,
    )
    info = api.dataset_info(DATASET_REPO)
    print(f"OK — dataset now has {len(info.siblings)} files, last_modified={info.last_modified}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

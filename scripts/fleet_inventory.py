#!/usr/bin/env python3
"""Full-disk fleet inventory — walk the filesystem, enumerate every model
weight directory, reconcile against THE_CLINIC patients.

Logged by: Opus 4.6 Opus-Claw (Dr. C) on 2026-04-11.
"""

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
PATIENTS = CLINIC / "translation-pairs"
STT = CLINIC / "stt-models"
OUT_DIR = CLINIC / "fleet-inventory"
OUT_JSON = OUT_DIR / "FLEET_INVENTORY_20260411.json"
OUT_MD = OUT_DIR / "FLEET_INVENTORY_20260411.md"

# Roots to walk. Ordered so the most-likely-to-have-models comes first.
SEARCH_ROOTS = [
    Path("/home/user1-gpu/Desktop/grants_folder/windy-pro"),
    Path("/srv/repos/windy-pro"),
    Path("/home/user1-gpu/windy-pro"),
    Path("/home/user1-gpu/.cache/huggingface/hub"),
    Path("/home/user1-gpu/Desktop"),
]

# Files that mark a "model directory"
WEIGHT_FILES = {
    "model.safetensors",
    "pytorch_model.bin",
    "model.bin",
    "tf_model.h5",
    "flax_model.msgpack",
    "adapter_model.safetensors",
    "adapter_model.bin",
}
WEIGHT_SUFFIXES = {".gguf", ".onnx"}

# Skip noisy dirs
SKIP_DIRS = {
    "__pycache__", "node_modules", ".git", "lost+found",
    ".venv", "venv", "env", ".mypy_cache", ".pytest_cache",
    "site-packages", ".tox",
}


def is_weight_file(name: str) -> bool:
    if name in WEIGHT_FILES:
        return True
    for suf in WEIGHT_SUFFIXES:
        if name.endswith(suf):
            return True
    return False


def walk_models(root: Path):
    """Yield (model_dir, weight_files, total_size) for every dir with weights."""
    if not root.exists():
        return
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # Prune
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        weights = [f for f in filenames if is_weight_file(f)]
        if not weights:
            continue
        total = 0
        details = []
        for f in weights:
            fp = Path(dirpath) / f
            try:
                s = fp.stat().st_size
                total += s
                details.append({"file": f, "size": s})
            except Exception:
                pass
        yield Path(dirpath), details, total


def classify_model_dir(model_dir: Path) -> dict:
    """Heuristically identify the model: read config.json if present, look for
    base_model_name, infer variant from path, etc."""
    info = {
        "path": str(model_dir),
        "config": None,
        "model_type": None,
        "base_model": None,
        "variant": None,
        "patient_id_guess": None,
    }

    cfg_path = model_dir / "config.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
            info["config"] = {
                "model_type": cfg.get("model_type"),
                "architectures": cfg.get("architectures"),
                "_name_or_path": cfg.get("_name_or_path"),
            }
            info["model_type"] = cfg.get("model_type")
            info["base_model"] = cfg.get("_name_or_path")
        except Exception:
            pass

    # Guess variant from last path component
    name = model_dir.name
    parent_name = model_dir.parent.name
    if name in ("base", "lora", "ct2", "ct2_int8", "herm0", "herm0-ct2",
                "herm0-scripture", "herm0_scripture", "allura"):
        info["variant"] = name
        # Patient ID is the parent dir name, stripped of "windy-pair-" / "windy-stt-"
        pid = parent_name
        for prefix in ("windy-pair-", "windy-stt-", "windy-"):
            if pid.startswith(prefix):
                pid = pid[len(prefix):]
                break
        info["patient_id_guess"] = pid
    else:
        # No variant dir — the model dir itself is the model
        pid = name
        for prefix in ("windy-pair-", "windy-stt-", "windy-"):
            if pid.startswith(prefix):
                pid = pid[len(prefix):]
                break
        info["patient_id_guess"] = pid

    # Whisper/STT heuristic
    if info["model_type"] == "whisper" or "whisper" in (info["base_model"] or "").lower():
        info["kind"] = "stt"
    elif info["model_type"] == "marian":
        info["kind"] = "translation"
    else:
        info["kind"] = "unknown"

    return info


def load_clinic_patients():
    ids = set()
    for p in PATIENTS.glob("*.json"):
        ids.add(p.stem)
    for p in STT.glob("*.json"):
        ids.add(p.stem)
    return ids


def main():
    OUT_DIR.mkdir(exist_ok=True, parents=True)
    ts_iso = datetime.now(timezone.utc).isoformat()
    print(f"Fleet inventory run at {ts_iso}")
    print(f"By: Opus 4.6 Opus-Claw (Dr. C)")
    print()

    clinic_patients = load_clinic_patients()
    print(f"Clinic patients known: {len(clinic_patients)}")

    found = []
    found_paths = set()
    scanned_roots = []

    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        scanned_roots.append(str(root))
        print(f"Scanning: {root}")
        count = 0
        new = 0
        for model_dir, weights, size in walk_models(root):
            count += 1
            p = str(model_dir)
            if p in found_paths:
                continue
            found_paths.add(p)
            info = classify_model_dir(model_dir)
            info["weights"] = weights
            info["total_bytes"] = size
            info["root"] = str(root)
            found.append(info)
            new += 1
        print(f"  scanned {count}, new {new}")

    print()
    print(f"Total model directories found: {len(found)}")

    # Group by patient_id_guess
    by_pid = defaultdict(list)
    for m in found:
        by_pid[m["patient_id_guess"]].append(m)

    print(f"Unique patient-id candidates: {len(by_pid)}")

    # Cross-ref with clinic
    in_clinic = {pid for pid in by_pid if pid in clinic_patients}
    not_in_clinic = {pid for pid in by_pid if pid not in clinic_patients}
    clinic_without_disk = clinic_patients - set(by_pid.keys())

    print(f"On-disk AND in clinic: {len(in_clinic)}")
    print(f"On-disk but NOT in clinic: {len(not_in_clinic)}")
    print(f"In clinic but NOT on disk: {len(clinic_without_disk)}")

    # Totals by kind
    by_kind = defaultdict(lambda: {"count": 0, "bytes": 0})
    for m in found:
        k = m.get("kind", "unknown")
        by_kind[k]["count"] += 1
        by_kind[k]["bytes"] += m["total_bytes"]

    # Totals by variant
    by_variant = defaultdict(lambda: {"count": 0, "bytes": 0})
    for m in found:
        v = m.get("variant") or "(no-variant)"
        by_variant[v]["count"] += 1
        by_variant[v]["bytes"] += m["total_bytes"]

    # Total disk used
    total_bytes = sum(m["total_bytes"] for m in found)
    total_gb = total_bytes / (1024**3)

    summary = {
        "_generated": ts_iso,
        "_generated_by": "Opus 4.6 Opus-Claw (Dr. C)",
        "_machine": "Veron-1 (RTX 5090, Mt Pleasant SC)",
        "_search_roots": scanned_roots,
        "total_model_directories": len(found),
        "total_bytes": total_bytes,
        "total_gb": round(total_gb, 2),
        "unique_patient_ids": len(by_pid),
        "in_clinic_and_on_disk": len(in_clinic),
        "on_disk_not_in_clinic": len(not_in_clinic),
        "on_disk_not_in_clinic_sample": sorted(list(not_in_clinic))[:30],
        "in_clinic_not_on_disk": len(clinic_without_disk),
        "in_clinic_not_on_disk_sample": sorted(list(clinic_without_disk))[:30],
        "by_kind": {k: {"count": v["count"], "gb": round(v["bytes"] / (1024**3), 2)} for k, v in by_kind.items()},
        "by_variant": {k: {"count": v["count"], "gb": round(v["bytes"] / (1024**3), 2)} for k, v in sorted(by_variant.items(), key=lambda kv: -kv[1]["bytes"])},
    }

    # Full details (potentially large)
    full = {
        "summary": summary,
        "models": found,
        "by_patient_id": {k: [m["path"] for m in v] for k, v in sorted(by_pid.items())},
    }
    OUT_JSON.write_text(json.dumps(full, indent=2))
    print(f"Wrote {OUT_JSON}  ({OUT_JSON.stat().st_size // 1024} KB)")

    # Markdown report
    lines = [
        "# FLEET INVENTORY — 2026-04-11",
        "",
        "**By:** Opus 4.6 Opus-Claw (Dr. C)",
        f"**Generated:** {ts_iso}",
        "**Machine:** Veron-1 (RTX 5090, Mt Pleasant SC)",
        "",
        "## Headline",
        "",
        f"- **Total model directories on disk:** {len(found):,}",
        f"- **Total weight storage:** {total_gb:.1f} GB",
        f"- **Unique patient-id candidates:** {len(by_pid):,}",
        f"- **In clinic AND on disk:** {len(in_clinic):,}",
        f"- **On disk but NOT in clinic:** {len(not_in_clinic):,}",
        f"- **In clinic but NOT on disk:** {len(clinic_without_disk):,}",
        "",
        "## Scanned roots",
        "",
    ]
    for r in scanned_roots:
        lines.append(f"- `{r}`")
    lines += ["", "## By kind", "",
              "| Kind | Count | Storage (GB) |", "|---|---|---|"]
    for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1]["bytes"]):
        lines.append(f"| {k} | {v['count']:,} | {v['bytes'] / (1024**3):.1f} |")
    lines += ["", "## By variant directory name", "",
              "| Variant | Count | Storage (GB) |", "|---|---|---|"]
    for k, v in sorted(by_variant.items(), key=lambda kv: -kv[1]["bytes"]):
        lines.append(f"| `{k}` | {v['count']:,} | {v['bytes'] / (1024**3):.1f} |")

    if clinic_without_disk:
        lines += ["", f"## Clinic patients with no on-disk weights ({len(clinic_without_disk)})", ""]
        for pid in sorted(clinic_without_disk)[:50]:
            lines.append(f"- `{pid}`")
        if len(clinic_without_disk) > 50:
            lines.append(f"- ... and {len(clinic_without_disk) - 50} more")

    if not_in_clinic:
        lines += ["", f"## On-disk candidates not in clinic ({len(not_in_clinic)})", ""]
        for pid in sorted(not_in_clinic)[:50]:
            lines.append(f"- `{pid}`")
        if len(not_in_clinic) > 50:
            lines.append(f"- ... and {len(not_in_clinic) - 50} more")

    OUT_MD.write_text("\n".join(lines) + "\n")
    print(f"Wrote {OUT_MD}")


if __name__ == "__main__":
    main()

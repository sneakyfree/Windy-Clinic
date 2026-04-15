#!/usr/bin/env python3
"""Reconcile patient-file variant_cluster status fields with actual on-disk state.

For every patient in THE_CLINIC/translation-pairs/, walk the filesystem and
determine which variants actually exist as loadable weight directories, and
record the ACTUAL state in the patient file. Also append a signed Dr. C
inventory exam to examination_log.

Does NOT modify any model weight files. Read-only on models, write-only on
patient JSONs.

Doctor: Opus 4.6 Opus-Claw (Dr. C)
Date:   2026-04-11
Reason: Herm Zero's GR1 run tested variants that have since been ONNX-exported
        and source-deleted. Patient files still claim those variants are
        "present" when they are in fact archived_as_onnx or missing. This
        reconciliation restores ground truth.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
PATIENTS = CLINIC / "translation-pairs"
INV_JSON = CLINIC / "fleet-inventory" / "FLEET_INVENTORY_20260411.json"

DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"
MACHINE = "Veron-1 (RTX 5090, Mt Pleasant SC)"
RUN_ISO = datetime.now(timezone.utc).isoformat()
EXAM_ID_PREFIX = "DRC-INVENTORY"

MODELS_ROOT = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/models")
PHASE2_ROOT = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/models_phase2")
ONNX_ROOT = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/onnx_fleet")


def find_variants(patient_id: str) -> dict:
    """Return a dict variant_name → {status, path, files, total_bytes}."""
    out = {}

    # Check models/windy-pair-{pid}/<variant>/
    mdir = MODELS_ROOT / f"windy-pair-{patient_id}"
    if mdir.exists():
        for sub in mdir.iterdir():
            if not sub.is_dir():
                continue
            variant = sub.name
            weights = _collect_weights(sub)
            if weights:
                out[_canonical_variant(variant)] = {
                    "status": "present",
                    "path": str(sub),
                    "format": _detect_format(sub),
                    "total_bytes": sum(w["size"] for w in weights),
                    "weight_files": [w["file"] for w in weights],
                }

    # Phase 2 root
    p2dir = PHASE2_ROOT / patient_id
    if not p2dir.exists():
        # Maybe it's named windy-pair-{pid}?
        p2dir = PHASE2_ROOT / f"windy-pair-{patient_id}"
    if p2dir.exists():
        for sub in p2dir.iterdir():
            if not sub.is_dir():
                continue
            weights = _collect_weights(sub)
            if weights:
                key = _canonical_variant(sub.name)
                if key not in out:
                    out[key] = {
                        "status": "present",
                        "path": str(sub),
                        "format": _detect_format(sub),
                        "total_bytes": sum(w["size"] for w in weights),
                        "weight_files": [w["file"] for w in weights],
                    }

    # ONNX fleet
    odir = ONNX_ROOT / f"windy-pair-{patient_id}"
    if odir.exists():
        weights = _collect_weights(odir)
        if weights:
            # If the patient had base/lora/ct2 deleted but ONNX remains, we
            # annotate this as an "archived" state — the variant cluster
            # is preserved as ONNX rather than safetensors.
            out["onnx_int8_archive"] = {
                "status": "archived_as_onnx",
                "path": str(odir),
                "format": "onnx_int8",
                "total_bytes": sum(w["size"] for w in weights),
                "weight_files": [w["file"] for w in weights],
                "note": "Source safetensors deleted after INT8 ONNX export on 2026-03-29.",
            }

    return out


def _canonical_variant(name: str) -> str:
    """Map on-disk directory name to patient_file variant_cluster key."""
    name = name.lower()
    if name == "base":
        return "base"
    if name == "lora":
        return "lora"
    if name == "ct2":
        return "ct2_int8"
    if name == "herm0":
        return "herm0"
    if name in ("herm0-ct2", "herm0_ct2"):
        return "herm0_ct2"
    if name in ("herm0-scripture", "herm0_scripture"):
        return "herm0_scripture"
    return name


def _collect_weights(dir_path: Path) -> list:
    """Return list of weight-file records in a directory."""
    out = []
    try:
        for f in dir_path.iterdir():
            if not f.is_file():
                continue
            if f.name in ("model.safetensors", "pytorch_model.bin",
                          "model.bin", "adapter_model.safetensors"):
                out.append({"file": f.name, "size": f.stat().st_size})
            elif f.suffix in (".onnx", ".gguf"):
                out.append({"file": f.name, "size": f.stat().st_size})
    except (PermissionError, OSError):
        pass
    return out


def _detect_format(dir_path: Path) -> str:
    try:
        names = {f.name for f in dir_path.iterdir() if f.is_file()}
    except Exception:
        return "unknown"
    if "model.safetensors" in names:
        return "safetensors"
    if "pytorch_model.bin" in names:
        return "pytorch_bin"
    if any(n.endswith(".onnx") for n in names):
        return "onnx"
    return "unknown"


def reconcile_patient(patient_file: Path) -> dict:
    chart = json.loads(patient_file.read_text())
    patient_id = chart["patient_id"]

    old_cluster = chart.get("variant_cluster", {}) or {}
    observed = find_variants(patient_id)

    # Compute diff
    diff = {"changed": [], "marked_missing": [], "newly_found": []}

    new_cluster = {}
    for variant, old in old_cluster.items():
        if variant in observed:
            obs = observed[variant]
            new_cluster[variant] = {
                **old,
                "status": "present",
                "on_disk_path": obs["path"],
                "on_disk_bytes": obs["total_bytes"],
                "on_disk_format": obs["format"],
                "on_disk_files": obs["weight_files"],
                "reconciled_at": RUN_ISO,
                "reconciled_by": DOCTOR,
            }
            if old.get("status") != "present":
                diff["changed"].append({"variant": variant, "old": old.get("status"), "new": "present"})
        else:
            # Variant is claimed present but not found on disk
            new_cluster[variant] = {
                **old,
                "status": "missing_from_disk",
                "note": "Weights not found on disk. May have been deleted, renamed, or archived as ONNX (see variant_cluster.onnx_int8_archive if present).",
                "reconciled_at": RUN_ISO,
                "reconciled_by": DOCTOR,
            }
            if old.get("status") == "present":
                diff["marked_missing"].append(variant)

    # Add any newly-observed variants that weren't in the old cluster
    for variant, obs in observed.items():
        if variant not in new_cluster:
            new_cluster[variant] = {
                "status": obs["status"],
                "on_disk_path": obs["path"],
                "on_disk_bytes": obs["total_bytes"],
                "on_disk_format": obs["format"],
                "on_disk_files": obs["weight_files"],
                "reconciled_at": RUN_ISO,
                "reconciled_by": DOCTOR,
            }
            if "note" in obs:
                new_cluster[variant]["note"] = obs["note"]
            diff["newly_found"].append(variant)

    chart["variant_cluster"] = new_cluster

    # Build examination entry
    exam = {
        "exam_id": f"{EXAM_ID_PREFIX}-{patient_id}",
        "date": RUN_ISO,
        "doctor": DOCTOR,
        "machine": MACHINE,
        "method": "Non-invasive filesystem walk + variant_cluster reconciliation",
        "protocol_script": "scripts/reconcile_variant_state.py",
        "scope": "read-only model inspection; write-only patient file update",
        "observed_variants": sorted(observed.keys()),
        "diff": diff,
        "notes": (
            "Fleet inventory audit by Opus 4.6 Opus-Claw (Dr. C) on 2026-04-11. "
            "Non-destructive: no model weights were modified, created, or deleted. "
            "Only this patient JSON file was updated. The purpose of this audit was "
            "to reconcile claimed variant presence against actual on-disk state, "
            "because between Herm Zero's Grand Rounds run (2026-03-28/29) and "
            "today, 374 of the 375 OPUS-improved models were ONNX-INT8-exported "
            "and their source safetensors were deleted, but the patient files "
            "still claimed the safetensors were 'present'. This audit updates "
            "each patient file's variant_cluster.<variant>.status to reflect "
            "what is actually on disk right now."
        ),
    }

    # Append to examination_log (idempotent by exam_id)
    log = chart.setdefault("examination_log", [])
    if not any(e.get("exam_id") == exam["exam_id"] for e in log):
        log.append(exam)

    chart["_last_updated"] = RUN_ISO
    return chart, diff


def main():
    patient_files = sorted(PATIENTS.glob("*.json"))
    print(f"Reconciling {len(patient_files)} patient files...")

    stats = {
        "total": 0,
        "unchanged": 0,
        "marked_missing_any": 0,
        "newly_found_any": 0,
        "no_variants_at_all": 0,
        "total_variants_marked_missing": 0,
    }

    for pf in patient_files:
        stats["total"] += 1
        chart, diff = reconcile_patient(pf)
        pf.write_text(json.dumps(chart, indent=2))

        if diff["marked_missing"]:
            stats["marked_missing_any"] += 1
            stats["total_variants_marked_missing"] += len(diff["marked_missing"])
        if diff["newly_found"]:
            stats["newly_found_any"] += 1
        if not any(v.get("status") == "present" for v in chart["variant_cluster"].values()):
            stats["no_variants_at_all"] += 1
        if not diff["marked_missing"] and not diff["newly_found"]:
            stats["unchanged"] += 1

    print(f"Stats: {json.dumps(stats, indent=2)}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Symlink restored Helsinki-NLP models into ~/Desktop/grants_folder/windy-pro/models/
so the existing grand_rounds_harness.py can find them as base variants.

Takes models from restore_20260411/phase1_onnx_restore/{pid}/ and creates:
  models/windy-pair-{pid}/base -> ../../restore_20260411/phase1_onnx_restore/{pid}

This allows the harness to read restored weights without moving any files,
and without overwriting any existing models (only creates links where the
target dir doesn't already exist).

Also updates each affected patient file with a signed Dr. C entry.

Doctor: Opus 4.6 Opus-Claw (Dr. C)
Date:   2026-04-11
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

MODELS = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/models")
RESTORE = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/restore_20260411/phase1_onnx_restore")
LOST_RESTORE = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/restore_20260411/phase1_lost")
PATIENTS = Path("/srv/repos/windy-pro/THE_CLINIC/translation-pairs")

DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"
MACHINE = "Veron-1 (RTX 5090, Mt Pleasant SC)"
RUN_ISO = datetime.now(timezone.utc).isoformat()


def is_valid_model_dir(p: Path) -> bool:
    """Has a weight file AND a config.json (or tokenizer)."""
    if not p.exists():
        return False
    has_weights = any((p / n).exists() for n in ("model.safetensors", "pytorch_model.bin"))
    has_config = (p / "config.json").exists()
    return has_weights and has_config


def link_restored(restore_dir: Path, label: str):
    created = 0
    skipped_existing = 0
    skipped_invalid = 0
    updated_patients = 0

    for restored in sorted(restore_dir.iterdir()):
        if not restored.is_dir():
            continue
        pid = restored.name

        if not is_valid_model_dir(restored):
            skipped_invalid += 1
            continue

        target_parent = MODELS / f"windy-pair-{pid}"
        target_base = target_parent / "base"

        if target_base.exists():
            skipped_existing += 1
            continue

        target_parent.mkdir(parents=True, exist_ok=True)
        # Create relative symlink so it stays portable
        rel = os.path.relpath(str(restored), str(target_parent))
        os.symlink(rel, str(target_base))
        created += 1

        # Update patient file
        pf = PATIENTS / f"{pid}.json"
        if pf.exists():
            chart = json.loads(pf.read_text())
            vc = chart.setdefault("variant_cluster", {})

            # Mark base as present (pointing at restored)
            old_base = vc.get("base", {})
            vc["base"] = {
                **old_base,
                "status": "present",
                "on_disk_path": str(target_base),
                "on_disk_target": str(restored),
                "on_disk_format": "pytorch_bin",
                "note": (
                    f"Restored from HuggingFace {label} on 2026-04-11 "
                    f"by {DOCTOR}. Symlinked into models/ for harness compatibility. "
                    f"Actual files live in {restored}."
                ),
                "restored_at": RUN_ISO,
                "restored_by": DOCTOR,
            }

            log = chart.setdefault("examination_log", [])
            exam_id = f"DRC-RESTORE-{pid}"
            if not any(e.get("exam_id") == exam_id for e in log):
                log.append({
                    "exam_id": exam_id,
                    "date": RUN_ISO,
                    "doctor": DOCTOR,
                    "machine": MACHINE,
                    "method": f"HuggingFace snapshot_download ({label}) + symlink into models/",
                    "protocol_script": "scripts/link_restored_to_models.py",
                    "variants_restored": ["base"],
                    "notes": (
                        f"On 2026-03-29 ~18:25-20:09 UTC, this patient's base/lora/ct2 "
                        f"safetensors were deleted after INT8 ONNX export. Only "
                        f"model_int8.onnx (56 MB, no tokenizer) remained locally. "
                        f"On 2026-04-11, {DOCTOR} re-downloaded the original Helsinki-NLP "
                        f"base weights from HuggingFace and symlinked them into "
                        f"models/windy-pair-{pid}/base so the grand rounds harness "
                        f"can load them. The restored base is the ORIGINAL pre-fine-tune "
                        f"Helsinki-NLP weights — NOT Herm Zero's OPUS-improved herm0 "
                        f"variant (those exist only as INT8 ONNX at "
                        f"~/Desktop/grants_folder/windy-pro/onnx_fleet/windy-pair-{pid}/). "
                        f"Non-destructive: symlinks only, no files moved or deleted."
                    ),
                })
            chart["_last_updated"] = RUN_ISO
            pf.write_text(json.dumps(chart, indent=2))
            updated_patients += 1

    return {
        "label": label,
        "created": created,
        "skipped_existing": skipped_existing,
        "skipped_invalid": skipped_invalid,
        "updated_patients": updated_patients,
    }


def main():
    print(f"Linking restored models into {MODELS}...")

    stats_onnx = link_restored(RESTORE, "phase1_onnx_restore")
    stats_lost = link_restored(LOST_RESTORE, "phase1_lost")

    print(json.dumps({"phase1_onnx_restore": stats_onnx, "phase1_lost": stats_lost}, indent=2))


if __name__ == "__main__":
    main()

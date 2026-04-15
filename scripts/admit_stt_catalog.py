#!/usr/bin/env python3
"""Admit the STT/voice shipping catalog into THE_CLINIC as metadata-only patients.

Reads:
  - src/models/model_registry.json   (the 2026-03-10 Kit OC1 Alpha catalog)
  - Desktop/grants_folder/.../artifacts/lora_checkpoints/   (local LoRA adapters)

Writes:
  - stt-models/<patient_id>.json     (one per voice/lingua model)
  - stt-models/MASTER_ROSTER.json    (index)
  - stt-models/README.md             (explains local-vs-remote state)

These are METADATA-ONLY patients. The actual weights live on HuggingFace
(WindyLabs/*) or on a remote machine where the live fine-tuning runs.
Nothing is tested here — admission only.
"""

import json
from datetime import datetime
from pathlib import Path

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
STT_DIR = CLINIC / "stt-models"
REGISTRY = Path("/srv/repos/windy-pro/src/models/model_registry.json")
LORA_DIR = Path(
    "/home/user1-gpu/Desktop/grants_folder/windy-pro/artifacts/lora_checkpoints"
)


def slug(s: str) -> str:
    return s.replace("/", "_").replace(" ", "_")


def load_local_lora_adapters() -> dict:
    """Return mapping run_name -> training_meta dict for local LoRA adapters."""
    adapters = {}
    if not LORA_DIR.exists():
        return adapters
    for meta_path in LORA_DIR.rglob("training_meta.json"):
        try:
            meta = json.loads(meta_path.read_text())
            run = meta.get("run_name", meta_path.parent.name)
            meta["_checkpoint_dir"] = str(meta_path.parent)
            adapters[run] = meta
        except Exception as e:
            print(f"  WARN: could not read {meta_path}: {e}")
    return adapters


def make_patient_from_catalog_entry(entry: dict, kind: str,
                                     local_adapters: dict) -> dict:
    """Build a minimal patient chart from a model_registry catalog entry."""
    model_id = entry.get("id")
    base_model = entry.get("base_model") or entry.get("base")
    base_license = entry.get("base_license")

    # Try to link any local LoRA adapter with matching base model
    linked_adapters = []
    if base_model:
        short = base_model.split("/")[-1]
        for run, meta in local_adapters.items():
            hf = meta.get("hf_model", "")
            if short in hf or short.replace("whisper-", "") in run:
                linked_adapters.append({
                    "run_name": run,
                    "base": meta.get("hf_model"),
                    "timestamp": meta.get("timestamp"),
                    "best_eval_loss": meta.get("best_eval_loss"),
                    "lora_r": meta.get("lora_r"),
                    "lora_alpha": meta.get("lora_alpha"),
                    "checkpoint_dir": meta["_checkpoint_dir"],
                    "local_present": True,
                })

    variant_cluster = {}
    if entry.get("variant") == "cpu-int8" or entry.get("format") == "ctranslate2-int8":
        variant_cluster["ct2_int8"] = {
            "status": "catalogued_not_local",
            "format": "ctranslate2-int8",
            "size_mb": entry.get("size_on_disk_mb") or entry.get("size_mb"),
            "hf_repo": entry.get("huggingface") or entry.get("hf_repo"),
        }
    else:
        variant_cluster["base"] = {
            "status": "catalogued_not_local",
            "format": entry.get("format"),
            "size_mb": entry.get("size_on_disk_mb") or entry.get("size_mb"),
            "hf_repo": entry.get("huggingface") or entry.get("hf_repo"),
            "base_model_source": base_model,
            "base_license": base_license,
        }

    return {
        "_schema": "windstorm_clinic_stt_v1",
        "_last_updated": datetime.now().isoformat(),
        "_clinic_path": f"stt-models/{model_id}.json",
        "_filing_note": (
            "Metadata-only record. Weights live on HuggingFace (WindyLabs/*) "
            "or on the remote training machine. Not locally testable."
        ),
        "patient_id": model_id,
        "kind": kind,
        "name": entry.get("name"),
        "admitted": "2026-04-11",
        "admitted_by": "Opus 4.6 Opus-Claw (Dr. C)",
        "source_registry": "/srv/repos/windy-pro/src/models/model_registry.json v5.0.0 (2026-03-10, Kit 0C1 Alpha)",
        "source_repo": base_model,
        "hf_repo": entry.get("huggingface") or entry.get("hf_repo"),
        "language": entry.get("language"),
        "language_pair": entry.get("language_pair"),
        "variant_cluster": variant_cluster,
        "training_artifacts": {
            "lora_adapters_local": linked_adapters,
        },
        "examination_log": [],
        "consensus": {
            "status": "awaiting_sync",
            "notes": "Shipping catalog entry from 2026-03-10. Local merged weights not present — can only be tested after pulling from HuggingFace or remote machine.",
        },
    }


def main():
    STT_DIR.mkdir(exist_ok=True, parents=True)

    registry = json.loads(REGISTRY.read_text())
    local_adapters = load_local_lora_adapters()
    print(f"Loaded {len(local_adapters)} local LoRA adapters")

    patients = []

    # Main "models" list (the 19 Windy-branded voice + 2 translation)
    for entry in registry.get("models", []):
        kind = entry.get("category") or "voice"
        if kind == "translation":
            continue  # covered by translation-pairs/
        p = make_patient_from_catalog_entry(entry, f"stt_{kind}", local_adapters)
        patients.append(p)

    # "lingua_models" list (per-language STT)
    for entry in registry.get("lingua_models", []):
        p = make_patient_from_catalog_entry(entry, "stt_lingua", local_adapters)
        patients.append(p)

    # pair_models are translation — skip, already tracked in translation-pairs/

    # Write patient files
    wrote = 0
    for p in patients:
        out = STT_DIR / f"{p['patient_id']}.json"
        if out.exists():
            existing = json.loads(out.read_text())
            if existing.get("_schema") == "windstorm_clinic_stt_v1":
                continue
        out.write_text(json.dumps(p, indent=2))
        wrote += 1

    # Write roster
    roster = {
        "_generated": datetime.now().isoformat(),
        "_clinic_version": "stt_v1",
        "_source": "src/models/model_registry.json v5.0.0",
        "_note": "Metadata-only catalog. Weights not local.",
        "_total_patients": len(patients),
        "_local_lora_adapters": len(local_adapters),
        "patients": {
            p["patient_id"]: {
                "kind": p["kind"],
                "name": p["name"],
                "language": p.get("language"),
                "hf_repo": p.get("hf_repo"),
                "source_repo": p.get("source_repo"),
                "has_local_lora": bool(p["training_artifacts"]["lora_adapters_local"]),
                "status": "catalogued_not_local",
            }
            for p in patients
        },
    }
    (STT_DIR / "MASTER_ROSTER.json").write_text(json.dumps(roster, indent=2))

    # README
    readme = f"""# THE CLINIC — STT / Voice Models

**Status:** Metadata-only catalog (admitted 2026-04-11 by Opus 4.6)

## What's here

{len(patients)} patient records covering the Windy Word STT/voice shipping catalog
as of the 2026-03-10 `src/models/model_registry.json` (v5.0.0, Kit 0C1 Alpha).

- **Windy voice fleet**: {sum(1 for p in patients if p['kind'].startswith('stt_voice'))}
  models (whisper-tiny through whisper-large-v3, GPU + CT2 CPU variants, plus 3 distil)
- **Windy Lingua (per-language STT)**: {sum(1 for p in patients if p['kind'] == 'stt_lingua')}
  models (Spanish, Chinese, Hindi, French, Arabic — safetensors + CT2 variants)

## Local state

The actual model weights are **NOT on this machine**. They live on:
- HuggingFace: `WindyLabs/*` repos
- The remote machine where the live fine-tuning agent runs

What IS locally present:
- `{len(local_adapters)}` whisper LoRA adapter checkpoints in
  `~/Desktop/grants_folder/windy-pro/artifacts/lora_checkpoints/` (Feb 25-26 2026 work)

Linked adapter pointers are in each patient file under
`training_artifacts.lora_adapters_local`.

## Intentionally NOT done

- No testing. Nothing here was exercised against audio — the weights aren't local.
- No merging of remote fine-tune output. We don't have it.
- No overlap with `translation-pairs/` — the 16 pair translation models in
  the registry are already tracked there under their language-pair IDs.

## Next steps (when the remote fleet is ready to sync)

1. Pull the merged STT weights from HuggingFace or the remote machine.
2. Update `variant_cluster.*.status` from `catalogued_not_local` to `present`.
3. Run a whisper-appropriate stress/WER/latency battery (the MarianMT Grand
   Rounds harness doesn't apply to ASR models — needs a separate harness).
4. Admit true examinations to each patient's `examination_log`.

## See also

- `translation-pairs/` — the 1,826-patient MarianMT translation fleet
- `grand-rounds/GR1_STATE_OF_UNION.json` — Grand Rounds v1 results for the
  translation fleet (2026-03-28/29, Herm Zero)
"""
    (STT_DIR / "README.md").write_text(readme)

    print(f"Admitted {len(patients)} STT/voice patients ({wrote} newly written)")
    print(f"Directory: {STT_DIR}")


if __name__ == "__main__":
    main()

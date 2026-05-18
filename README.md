# THE CLINIC — WindyWord Model Fleet Operational Records

**Private repository.** Do not make public — contains internal methodology, agent attribution, and forensic operational history.

## What this is

This is the canonical record of every model examination, training run, quantization, restore, and certification performed on the WindyWord translation + STT fleet. Every model is a "patient" with a JSON chart. Every agent (AI or human) that touched a model is a "doctor" who signed an exam entry with timestamp and methodology.

**Sibling of:** `github.com/sneakyfree/windy-pro` (platform code) — kept separate for cleaner access control and visibility.

## Directory layout

```
THE_CLINIC/
├── translation-pairs/    1,826 patient JSON files — one per Helsinki-NLP language pair
├── stt-models/           50 STT (whisper) patient files
├── doctor-logs/          Narrative reports from each doctor (Dr. A, B, C)
│                         Including state-of-union reports and forensic findings
├── grand-rounds/         Test results and checkpoints from Grand Rounds v1 & v2
├── fleet-inventory/      Periodic full-disk inventory snapshots
├── scripts/              Pipeline Python scripts — training, quantization, certification
├── backups/              Pre-change snapshots (most excluded via .gitignore due to size)
├── MASTER_ROSTER.json    Current fleet index (rebuilt after major operations)
└── README.md             This file
```

## Doctor registry

| ID | Name | Active | Role |
|---|---|---|---|
| Dr. A | Kit OC1 Alpha | 21-23 Mar 2026 | Phase 1 fleet build, LoRA fog-of-mirror, STT catalog |
| Dr. B | Herm Zero (H0) | 24-29 Mar 2026 | CT2 fix, OPUS+eBible fine-tune, Grand Rounds v1, undocumented 2026-03-29 quantization event |
| Dr. C | Opus 4.6 Opus-Claw | 11 Apr 2026+ | Full inventory audit, HF restore, Phase 3a verification, Phase 3b+4 improvement pipelines, real CT2 INT8, Grand Rounds v2, STT rebuild |
| Dr. D | Opus 4.7 1M-Context | 18 May 2026+ | ADR-039 Phase C clone WindyWord → WindstormLabs; clinic signoff wiring for Phase C; introduced clinic-wide `fleet_events.jsonl` event journal; backfilled 1,174 silently-completed clones |

Next agent: pick letter E, F, G...

## Patient file schema

Every patient JSON contains:
- **Identity**: `patient_id`, `source_repo`, language codes
- **Variant cluster**: which formats are on disk (base, lora, herm0, scripture, CT2 INT8, ONNX, etc.)
- **Examination log**: every test or operation, signed by the doctor who ran it with ISO-8601 timestamp, methodology, and notes
- **Surgical log**: destructive changes (deletions, renames, quantization)
- **Quality rating**: current 5-star rating from Grand Rounds v2
- **Consensus**: aggregated findings across all examinations

## Signoff convention

Every agent who touches a patient file MUST add an examination log entry with:
- ISO-8601 date/time
- Doctor name (full: `Opus 4.6 Opus-Claw (Dr. C)`, not just `Dr. C`)
- Machine (`Veron-1 (RTX 5090, Mt Pleasant SC)`)
- Method (what was done, with hyperparameters and metrics)
- Notes (narrative context)

No silent changes. No unsigned work. If you find an unsigned change, it's either a pre-convention artifact (before 2026-04-11) or an error.

## Backup strategy

| Layer | Location | Contents | Frequency |
|---|---|---|---|
| **1. This repo** | github.com/sneakyfree/Windy-Clinic | All clinic records + scripts | Push after each agent session |
| **2. HuggingFace dataset** | `WindyWord/clinic-patient-records` (private) | Mirror of this repo | Push after each agent session |
| **3. Local (optional)** | USB drive or NAS on Veron-1 | Full filesystem snapshot | Weekly |

The original working copy lives at `/srv/repos/windy-pro/THE_CLINIC/` on Veron-1.

## Related scripts

See `scripts/` for the full pipeline. Highlights:
- `build_roster.py` — rebuild MASTER_ROSTER.json from all patient files
- `fleet_inventory.py` — walk the filesystem and produce a full inventory report
- `reconcile_variant_state.py` — audit disk state vs patient file claims, fix drift
- `grand_rounds_v2.py` + `grand_rounds_v2_runner.py` — paragraph-level 8-test quality battery with 5-star rating
- `herm0_pipeline_parallel.py` — parallel OPUS-100 fine-tune pipeline (3 workers)
- `ct2_quantize_lora_fleet.py` — real CT2 INT8 quantization from lora/ proprietary weights
- `onnx_export_fleet.py` + `onnx_int8_quantize_fleet.py` — ONNX FP32 + INT8 deployment exports

## Current fleet state (as of last commit)

See `MASTER_ROSTER.json` for detailed per-patient status and `doctor-logs/` for narrative reports.

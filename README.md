# THE CLINIC — WindyWord Model Fleet Operational Records

**Private repository.** Do not make public — contains internal methodology, agent attribution, and forensic operational history.

## What this is

This is the canonical record of every model examination, training run, quantization, restore, certification, and Hugging Face migration performed on the WindyWord translation + STT fleet. Every model is a "patient" with a JSON chart. Every agent (AI or human) that touched a model is a "doctor" who signed an exam entry with timestamp and methodology.

The clinic is **the only artifact that ties everything together** — local working copies, the WindyWord consumer-brand HF account, the WindstormLabs canonical R&D HF account, and the upstream Helsinki-NLP archives. No model is recorded in only one place; the clinic patient file cross-references all of them.

**Sibling of:** `github.com/sneakyfree/windy-pro` (platform code) — kept separate for cleaner access control and visibility.

## Directory layout

```
THE_CLINIC/
├── translation-pairs/      1,828 patient JSON files — one per Helsinki-NLP language pair
├── stt-models/             91 STT (whisper) patient files
├── doctor-logs/            Narrative reports from each doctor (Dr. A, B, C, D)
│                           Including state-of-union reports and forensic findings
├── grand-rounds/           Test results and checkpoints from Grand Rounds v1 & v2
├── fleet-inventory/        Periodic full-disk inventory snapshots
├── huggingface-uploads/    Append-only HF migration logs:
│                             - upload_results.jsonl  (HF-specific row per upload)
│                             - fleet_events.jsonl    (clinic-wide event journal, 3,200+ rows)
├── scripts/                Pipeline Python scripts — training, quantization, certification
├── backups/                Pre-change snapshots (most excluded via .gitignore due to size)
├── MASTER_ROSTER.json      Current fleet index (rebuilt after major operations)
└── README.md               This file
```

## Doctor registry

| ID | Name | Active | Role |
|---|---|---|---|
| Dr. A | Kit OC1 Alpha | 21-23 Mar 2026 | Phase 1 fleet build, LoRA fog-of-mirror, STT catalog |
| Dr. B | Herm Zero (H0) | 24-29 Mar 2026 | CT2 fix, OPUS+eBible fine-tune, Grand Rounds v1, undocumented 2026-03-29 quantization event |
| Dr. C | Opus 4.6 Opus-Claw | 11 Apr 2026+ | Full inventory audit, HF restore, Phase 3a verification, Phase 3b+4 improvement pipelines, real CT2 INT8, Grand Rounds v2, STT rebuild |
| Dr. D | Opus 4.7 1M-Context | 18 May 2026+ | ADR-039 Phase C+D — full migration of WindyWord translate-* (1,609) and listen-* (59) to WindstormLabs; Phase D upstream archive (1,522 Helsinki-NLP/opus-mt-* mirrored byte-perfect with per-LFS SHA-256 attestation, including 9 with minimal README YAML patches for HF-validator-rejected entries); introduced clinic-wide `fleet_events.jsonl` event journal; backfilled 1,174 silently-completed Phase C clones; closed all unknown-upstream gaps via README inspection; documented reboot-resilience for `/tmp/Windy-Clinic` symlink and `is_done()` schema-evolution gotcha |

Next agent: pick letter E, F, G...

## Archive architecture — the full picture

The WindyWord fleet now lives at **six addresses per language pair**, each with a distinct role. The clinic patient file is the only thing that links them all.

```
                ┌─────────────────────────────────────────────────────────┐
                │  THE CLINIC (this repo) — single source of truth        │
                │  translation-pairs/<pair>.json  carries pointers to ALL │
                │  five external addresses + lineage + signed exam_log    │
                └─────────────────────────────────────────────────────────┘
                     │              │              │              │
        ┌────────────┴────┐  ┌──────┴──────┐ ┌─────┴────────┐ ┌───┴──────────────┐
        │ Local working   │  │ WindyWord/  │ │ Windstorm-   │ │ WindstormLabs/   │
        │  copy           │  │ translate-* │ │  Labs/       │ │ origin-Helsinki- │
        │ (windy-pair-*/) │  │             │ │ translate-*  │ │ NLP-opus-mt-*    │
        │ 522 GB / 1,607  │  │ 1,609 repos │ │ 1,609 repos  │ │ 1,522 repos      │
        │  base + lora +  │  │ consumer    │ │ canonical    │ │ byte-perfect     │
        │  herm0 +ct2int8 │  │ brand,      │ │ R&D brand,   │ │ snapshot of      │
        │                 │  │ frozen      │ │ source of    │ │ Helsinki-NLP/    │
        │                 │  │             │ │ truth        │ │ opus-mt-* main   │
        └─────────────────┘  └─────────────┘ └──────────────┘ └──────────────────┘
                                                                       │
                                                              ┌────────┴────────┐
                                                              │ Helsinki-NLP/   │
                                                              │ opus-mt-*       │
                                                              │ (external —     │
                                                              │  not ours, but  │
                                                              │  mirrored above)│
                                                              └─────────────────┘
```

### Brand architecture (why two HF accounts)

- **`WindyWord`** — legacy consumer-brand HF account, holds the customer-facing names (`translate-en-fr`, `listen-windy-lingua-fr`). **Frozen.** Per Grant 2026-05-13: "took weeks to upload, don't touch."
- **`WindstormLabs`** — the canonical R&D account under Windstorm Institute (parent). Holds the same fine-tunes under the same names *plus* the `origin-*` upstream archive *plus* lab-only models (SceneMachine: wan22-*, ltx2-*, hunyuan-*). **This is the long-term source of truth.**

### Current fleet state (independently verifiable via `HfApi.list_models`)

| Prefix | WindyWord | WindstormLabs | Notes |
|---|---:|---:|---|
| `translate-*` | 1,609 | 1,609 | Byte-identical mirror; Phase C complete 2026-05-19 |
| `listen-*` | 59 | 59 | Byte-identical mirror; listen-* track complete 2026-05-19 |
| `origin-Helsinki-NLP-opus-mt-*` | — | 1,522 | Phase D upstream archive complete 2026-05-25 |
| `origin-HPLT-*` + 1 misc origin | — | 13 | Pre-existing Dr. C work |
| `wan22-* / ltx2-* / hunyuan-*` | — | 7 | SceneMachine R&D models |
| `WindyWord/WindyWord` | 1 | — | Brand index repo |
| **Total** | **1,669** | **3,210** | Labs is a strict superset of WindyWord plus the upstream archive |

### Verification vocabulary

Every checkpoint entry uses a `verify` field with a precise meaning. The vocabulary expanded over the project — older statuses are still valid for entries that pre-date later passes.

| `verify` value | Means |
|---|---|
| `match` | Destination file count equals source file count. No deeper attestation. (Used by Phase C translate-* and listen-* tracks.) |
| `superset` | Destination has *more* files than source. Happens when WindyWord shipped a stub repo and the local upload was more complete. |
| `byte_perfect_match` | File list identical to upstream AND every LFS file's SHA-256 matches upstream. (Phase D origin-* default; introduced 2026-05-20.) |
| `byte_perfect_weights_only_readme_patched` | Weights byte-identical; README YAML was minimally patched to satisfy HF's metadata validator. Used for 9 Helsinki-NLP repos with invalid `language[]` entries (`false`-as-YAML-bool, BCP-47 script suffixes). Patches documented inline via `<!-- WINDSTORM_NOTE: ... -->` block. |
| `preexisting` | Repo already existed on Labs before the current session began; left untouched. Re-verify via `reupload_origin_byte_perfect.py` to upgrade. |
| `unverified` | Could not fetch expected file count from source. Investigate. |
| `subset` | Destination has *fewer* files than source. **ALWAYS investigate** — indicates upload incomplete. |

### Migration scripts (top-level on Veron-1, not in `scripts/`)

| Script | Purpose | Checkpoint |
|---|---|---|
| `/home/user1-gpu/clone_to_labs.py` | translate-* track: local windy-pair-*/ → `WindstormLabs/translate-*` | `clone_to_labs.checkpoint.json` |
| `/home/user1-gpu/clone_listen_to_labs.py` | listen-* track: HF cache → `WindstormLabs/listen-*` | `clone_listen_to_labs.checkpoint.json` |
| `/home/user1-gpu/clone_origin_to_labs.py` | origin-* track: byte-perfect `snapshot_download` from Helsinki-NLP → `WindstormLabs/origin-Helsinki-NLP-opus-mt-*` (includes SHA-256 pass) | `clone_origin_to_labs.checkpoint.json` |
| `/home/user1-gpu/reupload_origin_byte_perfect.py` | Retroactive byte-perfect re-upload + label upgrade for entries originally landed as `match` (Day 1 of Phase D). | shares the origin checkpoint |
| `/home/user1-gpu/repair_origin_readme_8.py` | Sanitize Helsinki-NLP README YAML (`false` → `"no"`, BCP-47 → `language_bcp47`) and re-upload to existing stub repos. No `create_repo` quota cost. | shares the origin checkpoint |

### Hard-won gotchas (don't relearn these)

- **`/tmp/Windy-Clinic` symlink dies on reboot.** `clinic_signoff.py` defaults `CLINIC_ROOT = /tmp/Windy-Clinic` which is meant to symlink to `~/clinic-cache/Windy-Clinic`. `/tmp` is wiped on reboot, so the next pipeline run silently creates an orphan dir there and writes the journal + patient updates to it instead of canonical. **Always verify `test -L /tmp/Windy-Clinic` before any clinic-writing pipeline after a restart.** Recovery recipe: append orphan jsonl to canonical, backfill examination_log from the upload checkpoint, then `ln -s ~/clinic-cache/Windy-Clinic /tmp/Windy-Clinic`.
- **`is_done()` schema evolution.** When the `verify` vocabulary expands (e.g., `match` → also accept `byte_perfect_match`), audit every `is_done`-like skip check in the migration scripts before relaunching. We burned 5 quota slots re-mirroring already-done entries on 2026-05-20 because of this.
- **HF `repos/create` cap is ~300/24h ROLLING per token.** Not UTC-reset. Retry < 24h from the *end* of your last burst = instant 429. The mirror scripts halt cleanly on 429 — but plan launches to clear the rolling window.
- **Helsinki-NLP YAML invalidity.** A subset of `tc-big-*` and a few zlw-fiu-class repos ship YAML `language:` arrays HF's validator now rejects (bare-bool `false` from unquoted `no`, plus underscore-script-tagged BCP-47 entries). `repair_origin_readme_8.py` documents the patch pattern.
- **Older Helsinki-NLP configs lack `_name_or_path`.** Provenance recovery for those falls back to the local README's `hf_name:` field in its System Info block. Documented for the two pairs that bit us (`ru-eu`, `zlw-fiu`).

## Patient file schema

Every patient JSON contains:
- **Identity**: `patient_id`, `source_repo`, language codes
- **Variant cluster**: which formats are on disk (base, lora, herm0, scripture, CT2 INT8, ONNX, etc.)
  - As of Phase C (2026-05-19), every variant block also carries `windstormlabs_url` and `windstormlabs_uploaded_at` linking to the canonical R&D mirror.
  - As of Phase D (2026-05-19+), `variant_cluster.base` additionally carries `upstream_repo`, `upstream_commit_sha_at_record_time`, `upstream_license`, `upstream_recorded_at`, and (where mirrored) `windstormlabs_origin_repo` / `windstormlabs_origin_url` / `windstormlabs_origin_archive_mode` / `windstormlabs_origin_verify`. ISO-alias entries (e.g. `windy-lingua-ar` ⇄ `windy-lingua-arabic`) link via a root-level `iso_aliases` block with SHA-256-verified byte-identical attestation.
- **Examination log**: every test or operation, signed by the doctor who ran it with ISO-8601 timestamp, methodology, and notes. Exam IDs follow conventions like `WSL-CLONE-<ts>-<pair>` (translate mirror), `WSL-CLONE-LISTEN-<ts>-<pair>` (listen mirror), `WSL-PROVENANCE-<ts>-<pair>` (Phase D records), `WSL-ORIGIN-MIRROR-<ts>-<pair>` (origin upload), `WSL-ORIGIN-BYTEPERFECT-<ts>-<pair>` (Day 1 retroactive byte-perfect upgrade), `WSL-ORIGIN-SHA-BACKFILL-<ts>-<pair>` (Day 2 SHA upgrade), `WSL-ORIGIN-README-REPAIR-<ts>-<pair>` (YAML-patched upload), `WSL-ORIGIN-UNKNOWN-RECOVERY-<ts>-<pair>` (unknown-upstream identification + mirror).
- **Surgical log**: destructive changes (deletions, renames, quantization)
- **Quality rating**: current 5-star rating from Grand Rounds v2
- **Consensus**: aggregated findings across all examinations — `last_updated`, `exams_total`, `doctors_examined`

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

## Fleet event journal

`huggingface-uploads/fleet_events.jsonl` is the clinic-wide append-only event journal introduced by Dr. D on 2026-05-18. Schema is op-agnostic:

```json
{"ts": "2026-05-25T22:00:19+00:00",
 "doctor": "Opus 4.7 1M-Context (Dr. D)",
 "machine": "Veron-1 (RTX 5090, Mt Pleasant SC)",
 "session_id": "phase-d-readme-repair-20260525T215834Z-07e26c",
 "op": "origin_readme_repair",
 "scope": "upstream:Helsinki-NLP/opus-mt-tc-big-zls-zle",
 "outcome": "success",
 "payload": {...op-specific...},
 "notes": "..."}
```

Op vocabulary stays open. Today it includes: `session_start`, `session_end`, `hf_clone` (translate/listen), `origin_mirror`, `origin_byteperfect`, `origin_readme_repair`, `origin_unknown_recovery`, `clinic_patch`. New op names are fine; the schema is forward-compatible. Write to it via `clinic_signoff.log_session_event(...)`.

As of the Phase D close: **3,200+ rows** spanning every clinic-touching operation since 2026-05-18.

## Related scripts

See `scripts/` for the in-clinic pipeline. Highlights:
- `build_roster.py` — rebuild MASTER_ROSTER.json from all patient files
- `fleet_inventory.py` — walk the filesystem and produce a full inventory report
- `reconcile_variant_state.py` — audit disk state vs patient file claims, fix drift
- `grand_rounds_v2.py` + `grand_rounds_v2_runner.py` — paragraph-level 8-test quality battery with 5-star rating
- `herm0_pipeline_parallel.py` — parallel OPUS-100 fine-tune pipeline (3 workers)
- `ct2_quantize_lora_fleet.py` — real CT2 INT8 quantization from lora/ proprietary weights
- `onnx_export_fleet.py` + `onnx_int8_quantize_fleet.py` — ONNX FP32 + INT8 deployment exports

The Phase C/D migration scripts live one level up at `/home/user1-gpu/` on Veron-1 (see "Migration scripts" table above). They are kept outside `scripts/` because they read from `clone_*.checkpoint.json` files that also live at `/home/user1-gpu/` for atomic-rename safety during long runs.

## Current fleet state (as of 2026-05-25)

| Track | State |
|---|---|
| translate-* fine-tunes | **1,609 / 1,609** mirrored on WindstormLabs (1,581 match + 28 superset) |
| listen-* fine-tunes | **59 / 59** mirrored on WindstormLabs (byte-identical to WindyWord) |
| origin-Helsinki-NLP upstream archive | **1,522 / 1,522** byte-perfect on WindstormLabs (1,513 byte_perfect_match + 9 byte_perfect_weights_only_readme_patched) |
| Clinic patient files (translation-pairs/) | **1,828** — every windy-pair has `upstream_repo` + `upstream_commit_sha_at_record_time` + `upstream_license` recorded |
| Clinic patient files (stt-models/) | **91** |
| fleet_events.jsonl rows | **3,200+** signed event entries |
| WindstormLabs grand total on HF | **3,210 models** |
| WindyWord grand total on HF | **1,669 models** (frozen, intact) |

The original local working copies live at `/home/user1-gpu/Desktop/grants_folder/windy-pro/models/` (522 GB across 1,607 `windy-pair-*/base/` dirs) on Veron-1.

See `MASTER_ROSTER.json` for detailed per-patient status and `doctor-logs/` for narrative reports.

# Audit Cleanup — 5 bugs fixed — 2026-04-28 (third pass of the day)

**Doctor:** Opus 4.6 Opus-Claw (Dr. C) on Veron-1 (RTX 5090, Mt Pleasant SC)

After Grant asked for an unfiltered ferret-out audit, I ran a comprehensive cross-check of HF reality vs clinic patient files vs installer registry. Five real bugs surfaced; all fixed in this pass.

## Fixes

### 1. WindyWord/translate-pt-en built (was MISSING — broke installer)
The installer's MODEL_REGISTRY had `windy-pair-pt-en` pointing at a non-existent WindyWord repo. No `Helsinki-NLP/opus-mt-pt-en` upstream exists; Helsinki's canonical Portuguese-source path is `opus-mt-ROMANCE-en` (68k+ downloads, multilingual Romance→English). Built `WindyWord/translate-pt-en/lora/` from those weights with a README that clearly discloses the ROMANCE-derived nature. Underlying weights identical to `WindyWord/translate-ROMANCE-en`. Patient file `translation-pairs/pt-en.json` signed `DRC-PORT-pt-en`.

### 2. Voice-tier "fog-of-mirror" remnant scrubbed (10 READMEs)
The `build_stt_readme()` template included the line *"Proprietary fine-tuning by WindyWord.ai team via LoRA fog-of-mirror methodology where applicable."* This was inaccurate for voice tiers — they are direct community Whisper / distil-whisper redistributions, not LoRA-fine-tuned. Updated template, refreshed all 10 voice repos. Verified: 0 `listen-*` repos still mention "fog-of-mirror".

### 3. German lingua language-family line added
`WindyWord/listen-windy-lingua-de` README's `LANG_NOTES["de"]` entry was missing the standard Indo-European > Germanic > West Germanic family line that every other lingua repo has. Added; refresh propagated. Verified.

### 4. WindyLabs/* references swept out of 27 STT patient JSONs
Patient files for windy-core, windy-nano, windy-edge, windy-lingua-spanish, etc., still referenced the dead `WindyLabs/*` HF org in their `hf_repo` and `variant_cluster.*.hf_repo` fields (Dr. A era stale pointers from before the WindyLabs typo was resolved). Sweep updated all CURRENT POINTERS to `WindyWord/listen-*` with appropriate subfolder. Historical narrative in exam logs preserves the Dr. A era context. Each touched file signed `DRC-WINDYLABS-WINDYWORD-MIGRATION-{name}`. Verified: 0 broken `hf_repo` fields remain.

### 5. MASTER_ROSTER.json regenerated (was 12 days stale)
The roster had been at the April 15 snapshot; missing en-pt port, German upgrade, Igbo creation, the WindyProLabs lingua port pass, all WER audits, and the forced_decoder_ids rescue. Re-ran `scripts/build_roster.py`. Fresh roster has 1,827 patients, 27,748 examinations.

## Bonus: 7 stale STT sub-variant patient files annotated as `_consolidated_into_parent`

Files like `windy-core-ct2.json`, `windy-distil-large-onnx.json`, etc. — Phase-2-era separate-repo patient records that no longer correspond to HF reality (we consolidated voice variants into multi-subfolder parent repos on 2026-04-21). Each annotated with `_consolidated_into_parent: { parent_repo, parent_subfolder, ... }` so future doctors understand they're historical-only and the canonical record lives in the parent's patient file.

## Verification (pass)

- HF translate-* without clinic patient file: **0** (target 0)
- STT patient files with broken WindyLabs hf_repo pointers: **0** (target 0)
- listen-* repos with fog-of-mirror remnant: **0** (target 0)
- WindyWord/translate-pt-en: **live** (9 files)
- de README contains language family: **yes**
- MASTER_ROSTER mtime: **just regenerated**

## State of the union after this pass

WindyWord HF org: 1,609 translate + 60 listen + 1 catalog = 1,670 + 1 dataset.

Naming, branding, language-name spellouts, dialect/script disclosures: all uniform.
Patient files ↔ HF: bijective coverage (modulo 219 not_materialized + 7 historical-only sub-variants, all explicitly flagged as such).
Installer: 45/45 entries point at live WindyWord/* repos with valid subfolders. Branch `dr-c/installer-windyword-migration` ready for E2E test before merge.

---

Filed by Opus 4.6 Opus-Claw (Dr. C).

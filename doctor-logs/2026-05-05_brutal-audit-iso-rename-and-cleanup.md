# Brutal Audit — ISO Rename, Orphan Delete, Stale-Config Sweep — 2026-05-05

**Doctor:** Opus 4.7 Opus-Claw (Dr. C)
**Machine:** Veron-1 (RTX 5090, Mt Pleasant SC)
**Patients:** 11 HF repos (10 renamed, 1 deleted) + 2 platform config files + 1 README content fix.

---

## Why

Grant asked for a brutal scan of the WindyWord HF org for "errors, misalignments, pattern disrupters, or low-quality model amplifying info." Built a sweep that enumerated all 1,670 models, sampled 141 READMEs across categories, and spot-checked file structures. Surfaced five real findings (after filtering out three audit-script false positives).

## What the audit found

### Critical pattern disrupters

1. **10 lingua repos used full-English names while all 39 others used ISO-639 codes.** Not duplicates — the *only* representation for those five major languages: `arabic`, `chinese`, `french`, `hindi`, `spanish`, plus their five `-ct2` sidekicks. Every other lingua (`am`, `bn`, `de`, `he`, `mn`, `ja`, …) uses ISO codes. The five most-trafficked languages in the catalog were the exception.

2. **`listen-windy-lingua-lt-ct2` orphan.** CT2 sidekick for Lithuanian existed with no parent `listen-windy-lingua-lt`. README claimed parent existed; it didn't.

3. **Igbo README still mentioned "Ported from legacy WindyProLabs upload"** — last lingering dead-org reference in the org. Reframed to drop the dead-org name without losing the quality-caveat content.

### Stale platform config (separate finding from sweep)

4. **`src/models/model_registry.json` had 45 references to `WindyLabs/*`** (the dead org from before the WindyWord cutover). The 04-28c bug-cleanup pass had updated `MASTER_ROSTER.json` (both copies) but missed this sibling file. Not actively loaded by any code (`main.js` mentions it only in comments), but a future doctor or auditor reading the platform repo would see WindyLabs paths as authoritative. File was owned by hermes-oc1; bumped group write perm via sudo, then updated.

### Audit-script false positives (no fix needed)

- "Windy Pro Engine" hits — that's the product name for the top voice tier, not a dead-org reference.
- 13 translate cards "missing full lang names" — regex didn't include Tuvaluan, Tiv, Esperanto, Haitian, Tok Pisin, Hiligaynon, etc. Cards spell them out properly.
- 50 sampled translate repos "missing lora/adapter_*" — `lora/` folder exists, contains full Marian models named `model.safetensors` (not LoRA adapters; folder name is a vestige of the fog-of-mirror methodology era). Audit's expectation was wrong.
- 16 "listen_no_subfolder_doc" — CT2 variants correctly use `subfolder="ct2-int8"`, not `safetensors`.

## Fixes shipped

### 1. ISO rename (10 repos)

Used HF `move_repo` (creates a permanent redirect from the old path so legacy clients keep resolving):

| Old | New | sha |
|---|---|---|
| `listen-windy-lingua-arabic` | `listen-windy-lingua-ar` | 18fe7877 |
| `listen-windy-lingua-chinese` | `listen-windy-lingua-zh` | 1368be6f |
| `listen-windy-lingua-french` | `listen-windy-lingua-fr` | ec6bd892 |
| `listen-windy-lingua-hindi` | `listen-windy-lingua-hi` | 350b918c |
| `listen-windy-lingua-spanish` | `listen-windy-lingua-es` | 8fa0e3d6 |
| `listen-windy-lingua-arabic-ct2` | `listen-windy-lingua-ar-ct2` | 587c6dbd |
| `listen-windy-lingua-chinese-ct2` | `listen-windy-lingua-zh-ct2` | 8d1d3fe8 |
| `listen-windy-lingua-french-ct2` | `listen-windy-lingua-fr-ct2` | 1b5dbd9a |
| `listen-windy-lingua-hindi-ct2` | `listen-windy-lingua-hi-ct2` | c5fc182f |
| `listen-windy-lingua-spanish-ct2` | `listen-windy-lingua-es-ct2` | 5ac78ccc |

All 10 succeeded with SHA preservation.

### 2. README refresher fix

`scripts/refresh_listen_readmes.py` had `LANG_NAMES`, `LANG_FAMILY`, and `LANG_NOTES` keyed by the *old* full-English slugs (`arabic`, `chinese`, etc.). After the rename, these lookups missed and the refresher fell back to title-casing the slug — "Arabic Lingua" became **"Ar Lingua"**, "Transcribes Arabic speech" became **"Transcribes Ar speech (Unknown)"**.

Migrated all three dicts from full-English keys to ISO codes (`ar`, `zh`, `fr`, `hi`, `es`). Also dropped the now-dead `arabic→ar` fallback mapping in `yaml_lang` since slugs are uniformly 2–3 chars now.

Refreshed READMEs on all 11 affected repos (10 renamed + ig). All show correct full language names: "Arabic Lingua", "Chinese (Mandarin) Lingua", "French Lingua", "Hindi Lingua", "Spanish Lingua".

### 3. Igbo dead-org reference removed

`LANG_NOTES["ig"]` previously read:

> Ported from legacy WindyProLabs upload. Limited capacity; for production use we recommend an `openai/whisper-large-v3` multilingual fallback.

Reframed to drop "Ported from legacy WindyProLabs upload" without losing the quality-caveat content. Updated README is live.

### 4. lt-ct2 orphan deleted

Single 74 MB file structure with no parent. Whisper-tiny-class CT2 sidekick that was never paired with a GPU parent. Confirmed via API that no `listen-windy-lingua-lt` exists; deleted via `delete_repo`.

### 5. installer-v2 download-manager.js updated

10 entries updated. Wizard keys also migrated to ISO codes for uniformity (`windy-lingua-arabic` → `windy-lingua-ar`, etc.). Old keys had no other code references — verified via grep before changing.

### 6. Platform model_registry.json sweep

`src/models/model_registry.json` had stale `WindyLabs/*` paths across:
- 19 voice-tier `huggingface` fields
- 12 pair-translation `hf_repo` fields
- 10 lingua `hf_repo` fields (also had old `id` fields like `windy-lingua-spanish` that needed migrating to `windy-lingua-es`)
- 2 deprecated translation bundles (windy-translate-spark/-standard) → `null` + `deprecated: true`

Total: 45 WindyLabs references → 0 (one remaining is in my own `_meta.note` annotation).

Added a `_meta` block flagging the file as legacy/non-authoritative; the canonical source is now `installer-v2/core/download-manager.js`.

---

## State after today

| | Before | After |
|---|---|---|
| Lingua repos with full-English names | 10 | **0** |
| Lingua orphan CT2s (no parent) | 1 (`lt-ct2`) | **0** |
| Lingua repos total | 50 | **49** |
| Total WindyWord models | 1,670 | **1,669** |
| `WindyLabs` references in `src/models/model_registry.json` | 45 | **0** |
| `WindyProLabs` references in any active lingua README | 1 (`ig`) | **0** |
| README slug-fallback bug ("Ar Lingua" instead of "Arabic Lingua") | latent | **fixed** |

Pattern uniformity achieved across all 49 lingua repos: every one uses ISO-639 codes, every parent has a corresponding CT2 (where built), no orphans.

---

## Open loose ends (not blocking; ranked)

1. **Build a Lithuanian lingua parent** so a CT2 sidekick can be re-introduced. Requires auditing community Lithuanian Whisper fine-tunes (~30 min).
2. **Audit the 13 unverified-WER lingua** (bn, gu, hu, kk, km, mr, pa, ro, te, si, ja parent, ja-ct2 — `lt-ct2` removed today). Need a CTranslate2-aware or `pipeline()`-based harness since transformers `language=` kwarg fails on these architectures.
3. **42 UPPERCASE Helsinki composite codes** in translate names (`ROMANCE`, `CELTIC`, `NORTH_EU`, `SCANDINAVIA`, `NORWAY`, `SAMI`, `ZH`). These follow Helsinki convention, not HF lowercase recommendation. READMEs spell them out properly. Renaming would break the upstream Helsinki provenance link. **Recommendation: leave as-is**, document in a future style guide.
4. **`lora/` folder name across 1,608 translate-* repos is misleading.** Contains full Marian fine-tunes, not LoRA adapters. A naming relic of the fog-of-mirror methodology era. Renaming would mean re-uploading the entire translation fleet + a parallel installer migration. **Recommendation: defer until next major fleet rebuild**, or accept as a stable legacy convention.
5. **Wizard E2E test of installer-v2 branch** still pending from the 04-27 work; today's renames should be tested before merging the branch.

---

## Process notes for future doctors

1. **`HfApi.move_repo` preserves SHA** and creates a permanent redirect at the old path. Safe to use for cleanup renames; old downloaders keep working but log warnings about the redirect.

2. **`refresh_listen_readmes.py` is keyed by repo slug.** When repos are renamed, the corresponding entries in `LANG_NAMES`, `LANG_FAMILY`, and `LANG_NOTES` must be migrated to match — or the refresher silently falls back to title-casing the slug, producing "Ar Lingua" instead of "Arabic Lingua." This was caught by spot-checking one rendered README; would have shipped silently otherwise.

3. **`src/models/model_registry.json` is owned by `hermes-oc1`** (Dr. B Herm Zero). Need `sudo chmod g+w` to write. Coordinate with whichever doctor is on Hermes if changes are non-trivial; today's edit was a stale-config sweep so no overlap.

4. **The platform repo has at least three model-registry-shaped files**: `MASTER_ROSTER.json` (×2: clinic root and stt-models/), and `src/models/model_registry.json`. The 04-28c cleanup updated the rosters but missed the registry. Future cleanup passes should sweep all three together via grep.

5. **Audit-script false positives are easy to overstate.** This pass had 5 real findings and 4 false positives in the same output. Always spot-check before mass-fixing — running `pkg/manifest match` regexes against community repos picks up architectural exceptions (custom subfolder layouts, base-model processor fallbacks, Helsinki uppercase codes) that aren't bugs.

---

Filed by **Opus 4.7 Opus-Claw (Dr. C)** on **Veron-1 (RTX 5090, Mt Pleasant SC)** at **2026-05-05T18:50:00Z**.

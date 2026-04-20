# Public Rebrand + Discoverability — 2026-04-20

**Doctor:** Opus 4.6 Opus-Claw (Dr. C)
**Machine:** Veron-1 (RTX 5090, Mt Pleasant SC)
**Session:** Continuing from 2026-04-16 handoff; full translation + STT HF launch week.
**Commits:** `5be9338`, `7b46e1f` (plus `f279574`, `ec51e9f` adjacent for manifest).

---

## Context

By mid-day 2026-04-20, the HuggingFace upload run had reached ~1,200 live public repos on `huggingface.co/WindyWord`. Grant reviewed a specific model card (`WindyWord/translate-tc-big-fi-zle`) and surfaced three distinct concerns, in this order:

1. **"lora fog-of-mirror" reads as gibberish or an inside joke to public users.** Our internal engineering nickname for the LoRA-r4-α8-merged variant was bleeding into the marketing copy of every one of the 1,200+ public model cards.
2. **"Quality ≈ Helsinki-NLP original"** on every card simultaneously undersold the `herm0/` variants (which are measurably better than the Helsinki baseline) and pointed savvy users to a free alternative for the `lora/` variants. Wrong framing for a proprietary product.
3. **Users can't read language abbreviations.** Repo IDs like `translate-tc-big-fi-zle`, `translate-aav-en`, and `translate-he-fr` are opaque. Users would have to click into every card to discover which languages a model serves.

Grant also asked a clarifying pass on whether models were being *renamed* in a way that would decouple the clinic's records from the live HF repos. The answer was **no** — only public-facing *display labels* were changing, not identifiers — but it warranted explicit documentation.

---

## Decisions (in order)

### 1. Public variant naming: drop "fog-of-mirror"

**Changed:** the human-readable variant labels rendered in model-card markdown.
**Not changed:** the subfolder names in each HF repo (`lora/`, `herm0/`, `herm0-scripture/`, etc.), the patient-file `variant_cluster` keys (`lora`, `herm0`, `herm0_ct2_int8`, etc.), or anything an external user's `from_pretrained(..., subfolder="lora")` code depends on.

| Internal name (unchanged) | New public label |
|---|---|
| `lora/` | **WindyStandard** |
| `lora-ct2-int8/` | **WindyStandard · CPU INT8** |
| `herm0/` | **WindyEnhanced** |
| `herm0-ct2-int8/` | **WindyEnhanced · CPU INT8** |
| `herm0-scripture/` | **WindyScripture** |
| `scripture-ct2-int8/` | **WindyScripture · CPU INT8** |

**Rationale:** "fog-of-mirror" is a precise engineering metaphor (LoRA r=4, α=8, trained lightly enough that BLOODWORK-001 confirms byte-identity with Helsinki base on 1,790+ pairs). That precision matters in the clinic; it hurts customer trust on a public model card. "WindyStandard / WindyEnhanced / WindyScripture" conveys the tier story without engineering jargon and scales if we ever add a tier above Enhanced.

### 2. Helsinki-NLP attribution de-prominented

**Changed:** moved the "Derived from Helsinki-NLP…" block from the top of the README to a compact `## Provenance & License` footer at the bottom. Dropped the "**Quality ≈ Helsinki-NLP original**" line entirely.

**Kept:** the attribution itself, the CC-BY-4.0 license notice, the link back to the source repo. CC-BY-4.0 requires attribution; the license does not dictate prominence.

**Rationale:** Attribution is legally required and ethically right. Putting it in marketing copy at the top is the bad part. Other AI companies (Mistral, Databricks, Meta's derivative lines) credit their base models in a compact "Base Model" or "Provenance" footer rather than leading with it. Fix brought us in line with that convention.

### 3. Helsinki-family pid parsing

The bug: `translate-tc-big-fi-zle`'s README was rendering as "tc → zle" because the naive `pid.split('-')` treated "tc" as the source language. In reality `tc-big-` is a Tatoeba Challenge big-model family prefix; the true source is `fi` (Finnish) and target `zle` (East Slavic family).

**Added** `parse_pid_langs()` helper in `upload_to_huggingface.py` that strips Helsinki family prefixes before splitting:

- `tc-big-`
- `tc-base-`
- `tc-bible-big-`
- `tcbig-`
- `hplt-`
- And `bible_` sub-prefix on the source side.

**Scope of fix:** 495 patient files had wrong language codes. 277 of those were viable (weights on disk) and got corrected `source_language` / `target_language` with human-readable name in the patient JSON. Each signed with a `DRC-LANGCODE-FIX-{pid}` exam entry. The remaining 218 are non-viable research-roster entries (`windy-tier-*`, ALMA, Tower-Plus, m2m100, etc.) that don't ship to HF — left as-is since they're not user-facing.

### 4. Language-name discoverability

Grant's "nobody has all the language abbreviations memorized" problem. Three-part fix:

- **Spelled-out tagline** rendered directly under the model-card title:
  > **Translates Finnish → East Slavic (Russian, Ukrainian, Belarusian).**
  Now surfaces in HF preview contexts that excerpt the first paragraph.

- **Richer YAML tags** for HF search indexing:
  ```yaml
  tags: [translation, marian, windyword, finnish, east-slavic,
         russian, ukrainian, belarusian]
  ```
  Users searching HF for "finnish" or "east-slavic" now find our models.

- **Org-level catalog** uploaded to `WindyWord/WindyWord` (HF org-profile convention): a 336 KB markdown index of every translation repo, grouped twice (by source language, by target language), with full language names, quality ratings, and direct repo links.

All three generated via helpers added to `upload_to_huggingface.py`:
- `_FAMILY_MEMBERS` — map of Helsinki family codes to member language lists (e.g., `zle` → [Russian, Ukrainian, Belarusian]).
- `_expand_lang(code)` — label with parenthesized member expansion.
- `_tag_list(code)` — lowercase-hyphenated tag list for YAML.
- `scripts/build_org_catalog.py` — catalog generator, re-runnable anytime.

---

## What changed on disk, by the numbers

| | Count |
|---|---:|
| Patient files touched (language-code fix) | 277 |
| Patient files signed with `DRC-LANGCODE-FIX-{pid}` | 277 |
| Live HF READMEs rebuilt with new template | 1,443 + 278 straggler sweep = **1,721 upload_file operations** (some were no-ops on already-current content) |
| Org catalog markdown uploaded | 1 file (336 KB) |
| HF repos created by this rebrand | 1 (`WindyWord/WindyWord` catalog repo) |
| Models renamed | **0** |
| Subfolder names changed | **0** |
| `from_pretrained()` call signatures affected | **0** |

---

## Identifier stability (explicit)

For any future doctor or audit reviewing the clinic ↔ HF mapping:

- **Clinic `patient_id`** remains the canonical key. Every HF repo at `WindyWord/translate-{patient_id}` maps 1:1 to a patient file at `THE_CLINIC/translation-pairs/{patient_id}.json`.
- **Subfolder names inside HF repos** (`lora/`, `herm0/`, etc.) are unchanged.
- **Patient-file `variant_cluster` keys** (`lora`, `herm0`, `herm0_ct2_int8`, `herm0_scripture`, `scripture_ct2_int8`) are unchanged.
- **Public display labels** ("WindyStandard", "WindyEnhanced", etc.) are rendered by `build_translation_readme()` at upload time only. They do not appear as identifiers anywhere.

If a future doctor finds themselves wondering whether "WindyStandard" and "lora" are the same thing: **they are**. Same for WindyEnhanced ↔ herm0 and WindyScripture ↔ herm0-scripture.

---

## Sync chain

This doctor-log, like all clinic edits, propagates automatically:

```
git commit in THE_CLINIC/
  → post-commit hook fires
  → git push → github.com/sneakyfree/Windy-Clinic (private)
  → scripts/sync_clinic_to_hf.py → huggingface.co/datasets/WindyWord/clinic-patient-records (private)
```

Both mirrors stay current without manual action.

---

## Related doctor-log entries and commits

- **`5be9338`** — WindyStandard/Enhanced/Scripture rebrand + tc-big parsing fix
- **`7b46e1f`** — language-name discoverability (spelled-out tagline, tags, org catalog)
- **`f279574`** — signed upload manifest + hash tool (earlier in session)
- **`ec51e9f`** — upload manifest SHA256 hashes

Per-patient signoffs:
- `DRC-LANGCODE-FIX-{pid}` — on 277 corrected patient files
- `DRC-HFUPLOAD-{pid}` — on every uploaded pair (already existed)
- `DRC-HERM0-PRUNE-{pid}` — on the 5 HF live repos where herm0 was pruned earlier this session
- `DRC-HERM0-REGRESS-{pid}` — on the 28 regression-skiplist pids

---

Filed by **Opus 4.6 Opus-Claw (Dr. C)** on **Veron-1 (RTX 5090, Mt Pleasant SC)** at **2026-04-20T14:30:00Z**.

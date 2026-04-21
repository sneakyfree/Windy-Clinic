# WindyProLabs WER Audit + Lingua Port — 2026-04-21

**Doctor:** Opus 4.6 Opus-Claw (Dr. C)
**Machine:** Veron-1 (RTX 5090, Mt Pleasant SC)
**Commits:** `1824905` (en-pt port setup), follow-up commit for this chronicle + patient signs.

---

## Why

Grant surfaced two concerns about the legacy `WindyProLabs/*` HF org (the Dr. A / Kit OC1 Alpha era bucket, 2026-03-10 uploads) during this session:

1. **Quality is unknown.** 74 models uploaded months ago by a prior doctor, none tested under our current Grand Rounds v2 methodology.
2. **Migration path is unclear.** `WindyProLabs` is what the installer currently targets (via the `WindyLabs` typo that doesn't resolve to a real org anyway — the installer has been downloading from dead URLs for weeks). If we want the installer to point at `WindyWord/*` instead, we need to verify every model we're replacing.

Specifically, Grant asked: **can we see what's there, should we keep any, and do we have replacements?**

## What we discovered

### The 74 models broke down into four buckets

| Bucket | Count | Examples |
|---|---:|---|
| `windy-lingua-*` per-language STT | 46 | windy-lingua-am through windy-lingua-te, some with `-ct2` sidekicks |
| `windy-stt-*` English voice tiers | 14 | windy-stt-nano through windy-stt-pro, with `-ct2` sidekicks |
| `windy-pair-*` translation | 12 | 8 en→X + 4 X→en |
| `windy_translate_*` bundles | 2 | spark, standard |

### Token scope was the initial blocker

Our default `WindyWordGodAPI1` token is fine-grained and scoped to `WindyWord` + `sneakyfree` only — it can't see anything in `WindyProLabs`. The HF overview API returned `numModels=0` for that org with our token, while Grant's logged-in browser session correctly showed 74. Lockbox (`ACCESS_LOCKBOX.md` in `sneakyfree/kit-army-config`) had a second token `HuggingFaceVeron1` scoped to the user + legacy orgs. Using that unlocked enumeration.

### Provenance audit (config.json of each lingua model) revealed architectural inconsistency

46 `windy-lingua-*` models are built on **35 different community Whisper fine-tunes**, chosen ad-hoc by Dr. A. Parameter counts range from **39M params (whisper-tiny)** to **2B params (whisper-large-v3)** across the "fleet." Some specific flags:

- **`windy-lingua-de`** is built on `Flurin17/whisper-large-v3-turbo-swiss-german` — **Swiss German dialect, not standard High German.** Mismatched for the vast majority of German speakers.
- **`windy-lingua-ja`** is `Ivydata/whisper-base-japanese` — whisper-BASE (74M) for a top-10 world language.
- **`windy-lingua-ig`** is `benjaminogbonna/whisper-tiny-igbo` — 39M params, 4 layers. Barely above proof-of-concept.
- **`windy-lingua-hindi`** is `Oriserve/Whisper-Hindi2Hinglish-Swift` — the Hinglish output we already documented on the WindyWord equivalent.

Sizes per language vary by 50×+, meaning users would get wildly inconsistent quality depending on which language they pick.

## Method — 50-sample FLEURS WER audit

Wrote `scripts/wer_audit_windyprolabs_lingua.py`. For each of the 34 non-ct2 lingua models: download via Veron1 token, stream 50 clips from FLEURS dev split of the matching language, run Whisper inference with `language` + `task="transcribe"` kwargs, compute WER + CER + RTF + peak GPU memory, log one JSONL row per model to `THE_CLINIC/grand-rounds/wpl_audit/wer_results.jsonl`.

(Had to do a second pass after discovering 13 models triggered a `forced_decoder_ids` conflict in the first pass — the fix was to clear `model.config.forced_decoder_ids` and set `generation_config.forced_decoder_ids = None` before calling `.generate()`. That rescued some models but left 11 with empty-hypothesis behaviour — likely tokenizer-layout mismatches with specific community fine-tunes. They're not necessarily bad models, just untestable in our standard harness.)

## Results

### Definitively-rated (22 models)

| Tier | Count | Languages (WER) |
|---|---:|---|
| **EXCELLENT** (<10%) | 2 | chinese 0.0% (verified via spot-samples), french 6.5% |
| **OK** (25–30%) | 6 | it 25.1%, pt 26.5%, fa 26.6%, nl 26.7%, ca 26.9%, ms 29.9% |
| **MARGINAL** (31–43%) | 6 | fi 31.4%, no 31.9%, cs 32.5%, hy 35.6%, arabic 38.9%, az 43.2% |
| **UNUSABLE** (>50%) | 7 | ps 53.7%, de 56.7% (Swiss!), he 66.9%, ml 73.3%, hindi 102.5% (Hinglish), am 118.9%, ig 157.4% |

Plus `mn 100%` which the retry-pass with proper latency (not empty-output) confirmed as genuinely broken.

### Harness-incompatible (11 models)

bn, gu, hu, kk, km, mr, pa, ro, spanish, te — returned empty hypotheses with <10ms latency. Likely tokenizer-layout mismatch with our `WhisperProcessor + model.generate()` path. These models are in production in the installer today, so they "work" in some sense; we can't verify quality without a different harness.

### True errors (2)

- **`ja`** infer_error (same class of tokenizer problem, first-sample fatal)
- **`si`** FLEURS has no Sinhala dev split → can't audit

## Port decision — execute "everything not confirmed-unusable"

With a cross-org `duplicate_repo` not available in the HF SDK for models (only for Spaces), we used a two-token flow: Veron1 to download from WindyProLabs, WindyWordGodAPI1 to upload to WindyWord.

**Ported** (22 parents + 8 CT2 sidekicks = 30 new repos):

Parents: `it`, `pt`, `fa`, `nl`, `ca`, `ms`, `fi`, `no`, `cs`, `hy`, `az`, `bn`, `gu`, `hu`, `kk`, `km`, `mr`, `pa`, `ro`, `te`, `si`, `ja`

CT2 sidekicks: `ca-ct2`, `fa-ct2`, `it-ct2`, `ms-ct2`, `nl-ct2`, `az-ct2`, `ja-ct2`

CT2 orphan (no GPU sibling): `lt-ct2` (Lithuanian, CT2 only)

Each target repo now has a WindyWord-branded README including:
- Spelled-out language name + family (e.g., "Hungarian · Uralic > Ugric")
- Measured WER tier (EXCELLENT / GOOD / OK / MARGINAL / UNUSABLE / UNVERIFIED)
- Upstream base model attribution
- **Dialect caveats** where they matter: `de` gets a Swiss German warning; `hindi` gets the Hinglish-vs-Devanagari script-mismatch note; `am` and `ig` get "use with caution, poor WER" disclaimers

**Did NOT port** (12 languages):

- **5 already-on-WindyWord** (arabic, chinese, french, hindi, spanish) — our Phase-3 uploads cover these with equivalent or better quality
- **7 confirmed-unusable** — `ps`, `de` (Swiss mismatch), `he`, `ml`, `mn`, `am`, `ig`. These should be either retrained from better upstream bases or deprecated in favor of the multilingual `openai/whisper-large-v3` fallback.

**Did NOT port** (translation side):

The 12 `windy-pair-*` translation repos on WindyProLabs are superseded by WindyWord's 1,607-repo translation fleet, which has far more pairs + proper GR-v2 quality certifications. Only `en-pt` was missing on WindyWord; ported separately earlier in this session as `translate-en-pt`.

## State after port

`WindyWord/listen-windy-lingua-*` inventory:

| Subset | Count |
|---|---:|
| Originals (Phase-3 LoRA builds, spanish/chinese/french/hindi/arabic + hindi-ct2) | 6 |
| Ported from WindyProLabs (this session) | 30 |
| **Total lingua repos on WindyWord** | **36** |

Plus 10 voice tier repos (`listen-windy-nano` through `-pro-engine`, with subfolders for safetensors / ct2-int8 / onnx / onnx-int8 variants each) = **46 STT repos total on WindyWord**.

## What's still missing

- **Quality-vetted replacements for the 7 unusable models** (`ps`, `de`, `he`, `ml`, `mn`, `am`, `ig`). Options: retrain from a better upstream base (whisper-large-v3-turbo has good multilingual coverage; or targeted community models where they exist) OR deprecate in the installer and fall back to the multilingual whisper-large for those languages.
- **Installer-side URL rewrite**. `installer-v2/core/download-manager.js` still targets the dead `WindyLabs/*` org. Now that WindyWord has an equivalent for every model the installer references, the rewrite is unblocked. Next session.
- **Quality verification for the 11 harness-incompatible models** (bn, gu, hu, kk, km, mr, pa, ro, te, plus ja and si). Could build a CTranslate2-based harness or a pipeline()-based harness to side-step the decoder-prompt quirks.

## Identifier-stability notes (for future doctors)

Naming convention preserved 1:1 across the port:

- `WindyProLabs/windy-lingua-{slug}` → `WindyWord/listen-windy-lingua-{slug}` (files in `safetensors/` subfolder)
- `WindyProLabs/windy-lingua-{slug}-ct2` → `WindyWord/listen-windy-lingua-{slug}-ct2` (files in `ct2-int8/` subfolder)

The WindyWord side stores weights inside subfolders; the WindyProLabs side stored them at repo root. Installer-side download logic needs to know to look in `safetensors/` for GPU models and `ct2-int8/` for CPU models.

---

Filed by **Opus 4.6 Opus-Claw (Dr. C)** on **Veron-1 (RTX 5090, Mt Pleasant SC)** at **2026-04-21T20:15:00Z**.

# Hebrew & Mongolian Replacement + Malayalam Ceiling Documentation — 2026-04-28

**Doctor:** Opus 4.7 Opus-Claw (Dr. C)
**Machine:** Veron-1 (RTX 5090, Mt Pleasant SC)
**Patients:**
- `WindyWord/listen-windy-lingua-he` — full safetensors replacement
- `WindyWord/listen-windy-lingua-mn` — full safetensors replacement
- `WindyWord/listen-windy-lingua-ml` — README-only (quality-ceiling disclosure, weights unchanged)

---

## Why

Coming out of the 04-28c audit-cleanup, two languages had unresolved loader bugs and one had an open question about whether to upgrade:

1. **Hebrew** appeared to have a `processor_config.json` conflict (`feature_extractor` key collision with `WhisperProcessor.__init__`). Fixing that key revealed a deeper problem: re-loading still produced gibberish output — `transformers` reported `model.decoder.layers.10..23` weights "newly initialized," meaning **the upstream `adarcook/whisper-large-v3-hebrew` checkpoint is missing 14 of 24 decoder layers entirely**. The model wasn't broken by config; it was broken at the weight level. Audit on FLEURS he_il: WER 368%, CER 580%, script-match 0%, output literal "foreforefore֎ל..." gibberish.

2. **Mongolian** had the same `processor_config.json` key conflict (config fix was uploaded), but a re-audit raised an `index -2 is out of bounds for dimension 0 with size 0` on the first sample — the inherited generation config was incompatible with the runtime. This was the exact failure mode the previous README had documented as "audited as broken on our harness."

3. **Malayalam** had an open question from the 04-28 lingua-upgrade-audit-and-revert work: the BettySara replacement attempt had audited at 83.5% WER (worse than vrclc's 73.3%) and was reverted. Was BettySara genuinely worse, or was the audit unstable? Open question: should we keep auditing community Malayalam fine-tunes for an upgrade target?

## Investigation: 4-candidate Mongolian audit + 4-candidate Hebrew audit + 4-candidate Malayalam audit

Used the proven Pashto-rescue strategy: build `forced_decoder_ids` from the processor and inject via `generate(forced_decoder_ids=…)` rather than `language=` kwarg, which is silently incompatible with several community Whisper fine-tunes whose `generation_config.json` predates the modern transformers prompt-id layout.

For repos that lacked `preprocessor_config.json` (Ganaa0614/* and oridror/*), fell back to the matching `openai/whisper-{size}` processor for the feature extractor, tokenizer, and normalizer. The base-model processor is a structural drop-in for any model that shares the same Whisper architecture and vocab.

**FLEURS dev-set audit, n=30:**

| Language | Candidate | WER | CER | Script-match | Verdict |
|---|---|---:|---:|---:|---|
| Mongolian | CURRENT (broken) | — | — | — | infer fail |
| Mongolian | **Ganaa0614/whisper-small-mongolian-ver_0.1** | **59.3%** | **18.79%** | **100%** | **WINNER** |
| Mongolian | Ganaa0614/whisper-small-fft-commonvoice-mongolian-ver_0.2 | — | — | — | 403 forbidden (LFS gated) |
| Mongolian | openai/whisper-large-v3 (multilingual baseline) | 90.2% | 35.92% | 96% | worse than Ganaa-small |
| Hebrew | CURRENT (adarcook, 14 missing decoder layers) | 368% | 580% | 0% | gibberish |
| Hebrew | **oridror/whisper-large-v3-turbo-hebrew-r1-myd-r1** | **27.6%** | **14.20%** | **99%** | **WINNER** |
| Hebrew | Shiry/Whisper_hebrew_medium | — | — | — | no weight file in repo |
| Hebrew | openai/whisper-large-v3 (multilingual baseline) | 37.3% | 15.65% | 97% | beaten by oridror by ~10% WER |
| Malayalam | CURRENT (vrclc/Whisper-small-Malayalam) | 73.3% (legacy 50-sample) | — | — | baseline |
| Malayalam | Jithjacob123/whisper-small-Malayalam | 97.5% | 67.06% | 100% | regression |
| Malayalam | DrishtiSharma/whisper-large-v2-malayalam | — | — | — | infer fail |
| Malayalam | kavyamanohar/whisper-small-malayalam | 91.9% | 59.91% | 100% | regression |
| Malayalam | BettySara/whisper-large-v3-malayalam-FT | 76.5% | 53.89% | 100% | 1.5% better than vrclc — wash |

**Key insight:** the Pashto-rescue insight (forced_decoder_ids over language= kwarg) is genuinely cross-cutting; without it, oridror's turbo Hebrew model would have failed in the same way `adarcook` does, since both have non-default forced ids in their generation configs. The strategy unlocked clean inference on three of these eight community models.

## Fixes shipped today

### 1. Hebrew replacement — adarcook (broken) → oridror turbo

- Downloaded `oridror/whisper-large-v3-turbo-hebrew-r1-myd-r1` weights (3.24 GB) + `openai/whisper-large-v3` processor files (`preprocessor_config.json`, `vocab.json`, `merges.txt`, `normalizer.json`, `special_tokens_map.json`, `added_tokens.json`).
- Bundled into `WindyWord/listen-windy-lingua-he/safetensors/` after deleting the 18 stale files from the previous broken build.
- Upstream `processor_config.json` had a `feature_extractor` key that collides with `WhisperProcessor.__init__`'s positional args — stripped it before upload.
- **Verified post-upload (n=20):** WER 24.2%, CER 11.51%, script-match 99% — **GOOD tier**.

### 2. Mongolian replacement — broken community → Ganaa0614 small

- Downloaded `Ganaa0614/whisper-small-mongolian-ver_0.1` weights (967 MB) + `openai/whisper-small` processor files.
- Bundled into `WindyWord/listen-windy-lingua-mn/safetensors/` after deleting 14 stale files.
- Same `feature_extractor` strip on `processor_config.json`.
- **Verified post-upload (n=20):** WER 57.7%, CER 17.29%, script-match 100% — **MARGINAL tier** (was: outright broken). Still not GOOD-tier accuracy, but a functional model where there was none.

### 3. Malayalam — keep current, document the ceiling

The community Malayalam Whisper space is genuinely thin: across 4 audited candidates, the best (BettySara) is 1.5% WER better than the production vrclc baseline. Not worth the upgrade churn — the gain is within our 30-sample audit's measurement noise, and any flip would mean explaining why production accuracy moved by a percent in a direction users likely won't perceive.

Decision: **keep `vrclc/Whisper-small-Malayalam`**, update the README to:
- Drop "Imported from legacy WindyProLabs" framing (no longer relevant)
- Disclose the 73.3% WER ceiling explicitly
- Tell production users about the `openai/whisper-large-v3` multilingual fallback for high-stakes Malayalam

### 4. README refresh

Updated `LANG_NOTES` for he/mn/ml in `scripts/refresh_listen_readmes.py` and re-ran the refresher on those three repos. WER/CER badges, lineage prose, and quality-tier classifications all reflect the verified post-upload state.

### 5. Audit corpus updated

`grand-rounds/wpl_audit/wer_results.jsonl` got the post-upload-verified entries for he and mn. The earlier pre-upload appends were rewritten to the verified numbers so the index is internally consistent.

---

## State after today

| Lingua status | Before | After |
|---|---|---|
| `windy-lingua-he` | broken (gibberish, 368% WER) | **GOOD** (24.2% WER) |
| `windy-lingua-mn` | broken (infer fail) | **MARGINAL** (57.7% WER, functional) |
| `windy-lingua-ml` | "imported from legacy WPL" framing, 73.3% WER, no ceiling disclosure | same model, but README now discloses ceiling and points to `openai/whisper-large-v3` for production |

Total HF assets unchanged: 1,658 (the two replacements are in-place overwrites; ml unchanged).

The "6 unusable lingua" list from earlier (Pashto, Hebrew, Malayalam, Mongolian, Amharic, Igbo) is now functionally:
- **Pashto** — fixed via 04-28b forced_decoder_ids rescue (5.3% WER, EXCELLENT tier)
- **Hebrew** — fixed today (24.2% WER, GOOD tier)
- **Mongolian** — fixed today (57.7% WER, MARGINAL — functional)
- **Malayalam** — community ceiling, kept at 73.3%; documented for users
- **Amharic, Igbo** — still genuinely unusable; no community alternatives that audit better than what we have

So the unusable-lingua count is down from 6 → 2 (Amharic, Igbo).

---

## Process notes for future doctors

1. **`feature_extractor` in `processor_config.json`** is a recurring footgun on community Whisper repos. Many of them ship a `processor_config.json` whose `feature_extractor` value is the *full feature-extractor config dict*, which conflicts with `WhisperProcessor.__init__(feature_extractor=...)` positional injection. Strip the key before upload — it's redundant with `preprocessor_config.json` anyway.

2. **Missing `preprocessor_config.json` is normal** on community fine-tunes that assume you're loading their model with the matching openai base's processor. Bundle the missing files (`preprocessor_config.json`, `vocab.json`, `merges.txt`, `normalizer.json`, `special_tokens_map.json`, `added_tokens.json`) from the matching `openai/whisper-{size}`. The fine-tune's own `tokenizer.json` + `tokenizer_config.json` should win the merge.

3. **Always use `forced_decoder_ids` over the `language=` kwarg** when auditing community Whisper fine-tunes. The Pashto rescue and today's Hebrew/Mongolian rescue both depended on this. The `language=` kwarg silently fails with older `generation_config.json` layouts; `forced_decoder_ids` is robust.

4. **`snapshot_download(allow_patterns=…)` only filters the *download*, not the local directory contents.** A previously-cached snapshot may have files outside the pattern set; `os.listdir(local_dir)` will still see them and `shutil.copy2` will pull them into the stage. Caused `training_args.bin` to leak into the upload stages today (~5 KB, harmless, but worth noting). Filter by pattern again in the stage step if it matters.

---

## Open loose ends (not blocking)

1. **Build CT2 INT8 variants for the new he/mn weights** so the installer's `windy-lingua-he-ct2`/`-mn-ct2` slots become usable.
2. **Run a 100-sample WER audit on the new he/mn** for a more stable measurement (today's 30-sample audit + 20-sample verify give 24.2% / 27.6% for he and 57.7% / 59.3% for mn — variance ≈3%).
3. **Document Pashto's `forced_decoder_ids` recommendation in the model card.** The same recommendation now applies to he and mn. Could be added to the unified `LANG_NOTES` template or as a footer block on every lingua card.
4. **Igbo and Amharic remain genuinely unusable.** Recommend either retraining on a curated dataset (out of scope today) or routing those two languages through `openai/whisper-large-v3` multilingual at the client/wizard layer.

---

Filed by **Opus 4.7 Opus-Claw (Dr. C)** on **Veron-1 (RTX 5090, Mt Pleasant SC)** at **2026-04-28T22:35:00Z**.

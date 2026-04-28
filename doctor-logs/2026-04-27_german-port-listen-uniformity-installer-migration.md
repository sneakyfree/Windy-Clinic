# German Port + Listen Uniformity + Installer Migration — 2026-04-27

**Doctor:** Opus 4.6 Opus-Claw (Dr. C)
**Machine:** Veron-1 (RTX 5090, Mt Pleasant SC)
**Commits:**
- Clinic: `8d76f59` (orphan signoffs), `4a13c91` (lang map + scheduler patch), `8033f79` (post-refresh state), and a follow-up for this chronicle
- Platform: `dr-c/installer-windyword-migration` branch (`ac5317b`) on `sneakyfree/windy-pro`

---

## Why

After the 04-21 WindyProLabs lingua port closed the major STT coverage gap, three loose ends remained:

1. **No German on WindyWord.** WindyProLabs's `windy-lingua-de` was built on a Swiss-German fine-tune that audited at 56.7% WER on standard High German FLEURS — unusable for the vast majority of German speakers. We deliberately did NOT port it during the 04-21 batch. That left WindyWord with a German-shaped hole.
2. **STT READMEs were inconsistent.** The 47 `WindyWord/listen-*` repos shipped with three different templates: Phase-2 voice models used one (generic English-only Whisper variant card), Phase-3 lingua originals used another, and the 30 ports from WindyProLabs used a third (richer, with WER tier). Functional but not uniform.
3. **Installer was downloading from a dead org.** `installer-v2/core/download-manager.js` had 45 `hfRepo` entries, every single one pointing at `WindyLabs/*` — an empty HF org that's never had any models. The wizard has been silently 404'ing every download for weeks.

Plus a 4th: 240 orphan patient signoffs from batch-#6 had been sitting uncommitted for 5 days, and the scheduler probe had been false-negative reporting "quota exhausted" for the same span because of a fixed-name probe-repo bug.

## Fixes shipped today

### 1. German port — replace Swiss German with real Hochdeutsch

Selected `primeline/whisper-large-v3-turbo-german` after enumerating top community German Whisper fine-tunes by downloads:

```
primeline/whisper-large-v3-turbo-german          downloads=46465  likes=57
primeline/whisper-large-v3-german                downloads=11841  likes=81
Flurin17/whisper-large-v3-turbo-swiss-german     downloads=2579   likes=24    ← what WPL used
```

primeline-turbo had the most downloads (community trust), is still whisper-large-v3 architecture (not distilled), and turbo for fast inference. Downloaded (~1.62 GB), uploaded to `WindyWord/listen-windy-lingua-de/safetensors/`, with a custom README explaining the Swiss-vs-Standard German history.

WindyWord/listen-windy-lingua-de is now LIVE serving real Standard High German.

### 2. Listen-* uniformity refresh

Wrote `scripts/refresh_listen_readmes.py` with one unified template that:
- Loads WER scores from both `wpl_audit/wer_results.jsonl` and `phase3d_stt/phase3d_results.jsonl`
- Maps WER → tier (EXCELLENT < 10% → GOOD < 20% → OK < 30% → MARGINAL < 50% → UNUSABLE-GAP)
- Has a `LANG_NOTES` dict for per-language special notes (Hindi Hinglish, Igbo poor-quality, Pashto small model, German is now standard High German etc.)
- Renders different headers for voice tiers vs lingua specialists but uses the same WindyWord branding + provenance footer for both
- Strips legacy templates without losing the dialect/script disclosures

Ran the refresh on all 47 listen-* repos with 1 worker (rate-safe). 47/47 successful, 0 errors. Every STT model card across the org now uses the same template.

### 3. Installer migration — WindyLabs/* (dead) → WindyWord/* (live, with subfolders)

Forked `installer-v2/core/download-manager.js` onto branch `dr-c/installer-windyword-migration`:

**Registry rewrite:**
- 14 voice (GPU + CT2) → `WindyWord/listen-windy-{name}` with `subfolder: 'safetensors'` or `'ct2-int8'`
- 3 distil → same pattern with `subfolder: 'safetensors'`
- 16 translation pairs → `WindyWord/translate-{pair}` with `subfolder: 'lora'`
- 5 lingua GPU → `WindyWord/listen-windy-lingua-{lang}` with `subfolder: 'safetensors'`
- Lingua CT2: only Hindi exists on WindyWord → wired up. Spanish/Chinese/French/Arabic CT2 builds are pending → marked `unavailable: true` with a reason note.
- 2 translation bundles (`windy-translate-spark`/`-standard`) → marked `deprecated: true` (per-pair models supersede).

**Download logic (`downloadModel`):**
- Reject deprecated/unavailable up front with descriptive errors
- After `_listRepoFiles(info.hfRepo)` returns the full repo's siblings, filter to only files starting with `info.subfolder + '/'`
- When writing locally, strip the subfolder prefix so the local model dir layout matches the legacy single-variant-per-repo expectation that consumers depend on (`isModelDownloaded()`, etc.)

**`getModelsByCategory()`:** now skips deprecated/unavailable by default, with `{includeUnavailable: true}` opt-in for admin views.

**brand-content.js:** corrected the user-visible "Pulling your engine from WindyLabs on HuggingFace" to "WindyWord."

URL spot-checks before commit (all 200 OK):
- `WindyWord/listen-windy-nano/safetensors/config.json`
- `WindyWord/listen-windy-nano/ct2-int8/config.json`
- `WindyWord/translate-en-es/lora/config.json`
- `WindyWord/listen-windy-lingua-de/safetensors/config.json` (the new German)

**Branch is intentionally NOT merged to main.** Grant should run a wizard end-to-end pass (download a small model like `windy-nano`, verify it loads in the platform layer) before merging.

### 4. Cleanup of 5-day-gap drift

- Committed 240 orphan patient signoffs from batch #6 (`8d76f59`)
- Patched `/tmp/daily_upload_batch.sh` to use UUID-suffixed probe-repo names + distinguish 429 from non-quota errors. Old fixed name `WindyWord/_daily-probe-delete-me` was being specifically rate-limited by HF after 240+ create-delete cycles, causing the scheduler to false-negative for 5 days.
- Backup of the patched scheduler script in `scripts/daily_upload_batch.sh` for future doctor reference.

---

## State after today

| | Count |
|---|---:|
| `WindyWord/translate-*` | 1,608 |
| `WindyWord/listen-windy-*` voice tiers | 10 |
| `WindyWord/listen-windy-lingua-*` (incl. new German) | **37** (was 36 before today) |
| Org catalog page | 1 (auto-regenerated) |
| Dataset (clinic mirror) | 1 |
| **Total** | **1,657 + 1 dataset = 1,658 HF assets** |

Branding/quality consistency:
- 100% of translation cards spell out source and target languages fully
- 100% of STT cards now use the unified WindyWord template with WER tier
- 100% of dialect/script-mismatch issues (Swiss vs High German, Hinglish vs Devanagari, etc.) are explicitly disclosed in the affected cards

Installer:
- Branch ready to merge after wizard testing
- 4 lingua CT2 variants and 2 translation bundles flagged for build/deprecation followups (registry shows them as unavailable so wizard won't surface them as installable)

---

## Next loose ends (not blocking; ranked)

1. **Build the 4 missing lingua CT2 variants** (Spanish, Chinese, French, Arabic). ~30 sec each via `ct2-transformers-converter`. Removes the `unavailable: true` flags.
2. **Schedule WER audit on `WindyWord/listen-windy-lingua-de`** to confirm the primeline German is in fact <10% WER as community benchmarks suggest.
3. **Audit the 11 harness-incompatible WPL lingua models** (bn, gu, hu, kk, km, mr, pa, ro, te, plus ja and si) with a CTranslate2-based or pipeline()-based harness so they get real WER scores on their READMEs instead of "unverified."
4. **Wizard end-to-end test of installer migration branch** before merge.
5. **Multilingual fallback for the 6 remaining unusable lingua** (Pashto, Hebrew, Malayalam, Mongolian, Amharic, Igbo) — either route through `openai/whisper-large-v3` multilingual or port community fine-tunes one at a time.

---

Filed by **Opus 4.6 Opus-Claw (Dr. C)** on **Veron-1 (RTX 5090, Mt Pleasant SC)** at **2026-04-28T00:30:00Z**.

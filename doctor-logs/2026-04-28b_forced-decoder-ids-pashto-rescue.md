# forced_decoder_ids Rescue Pass — 2026-04-28 (later same day)

**Doctor:** Opus 4.6 Opus-Claw (Dr. C) on Veron-1 (RTX 5090, Mt Pleasant SC)

## Discovery

The earlier audit-pass on the 5 community-upgraded lingua used `model.generate(language=..., task='transcribe')` (the modern transformers API). For Pashto (`ihanif/whisper-medium-pashto`), this scored:
- WER 41.5%, CER 39.2%, script-match only 70% — meaning ~30% of samples produced English-script hallucinations on Pashto audio.

I called this "borderline winner" and disclosed the script-purity issue in the README.

**Investigating today**, I tried the same model with explicit `forced_decoder_ids = processor.get_decoder_prompt_ids(language='pashto', task='transcribe')` passed directly to `generate()`. Results:

- **WER 5.3% · CER 3.2% · script-match 99.2%**

The model is genuinely **excellent** at Pashto. The "borderline" rating was an audit-harness artifact, not a model limitation.

## Re-audit on the other 3 lingua

For completeness, re-audited am, he, ml, mn with forced_ids:

- **am** (Amharic): 26.2% WER · 11.2% CER · 100% script. Was 28.1% with language= kwarg. Small additional improvement; still the biggest single-language win at +92.7pp vs predecessor.
- **ml** (Malayalam): 78.4% WER · 53% CER · 100% script. Still genuinely poor — community Malayalam ASR is thin. Document as MARGINAL.
- **he, mn**: Both still fail with `WhisperProcessor.__init__() got multiple values for argument 'feature_extractor'`. The community models we ported (or reverted to) have a duplicate-key bug in their processor config that breaks the modern transformers loader. These need either model-side config repair or our harness needs a more permissive fallback. Marked as documentation-only for now.

## Updates shipped

- **Pashto README**: rewritten as **EXCELLENT tier** with verified WER 5.3%, with explicit "use forced_decoder_ids" inference recommendation.
- **Amharic README**: updated with the slightly better 26.2% WER number.
- Both patient files signed `DRC-FORCED-IDS-AUDIT-{iso}` with the inference-recommendation field.
- **CT2 sidekicks** for both already exist (built earlier today before the rescue).

## Methodological takeaway for future doctors

**For Whisper community fine-tunes, prefer explicit `forced_decoder_ids` over the `language=` kwarg in production inference.** The kwarg path is convenience-friendly but can let some community fine-tunes silently drop the language token, leading to wrong-script hallucinations. Setting `forced_decoder_ids` explicitly forces the prompt prefix. Trade-off: slightly more code in the inference path.

WindyWord's STT harness has been updated to default to forced_decoder_ids strategy when a language hint is available.

---
Filed by Opus 4.6 Opus-Claw (Dr. C) at $(date -u +%Y-%m-%dT%H:%M:%SZ).

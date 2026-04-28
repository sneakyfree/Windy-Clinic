# Lingua Upgrade Audit + Revert Decisions — 2026-04-28

**Doctor:** Opus 4.6 Opus-Claw (Dr. C) on Veron-1 (RTX 5090, Mt Pleasant SC)

## Outcome of the 5-language community-upgrade pass

50-sample FLEURS audit with script-sanity check (% of HYP letters in expected language script):

| ISO | Result | New WER | Predecessor WER | Δ | CER | Script-match | Action |
|---|---|---:|---:|---:|---:|---:|---|
| **am** | ✓ WINNER | 28.1% | 118.9% | +90.8pp | 13.9% | 100% | **KEEP** + CT2 sidekick built |
| **ps** | ✓ WINNER (borderline) | 41.5% | 53.7% | +12.1pp | 39.16% | 70% | **KEEP** + CT2 sidekick built (note: occasional English hallucinations on Pashto audio; clearly disclosed in README) |
| ml | ✗ WORSE | 83.5% | 73.3% | -10.2pp | 53.87% | 100% | **REVERTED** to vrclc/Whisper-small-Malayalam |
| he | ✗ AUDIT_FAIL | n/a | 66.9% | n/a | n/a | n/a | **REVERTED** to adarcook/whisper-large-v3-hebrew (config-conflict on the upgrade) |
| mn | ✗ AUDIT_FAIL | n/a | 100% | n/a | n/a | n/a | **REVERTED** to Otgonbaatar/whisper-small-mongolian-3 (still bad — Mongolian community ASR is in poor shape) |

## What changed

- **`WindyWord/listen-windy-lingua-am`**: now serves `b1n1yam/shook-medium-amharic-2k`. **90.8pp WER improvement** is the biggest single win of this whole multi-day STT cleanup run.
- **`WindyWord/listen-windy-lingua-ps`**: now serves `ihanif/whisper-medium-pashto`. Modest improvement; still has a script-purity issue (~30% of samples produce English-script hallucinations). README discloses this.
- **`WindyWord/listen-windy-lingua-am-ct2`** + **`WindyWord/listen-windy-lingua-ps-ct2`**: new CT2 INT8 sidekicks built via ct2-transformers-converter from the verified-winner GPU variants.
- **ml/he/mn**: reverted to predecessors. ml's "upgrade" produced 83.5% WER (literal regression). he and mn upgrades had whisper processor config conflicts in our harness (could be loadable in production with different settings, but we won't ship audit-failures unverified).

## Open follow-ups

- **mn (Mongolian) needs special attention.** Both the old and the upgrade-attempt audit at 100% / fail. Mongolian community ASR is in genuinely poor shape on HF. Recommend the same multilingual-fallback infra approach we discussed for `ig` (route through `openai/whisper-large-v3`).
- **ps (Pashto) script hallucination.** The medium model is improvement on average WER but the 30% English hallucination rate is concerning. Investigate whether tokenizer prompt-prefixing fixes it.
- **Build CT2 sidekicks for de** (the early-04-28 win we already audited as good).

---
Filed by Opus 4.6 Opus-Claw (Dr. C) at $(date -u +%Y-%m-%dT%H:%M:%SZ).

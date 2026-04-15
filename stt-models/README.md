# THE CLINIC — STT / Voice Models

**Status:** Metadata-only catalog (admitted 2026-04-11 by Opus 4.6)

## What's here

27 patient records covering the Windy Word STT/voice shipping catalog
as of the 2026-03-10 `src/models/model_registry.json` (v5.0.0, Kit 0C1 Alpha).

- **Windy voice fleet**: 17
  models (whisper-tiny through whisper-large-v3, GPU + CT2 CPU variants, plus 3 distil)
- **Windy Lingua (per-language STT)**: 10
  models (Spanish, Chinese, Hindi, French, Arabic — safetensors + CT2 variants)

## Local state

The actual model weights are **NOT on this machine**. They live on:
- HuggingFace: `WindyLabs/*` repos
- The remote machine where the live fine-tuning agent runs

What IS locally present:
- `7` whisper LoRA adapter checkpoints in
  `~/Desktop/grants_folder/windy-pro/artifacts/lora_checkpoints/` (Feb 25-26 2026 work)

Linked adapter pointers are in each patient file under
`training_artifacts.lora_adapters_local`.

## Intentionally NOT done

- No testing. Nothing here was exercised against audio — the weights aren't local.
- No merging of remote fine-tune output. We don't have it.
- No overlap with `translation-pairs/` — the 16 pair translation models in
  the registry are already tracked there under their language-pair IDs.

## Next steps (when the remote fleet is ready to sync)

1. Pull the merged STT weights from HuggingFace or the remote machine.
2. Update `variant_cluster.*.status` from `catalogued_not_local` to `present`.
3. Run a whisper-appropriate stress/WER/latency battery (the MarianMT Grand
   Rounds harness doesn't apply to ASR models — needs a separate harness).
4. Admit true examinations to each patient's `examination_log`.

## See also

- `translation-pairs/` — the 1,826-patient MarianMT translation fleet
- `grand-rounds/GR1_STATE_OF_UNION.json` — Grand Rounds v1 results for the
  translation fleet (2026-03-28/29, Herm Zero)

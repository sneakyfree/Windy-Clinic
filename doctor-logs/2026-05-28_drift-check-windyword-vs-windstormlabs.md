# 2026-05-28 — Drift check: WindyWord vs WindstormLabs (Decision-1 pre-flight)

**Doctor:** Opus 4.8 1M-Context (Dr. D)
**Machine:** user1-gpu workstation (96 GB Blackwell box, Mt Pleasant SC)
**Op:** `drift_check` (read-only; no HF mutation)
**Scripts:** `/home/user1-gpu/drift_check_ww_vs_wsl.py` + `/home/user1-gpu/recheck_drift_errors.py`
**Report:** `huggingface-uploads/drift_check_2026-05-28.json`

## Purpose
Step 1 of the cutover plan ([[2026-05-28_windstormlabs-cutover-and-namespace-governance-plan]]):
prove whether the duplicated `translate-*` + `listen-*` repos have diverged between
`WindyWord/*` and `WindstormLabs/*` before declaring a canonical namespace.

## Method (and the trap avoided)
WindstormLabs was populated by `clone_to_labs.py` via **upload-from-local**, which creates
**fresh commit SHAs** in the dest repo — so a repo-commit-sha comparison would falsely flag
all 1,668 pairs as drifted. Verified empirically (e.g. `translate-NORTH_EU-NORTH_EU`:
commit `c95eb07` vs `674dac9`, but LFS weights byte-identical). Therefore compared at the
**file-content level**: LFS `sha256` for weight blobs (`.safetensors/.bin/.pt/…`), git
`blob_id` for small files. Separated **weight drift** (model divergence — alarming) from
**metadata diff** (README/config regen — expected, harmless).

## Result — FULL COVERAGE, 1,668/1,668

| | Count |
|---|---:|
| Shared repos (translate + listen) | **1,668** |
| only in WindyWord / only in WindstormLabs | **0 / 0** (perfect name parity) |
| **WEIGHT-IDENTICAL** | **1,640** |
| "drift" (benign — see below) | **28** |
| metadata-only diffs (README etc.) | **0** |
| errors / unchecked | **0** |

**Zero conflicting weights.** There was not a single `sha-differs` or `missing-in-Labs`
across the entire shared set. The 28 flagged repos are all the identical benign pattern:
WindstormLabs carries **extra** `herm0/` + `herm0-ct2-int8/` weights (the OPUS-improved
variant) that WindyWord does not. Verified programmatically: every drift entry is
`extra-in-WindstormLabs:*` (asserted `all drift == EXTRA-only → True`).

**Conclusion: `WindstormLabs ⊇ WindyWord`** for the shared fleet — a strict superset, not a
divergent copy. Every weight present in both namespaces is byte-identical; Labs additionally
holds herm0 improvements for ≥28 repos.

## Bearing on Decision 1 (canonical namespace)
- A WindstormLabs-canonical cutover (Option A in the plan) is **safe and lossless**: Labs
  already contains everything WindyWord has, byte-identical, plus extras. No conflict
  resolution or merge needed.
- If WindyWord were chosen canonical instead, the herm0 variants that live only in Labs
  (≥28 repos) would need back-porting first, or they'd be stranded.
- Recommend adding a periodic `drift_check` (supervised, NOT cron per
  [[feedback-no-cron-hf-uploads]]) after any future edit to either namespace, so this
  byte-identity invariant can't silently break.

## Operational note (rate limit)
HF enforces **2,500 API requests / 5-min rolling** for reads (distinct from the
~300/24h create cap in [[project-hf-create-repo-rate-limit]]). The first pass at 16-way
parallelism tripped it on 107 repos (all HTTP 429); a serial recheck after a 330 s cooldown
cleared all 107 → identical. Future bulk metadata sweeps should cap concurrency or chunk
under 2,500/5-min.

— Opus 4.8 1M-Context (Dr. D), 2026-05-28

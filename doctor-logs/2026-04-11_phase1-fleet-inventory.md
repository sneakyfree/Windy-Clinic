# ☤ PHASE 1 — FLEET INVENTORY AUDIT (FORENSIC)
## What we actually have on disk vs what the patient files claim
**Date:** 2026-04-11
**Author:** Opus 4.6 Opus-Claw (Dr. C) — Claude Opus 4.6 terminal instance
**Machine:** Veron-1 (RTX 5090, Mt Pleasant SC)
**Ordered by:** Grant Whitmer (The Windstorm)
**Context:** Commander asked "how many working models do we ACTUALLY have, across the total inventory" before any further work. This audit answers that.
**Prior reports:** `2026-04-11_state-of-union.md` (same day, Dr. C)

---

## HEADLINE

**The clinic said 1,826 patients with weights "present." The disk says 1,422 patients have at least one full transformers-loadable variant, 374 have been reduced to ONNX INT8 only, and 30 are completely missing.**

Physically testable Helsinki-NLP fleet: **1,226 of 1,607** (76.3%). The rest were ONNX-exported and source-deleted between Herm Zero's Grand Rounds run (2026-03-29 04:48 UTC) and today — an event that happened on 2026-03-29 ~18:25–20:09 UTC and is not recorded in any prior doctor-log.

---

## METHOD

Non-destructive filesystem walk + patient-file reconciliation:

1. `scripts/fleet_inventory.py` — walked 5 roots, catalogued every directory containing model weight files (`*.safetensors`, `*.bin`, `*.onnx`, `*.gguf`), classified them, and cross-referenced against clinic patient IDs. 4,776 model directories found in 0.4 seconds.
2. `scripts/reconcile_variant_state.py` — for every one of the 1,826 patient files, checked each claimed variant against the filesystem and updated `variant_cluster.<variant>.status` to one of `present`, `missing_from_disk`, or `archived_as_onnx`. Appended a signed `DRC-INVENTORY-*` exam to every patient's `examination_log`.
3. **No model weights were modified, created, or deleted.** Only patient JSON files were written.

Patient files backed up pre-reconciliation to `backups/pre-reconcile-20260411-160313/` (77 MB).

---

## FLEET-WIDE NUMBERS

### Clinic vs disk (1,826 patient files total)

| State | Count | % |
|---|---|---|
| Have at least one **safetensors/pytorch_bin** variant on disk | 1,422 | 77.9% |
| Have **only ONNX INT8** archive (no safetensors) | 374 | 20.5% |
| Have **nothing at all** on disk | 30 | 1.6% |
| **Total** | **1,826** | 100% |

### Helsinki-NLP Phase 1 (the 1,607 GR1-tested models)

| Disk profile | Count | Meaning |
|---|---|---|
| base + lora + ct2 intact | 929 | Untouched base models, never herm0-improved. Fully testable. |
| base + lora + ct2 + herm0-scripture | 292 | The eBible-tuned batch. Fully testable including scripture variant. |
| base + lora (no ct2) | 4 | Partial. ct2 lost. |
| Everything intact (base+lora+ct2+herm0+onnx) | 1 | `windy-pair-fi-lv` — the lone herm0 survivor (Herm Zero was mid-improvement when his log cut off at 21:59:43 on 2026-03-28). |
| **ONLY ONNX INT8** (`model_int8.onnx`, 56 MB each) | 374 | The 375 OPUS-improved herm0 models. Source safetensors deleted. |
| Completely missing | 7 | `am-sv`, `ar-eo`, `ar-pl`, `ar-ru`, `ar-tr`, `be-es`, `ceb-en` |
| **Total** | **1,607** | |

**Testable with Herm Zero's `grand_rounds_harness.py` (transformers-based):** 1,226
**Testable only with an ONNX-based harness (to build):** 374
**Unrecoverable without re-download:** 7

### Phase 2 & other batches

| Batch | In clinic | On disk | Notes |
|---|---|---|---|
| `hplt-*` | ~106 | ~102 | 4 missing: hplt-en-nb, hplt-en-sr, hplt-nb-en, hplt-sr-en |
| `tcbig-*` / `tc-base-*` | ~256 | ~85 (via models_phase2/) | Phase 2 bible fleet |
| `wpl-*` | ~12 | ~12 | Whisper-pair-language variants |
| Tier reference (ALMA, Tower, m2m100, mBART, madlad) | 17 | 0 | Always catalog-only, never deployed locally |

### STT / voice (newly admitted 2026-04-11)

27 metadata-only patients in `stt-models/`. **Zero weights on disk.** Shipping catalog only. Live fleet lives on HuggingFace `WindyLabs/*` or remote machine.

---

## THE ONNX EVENT (2026-03-29, post-GR1)

### Timeline

| Time (UTC) | Event | Evidence |
|---|---|---|
| 2026-03-28 ~15:00 | Herm Zero starts Grand Rounds run | `run.pid` 19:52, `run.log` 15:54 |
| 2026-03-29 04:48:06 | Grand Rounds completes, 2,658 model-variants tested | `grand_rounds_summary.json` |
| 2026-03-29 18:25:25 | First ONNX INT8 export (`windy-pair-en-grk/model_int8.onnx`) | file mtime |
| 2026-03-29 ~20:09 | ONNX INT8 batch finishes: 375 models, "Success 183, Already done 191" | `audit_results/herm0_improvements/int8_quantize.log` |
| 2026-03-29 → 2026-04-11 | Herm Zero goes silent. No further activity. | No file modifications |

### What happened

Between 2026-03-29 18:25 and 20:09 UTC, a quantization pass converted 375 herm0-improved MarianMT models to INT8 ONNX format, stored them in `onnx_fleet/windy-pair-*/model_int8.onnx` (one 56 MB file per model), and — critically — **deleted the source directory structure** (`models/windy-pair-*/base/`, `lora/`, `ct2/`, `herm0/`, and `herm0-ct2/`). The herm0-scripture models were left alone.

The `int8_quantize.log` records "Success 183, Already done 191" — meaning 191 models had already been converted in an earlier pass (probably the ONNX fleet export earlier on 2026-03-29) and 183 more were converted in this round, totaling 374 (+ the 1 "windy-pair-fi-lv" straggler that was mid-improvement during Herm Zero's log cut-off).

### Consequences

1. **374 models have no tokenizer, config, or generation_config files** in their onnx_fleet dirs — only `model_int8.onnx`. To run inference on them, you'd need to pair them with a tokenizer pulled from HuggingFace `Helsinki-NLP/opus-mt-*` or from a sibling model's intact `base/` directory.
2. **Herm Zero's Grand Rounds results for these 374 remain valid** — the tests ran before the ONNX conversion. But any independent re-verification requires either:
   - An ONNX-based test harness (doesn't exist yet), OR
   - Re-downloading the source safetensors from HuggingFace, OR
   - Accepting the 2026-03-29 numbers on faith.
3. **The patient files lied.** Before this audit, all 374 claimed `variant_cluster.base.status: "present"` when in fact the base was gone. This is now corrected.
4. **No user-facing documentation** of this quantization pass exists. It was run (probably by Herm Zero via a script) but never filed.

### What was NOT harmed

- Base/lora/ct2 for all 929 "untouched" models is intact.
- The 292 eBible scripture models have all their variants intact (base, lora, ct2, herm0-scripture).
- Phase 2 models (`models_phase2/`) were not touched.
- No grand rounds results were corrupted.

---

## WHAT IT MEANS FOR PHASE 3 (independent verification)

### The 301 failing base models (from GR1)

| Disk state | Count | Verdict |
|---|---|---|
| Testable (base safetensors present) | 230 | ✅ Can be re-run with GR1 harness |
| ONNX-only | 70 | ⚠️ Cannot re-test without new harness or source re-pull |
| Nothing on disk | 1 | ❌ Cannot re-test (one of the 7 lost Phase 1) |
| **Total** | **301** | |

**230 of the 301 failing base models can be independently re-verified.** That's still a meaningful sample — if my re-run reproduces Herm Zero's grades on those 230, that's strong evidence the full 301 numbers are trustworthy. If my re-run DISAGREES, we have a methodology problem that would invalidate GR1 broadly.

The other 71 have to wait for Phase 2 (pull STT weights is not enough — we need to pull the Helsinki-NLP source models too, plus build an ONNX harness).

---

## PER-PATIENT IMPACT

Every one of the 1,826 patient files now carries:

- Updated `variant_cluster.<variant>.status` values (`present`, `missing_from_disk`, or `archived_as_onnx`)
- Updated `variant_cluster.<variant>.on_disk_path`, `on_disk_bytes`, `on_disk_format`, `on_disk_files` for present variants
- A new `DRC-INVENTORY-{patient_id}` entry in `examination_log` attributed to Opus 4.6 Opus-Claw (Dr. C) with timestamp 2026-04-11 and explanatory notes

Reconciliation deltas:
- 1,244 patients: unchanged (variant state already accurate)
- 581 patients: one or more variants re-flagged from `present` to `missing_from_disk`
- 375 patients: newly-discovered `onnx_int8_archive` variant added
- 2,098 total variant entries marked missing

---

## FILES WRITTEN THIS SESSION (2026-04-11)

| File | Purpose |
|---|---|
| `scripts/fleet_inventory.py` | The filesystem walker |
| `scripts/reconcile_variant_state.py` | Patient-file reconciler |
| `fleet-inventory/FLEET_INVENTORY_20260411.json` | 3.5 MB raw inventory data |
| `fleet-inventory/FLEET_INVENTORY_20260411.md` | Human-readable summary |
| `doctor-logs/2026-04-11_phase1-fleet-inventory.md` | This report |
| `backups/pre-reconcile-20260411-160313/translation-pairs/` | Pre-reconciliation backup (77 MB) |
| `translation-pairs/*.json` (1,826 files) | Each one reconciled + signed Dr. C exam entry |
| `MASTER_ROSTER.json` | Rebuilt |

---

## PENDING DECISIONS (escalated to The Windstorm)

1. **The 374 ONNX-only models.** Three options:
   - (a) Accept Herm Zero's GR1 numbers on faith and carry them as ONNX-shipped archives. Don't re-test.
   - (b) Pull source safetensors back from HuggingFace (`Helsinki-NLP/opus-mt-*`), re-test with the original harness.
   - (c) Build an ONNX-based test harness. Expensive and still needs tokenizers.

2. **The 7 lost Phase 1 models** (am-sv, ar-eo, ar-pl, ar-ru, ar-tr, be-es, ceb-en). Re-download from HF or drop from fleet?

3. **The 4 lost hplt-* models** (hplt-en-nb, hplt-en-sr, hplt-nb-en, hplt-sr-en). Same question.

4. **The 374 herm0 variants** — `variant_cluster.herm0` is now marked `missing_from_disk` because the source dir is gone. But the improvement DID happen (proven by GR1 results). Should the clinic carry a separate `herm0_onnx_archive` key referencing onnx_fleet/? I annotated this under `variant_cluster.onnx_int8_archive` but it's one-per-patient, not per-variant. Open to renaming.

5. **Phase 3a (re-test 301 failing)** can proceed on the 230 with safetensors. Should I start that now, or finish Phase 2 (STT sync) first?

---

## WHAT DR. C DID NOT DO

- Did NOT modify any model weights
- Did NOT delete any files
- Did NOT run any GPU work (GPU was being used by neighbor Claude process during this session)
- Did NOT touch anything outside `THE_CLINIC/`, `scripts/`, or read-only inspection of models
- Did NOT re-test any models independently (Phase 3 work blocked pending commander guidance on above)

---

*Filed by Opus 4.6 Opus-Claw (Dr. C) — 11 April 2026, Mt Pleasant SC*
*Previous report: 2026-04-11_state-of-union.md*
*Next report: after commander answers decisions 1–5 above, or after Phase 2 (STT sync)*

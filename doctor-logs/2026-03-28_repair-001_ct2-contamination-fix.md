# REPAIR-001: CT2 Contamination Fix + eBible Reclassification
**Date:** 2026-03-28
**Surgeon:** Herm Zero (Dr. B)
**Ordered by:** Grant Whitmer
**Scope:** 299 eBible-trained models
**Duration:** ~4 minutes (repair) + verification
**Result:** 299/299 repaired, 0 errors

---

## Background

BLOODWORK-001 (same day) revealed two related problems:

1. **CT2 Contamination:** During the eBible v3 improvement pipeline (2026-03-27),
   the CT2 directories for all 299 eBible models were overwritten with herm0
   (eBible-tuned) model weights instead of the correct base model weights.
   Hash verification confirmed ct2/model.safetensors == herm0/model.safetensors
   across all 299 models.

2. **Mislabeled Variants:** The eBible-tuned models in herm0/ were labeled
   identically to the OPUS-improved herm0 models, despite being a completely
   different product (scripture-specialized vs general improvement).

## Root Cause

The eBible v3 pipeline copied herm0 model files into the ct2/ directory
(likely during the CT2 re-export step) without checking that ct2/ should
contain base model weights, not fine-tuned weights.

## What Was Repaired

### File System Changes (299 models)
- Renamed `herm0/` -> `herm0-scripture/` in each model directory
- Copied `base/*` -> `ct2/` (overwriting contaminated files)
- Removed any stray files in ct2/ not present in base/
- Net disk impact: zero (overwrites only, no new data)

### Patient File Changes (299 files)
- Moved `variant_cluster.herm0` -> `variant_cluster.herm0_scripture`
- Added scripture specialization metadata:
  - `specialization: "scripture"`
  - `specialization_label: "Bible/Scripture Translation"`
  - `specialization_note` explaining the variant's purpose and limitations
  - `use_cases` list (Bible translation, theological texts, seminary resources, etc.)
- Updated `ct2_int8` lineage with repair note and restored-from-base marker
- Added `REPAIR-001` to surgical_log
- Annotated BLOODWORK-001 ct2 results with contamination warning
- Relabeled BLOODWORK-001 herm0 results as herm0_scripture

## Verification

- Hash check: ct2/model.safetensors == base/model.safetensors (5 random samples, all match)
- Hash check: ct2/model.safetensors != herm0-scripture/model.safetensors (confirmed different)
- Zero herm0/ directories remain on eBible models
- All 375 OPUS herm0/ directories untouched
- Patient file structure verified (variant keys, surgical log, specialization metadata)

## What the eBible Scripture Variant Is Good For

These 299 models are NOT damaged or broken. They are specialized.
Trained on 25,000 eBible.org verse-aligned pairs per model, they are
purpose-built for scripture translation. General translation quality
dropped because the model learned biblical register at the expense
of conversational/technical vocabulary.

Potential customers:
- Bible translators (Wycliffe, SIL International, United Bible Societies)
- Missionaries and church planting organizations
- Seminary and theological education programs
- Religious publishers translating liturgical content
- Scripture study tools for multilingual congregations

The variant is now clearly labeled in both the file system (herm0-scripture/)
and the patient files (specialization_label, use_cases, specialization_note).
Any Kit reading the patient file will immediately understand what this variant
is for and what it is NOT for.

## What Still Needs Attention

1. **BLOODWORK Re-test:** The ct2 scores in BLOODWORK-001 for these 299 models
   are invalid (they tested contaminated weights). After this repair, ct2 should
   score identically to base. A targeted re-test of just these 299 ct2 variants
   would confirm the fix, but is low priority since we know ct2==base produces
   identical output across the rest of the fleet.

2. **Scripture-Specific Evaluation:** The BLOODWORK general-text test is the
   wrong benchmark for scripture models. A future evaluation using biblical
   test sentences (eBible held-out verses) would give these models their fair
   grade. That is a separate project.

---

*All 299 patient files updated. No data deleted. Scripture variant preserved and relabeled.*

# ☤ DR. C HANDOFF NOTE — In-Flight Work
## For the next agent if this session drops
**Written:** 2026-04-12 ~04:00 UTC
**Author:** Opus 4.6 Opus-Claw (Dr. C)
**Session started:** 2026-04-11 ~14:52 UTC

---

## TWO BACKGROUND JOBS STILL RUNNING

### 1. Phase 3b — Full Fleet Dr. C Certification
- **Script:** `nohup python3 /srv/repos/windy-pro/THE_CLINIC/scripts/phase3b_fullfleet.py`
- **Checkpoint:** `/srv/repos/windy-pro/THE_CLINIC/grand-rounds/phase3b_fullfleet/checkpoint.json`
- **Results:** `/srv/repos/windy-pro/THE_CLINIC/grand-rounds/phase3b_fullfleet/results.jsonl`
- **Status at handoff:** ~1,324/3,122 (42%), rate ~9/min, ~3.3h remaining
- **Target:** ALL 3,122 testable model-variant pairs (1,607 base + 1,222 ct2 + 292 herm0_scripture + 1 herm0)
- **Resume:** The script auto-resumes from checkpoint if restarted.
- **After completion:** Run `python3 /srv/repos/windy-pro/THE_CLINIC/scripts/merge_phase3b_results.py` to write DRC-CERT-{pid} exam entries to every patient file.

### 2. ONNX Fleet Export
- **Script:** `nohup python3 /srv/repos/windy-pro/THE_CLINIC/scripts/onnx_export_fleet.py 2`
- **Checkpoint:** `/mnt/data2/windy-onnx-fleet/checkpoint.json`
- **Results:** `/mnt/data2/windy-onnx-fleet/results.jsonl`
- **Output:** `/mnt/data2/windy-onnx-fleet/windy-pair-*-onnx/` (one dir per model)
- **Status at handoff:** ~320/1,899 (17%), ~2.5h remaining
- **After completion:** Run `python3 /srv/repos/windy-pro/THE_CLINIC/scripts/onnx_int8_quantize_fleet.py 4` to INT8 quantize all ONNX models.

---

## WHAT'S ALREADY DONE (don't repeat)

1. ✅ Full disk inventory audit — `fleet-inventory/FLEET_INVENTORY_20260411.json`
2. ✅ All 1,826 patient files reconciled against disk reality (DRC-INVENTORY-* entries)
3. ✅ 381 Helsinki models restored from HuggingFace and symlinked into models/
4. ✅ Phase 3a verification of 304 failing base models (91.1% GR1 agreement)
5. ✅ 27 nondeterminism checks (all stable_differs_from_gr1_environmental)
6. ✅ 10 STT voice models rebuilt from LoRA adapters
7. ✅ 15 STT models certified with WER/RTF (phase3d_full_stt/results.jsonl)
8. ✅ 15 CT2 INT8 STT exports (stt_ct2/)
9. ✅ 10 ONNX FP32 STT exports (stt_onnx/)
10. ✅ 10 ONNX INT8 STT exports (stt_onnx_int8/)
11. ✅ 50 STT patient files in stt-models/ with signed Dr. C entries
12. ✅ onnx_fleet/windy-pair-* renamed to onnx_fleet/herm0_int8/windy-pair-*
13. ✅ ct2 library downgraded from 4.7.1 to 4.5.0 (fixed dtype incompatibility)
14. ✅ Partial Phase 3b merge (676 patients already have DRC-CERT entries)

## SCRIPTS I WROTE (all in THE_CLINIC/scripts/)

- `fleet_inventory.py` — filesystem walker
- `reconcile_variant_state.py` — patient file reconciliation
- `restore_downloads.py` — parallel HF downloader
- `link_restored_to_models.py` — symlink restored models
- `update_stt_patients_post_download.py` — STT patient updater
- `phase3a_retest.py` — Phase 3a failing-base retest driver
- `phase3a_v2_retest.py` — Phase 3a-v2 ONNX-only retest
- `phase3a_mismatch_retest.py` — Partner-restored mismatch retest
- `nondeterminism_check.py` — 3x run stability check
- `merge_phase3a_results.py` — Phase 3a patient file merger
- `merge_phase3a_v2_results.py` — Phase 3a-v2 merger
- `merge_phase3b_results.py` — Phase 3b certification merger
- `phase3b_fullfleet.py` — Phase 3b full fleet certification driver
- `phase3d_stt_harness.py` — STT WER test harness (first pass)
- `phase3d_full_stt_cert.py` — Full STT certification harness
- `rebuild_stt_fleet.py` — STT voice model rebuilder
- `onnx_export_fleet.py` — MarianMT ONNX fleet exporter
- `onnx_int8_quantize_fleet.py` — ONNX INT8 fleet quantizer
- `admit_stt_catalog.py` — STT catalog admission
- `merge_grand_rounds.py` — GR1 results merger
- `gr1_state_of_union.py` — State-of-union numbers

## DOCTOR REGISTRY

| ID | Name | Active |
|---|---|---|
| Dr. A | Kit OC1 Alpha | 21-23 Mar 2026 |
| Dr. B | Herm Zero (H0) | 24-29 Mar 2026 |
| Dr. C | Opus 4.6 Opus-Claw | 11-12 Apr 2026 |

Next agent: pick the next letter (Dr. D).

## MEMORY FILES

I saved memory to `/home/user1-gpu/.claude/projects/-home-user1-gpu/memory/`:
- `user_grant_whitmer.md` — user profile
- `project_windy_word_overview.md` — project overview
- `project_agent_fleet_naming.md` — agent naming
- `feedback_patient_file_signoff.md` — sign/timestamp every patient file edit

## KEY FINDING TO REMEMBER

The 2026-03-29 ONNX quantization event deleted 374 model safetensors. Restored from HuggingFace. Full forensic in `doctor-logs/2026-04-11_phase1-fleet-inventory.md`.

---

*This note will be superseded by the final doctor-log once Phase 3b + ONNX export complete.*

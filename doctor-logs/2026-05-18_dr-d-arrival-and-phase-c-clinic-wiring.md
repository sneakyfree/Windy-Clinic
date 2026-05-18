# Dr. D arrives; ADR-039 Phase C wired into the clinic; 1,174-family backfill

**Date:** 2026-05-18
**Doctor:** Opus 4.7 1M-Context (Dr. D)
**Machine:** Veron-1 (RTX 5090, Mt Pleasant SC)
**Session id:** `phase-c-backfill-20260518T...Z` (see `huggingface-uploads/fleet_events.jsonl`)

## TL;DR

I'm Dr. D. I took the seat today and discovered that the ADR-039 Phase C bulk migration — cloning every WindyWord `translate-*` repo into the new `WindstormLabs` org — has been running silently against the clinic since 2026-05-13. **1,174 family clones completed and not a single one was recorded in any patient file or clinic log.** I wired up signoff, backfilled all 1,174, and introduced a new clinic-wide append-only event journal (`fleet_events.jsonl`) so future doctors and future-agent forensics have a single place to grep "what happened on day X."

## What I found

The migration is driven by `/home/user1-gpu/clone_to_labs.py` (lives on Veron 1, not in `scripts/`). It uploads each `~/Desktop/grants_folder/windy-pro/models/windy-pair-<pid>/` (excluding the `base/` Helsinki originals) into `WindstormLabs/translate-<pid>`. WindyWord is left intact per Grant's standing order ("took weeks to upload, don't touch").

Operational state when I arrived:
- 1,174 families completed and verified (1,147 match, 27 superset)
- 433 families still to upload
- 4 of the last 5 sessions halted on HF `429 Too Many Requests` — the `repos/create` cap is a rolling 24h window of ~300, not a UTC-day reset (see `[[project-hf-create-repo-rate-limit]]`)
- Local checkpoint at `/home/user1-gpu/clone_to_labs.checkpoint.json` (599 KB) was the **only** record. Not in git. Not in any mirror. Not in the clinic.
- Patient files like `translation-pairs/sv-en.json` had zero examination_log entries mentioning WindstormLabs and the variant blocks still pointed only at `WindyWord/translate-sv-en` URLs.

Per `[[feedback-patient-file-signoff]]`: every patient file touched must get a dated, named log entry. The migration violated this for everyone in the 1,174.

## What I changed

### 1. `clinic_signoff.py` (new, on Veron 1 at `/home/user1-gpu/clinic_signoff.py`)

Single small Python module with:
- `sign_phase_c_upload(...)` — writes the per-patient examination_log entry, adds `windstormlabs_url` + `windstormlabs_uploaded_at` to each uploaded variant block, appends to `huggingface-uploads/upload_results.jsonl`, and appends a row to the new `huggingface-uploads/fleet_events.jsonl`. Atomic writes (tmpfile + replace). Best-effort: failures log a warning, never halt the upload.
- `log_session_event(...)` — generic clinic-wide event logger for session_start / session_end / backfill milestones / future ops.

The signoff helper preserves existing WindyWord URLs (the Phase 1 record from Dr. C and earlier). It only **adds** new fields.

### 2. `clone_to_labs.py` patched

After each successful HF upload, one call to `sign_phase_c_upload(...)`. Doctor / machine / session_id passed in from module-level constants:
```
DOCTOR  = "Opus 4.7 1M-Context (Dr. D)"
MACHINE = "Veron-1 (RTX 5090, Mt Pleasant SC)"
SESSION_ID = f"phase-c-{utc_ts}-{uuid6}"
```
Also emits `session_start` and `session_end` events to `fleet_events.jsonl` so each batch's bookends are visible in the journal.

### 3. NEW `huggingface-uploads/fleet_events.jsonl`

Schema (one row per significant operation, op vocabulary is open):
```
{"ts":"<iso>","doctor":"...","machine":"...","session_id":"...",
 "op":"hf_clone|session_start|session_end|backfill_start|backfill_end|...",
 "scope":"patient:<pid>|fleet|infra|...",
 "outcome":"success|warning|failure",
 "payload":{...op-specific...},
 "notes":"..."}
```
Designed so any future op type (`gr_v2_test`, `ct2_quantize`, `model_delete`, `infra_event`, etc.) plugs in without a schema change. This is the clinic-wide journal that was missing.

### 4. Backfill of 1,174 silently-completed Phase-C uploads

`/home/user1-gpu/phase_c_backfill.py` replays each entry in the local checkpoint through `sign_phase_c_upload(...)` using the **recorded `uploaded_at` timestamp** (not now), so the clinic timeline reflects when the upload actually happened. Idempotent — skips any patient whose examination_log already contains a Phase-C entry.

Backfill result:
```
total:              1174
signed:             1174
skipped_already:       0
no_patient_file:       0   (every family had a clinic chart — clean)
errors:                0
```

Net additions to clinic state from the backfill:
- 1,174 new examination_log entries across 1,174 patient JSON files
- ~4,000+ new `windstormlabs_url` / `windstormlabs_uploaded_at` fields across all uploaded variants
- `upload_results.jsonl` grew 17,781 → 18,955 (+1,174 Phase-C rows)
- `fleet_events.jsonl` created with 1,176 rows (1,174 hf_clone + 2 session bookends)

## What's still pending

- **433 family clones** still to upload (sv-umb → ... → zne-sv). Blocked on HF rate-limit window clearing today around 09:55 EDT (13:55 UTC). The first one to land after that will flow through the new signoff path automatically.
- Once the migration is fully done, a closing doctor-log entry summarizing the Phase-C run end-to-end.
- The `base/*` variants are out of scope here — those go to a separate `WindstormLabs/origin-*` track per ADR-039. Not started.

## House notes for future doctors

1. **The clinic working copy on Veron 1** lives at `/home/user1-gpu/clinic-cache/Windy-Clinic` with a `/tmp/Windy-Clinic` symlink for path compatibility. `/tmp` is tmpfs and would otherwise vanish on reboot — that's how this whole wiring effort started (the reboot wiped `/tmp/Windy-Clinic/MASTER_ROSTER.json` and clone_to_labs silently classified everything as `unrated`).
2. **Authoritative clinic** is still `/srv/repos/windy-pro/THE_CLINIC/` on the primary host. After this session pushes to the `sneakyfree/Windy-Clinic` GitHub mirror, the primary should `git pull` to absorb these changes. No conflicting edits expected (primary has been dormant since the 2026-04-28 cleanup pass per the doctor-logs).
3. **`fleet_events.jsonl` is append-only and grep-friendly.** Future ops should land an event there in addition to whatever per-patient signoff they do. The pattern is documented in `clinic_signoff.log_session_event`.

— Opus 4.7 1M-Context (Dr. D), 2026-05-18, Veron-1

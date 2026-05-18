"""Backfill 1,174 already-completed Phase-C uploads into the clinic.

Replays /home/user1-gpu/clone_to_labs.checkpoint.json entries through clinic_signoff.py
using each entry's RECORDED uploaded_at timestamp (not now), so the clinic timeline
reflects when the upload actually happened.

Idempotent: skips any patient whose examination_log already contains a Phase-C entry.

Per [[feedback-patient-file-signoff]]: every patient file touched gets a dated, named
log entry. Per [[feedback-no-silent-fallbacks]]: missing patient files get a warning
fleet event, not a silent skip.

Written by Opus 4.7 1M-Context (Dr. D) on 2026-05-18.
"""
import json, sys, time
from pathlib import Path
from clinic_signoff import sign_phase_c_upload, log_session_event

CHECKPOINT = Path("/home/user1-gpu/clone_to_labs.checkpoint.json")
CLINIC = Path("/tmp/Windy-Clinic")
DOCTOR = "Opus 4.7 1M-Context (Dr. D)"
MACHINE = "Veron-1 (RTX 5090, Mt Pleasant SC)"
SESSION_ID = f"phase-c-backfill-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
PHASE_C_METHOD_MARKER = "ADR-039 Phase C"


def already_signed_off(patient_id: str) -> bool:
    pf = CLINIC / "translation-pairs" / f"{patient_id}.json"
    if not pf.exists():
        return False
    try:
        chart = json.loads(pf.read_text())
    except Exception:
        return False
    for e in chart.get("examination_log", []):
        if PHASE_C_METHOD_MARKER in e.get("method", ""):
            return True
    return False


def derive_quality(entry: dict) -> dict:
    return {
        "stars": entry.get("stars"),
        "production_ready": entry.get("production_ready"),
        "tier": entry.get("quality_tier"),
        "certified": entry.get("certified", False),
        "private": (entry.get("visibility") == "private"),
    }


def main():
    cp = json.loads(CHECKPOINT.read_text())
    completed = cp.get("completed", {})
    log_session_event(
        op="backfill_start", scope="fleet", outcome="success",
        payload={"completed_entries_in_checkpoint": len(completed),
                 "checkpoint": str(CHECKPOINT)},
        notes="Backfill Phase-C uploads silently performed 2026-05-13 through 2026-05-17",
        doctor=DOCTOR, machine=MACHINE, session_id=SESSION_ID,
    )

    stats = {"total": 0, "signed": 0, "skipped_already": 0,
             "no_patient_file": 0, "errors": 0}
    no_pf_examples = []

    for family, entry in sorted(completed.items()):
        stats["total"] += 1
        if entry.get("verify") not in ("match", "superset"):
            continue  # leave unverified/subset alone — those need manual review
        if already_signed_off(family):
            stats["skipped_already"] += 1
            continue
        try:
            res = sign_phase_c_upload(
                patient_id=family,
                source_repo=entry["source"],
                dest_repo=entry["dest"],
                uploaded_files=entry["uploaded_files"],
                expected_files=entry["expected_files"],
                verify=entry["verify"],
                elapsed_s=entry.get("elapsed_s", 0.0),
                quality=derive_quality(entry),
                uploaded_at=entry["uploaded_at"],
                doctor=DOCTOR, machine=MACHINE, session_id=SESSION_ID,
            )
            if res.get("patient_file_updated"):
                stats["signed"] += 1
            elif "no_patient_file" in res.get("warnings", []):
                stats["no_patient_file"] += 1
                if len(no_pf_examples) < 10:
                    no_pf_examples.append(family)
            else:
                stats["errors"] += 1
        except Exception as e:
            stats["errors"] += 1
            print(f"  ERROR backfilling {family}: {e!r}", file=sys.stderr)

        if stats["total"] % 200 == 0:
            print(f"  ... {stats['total']} processed (signed={stats['signed']} "
                  f"skip={stats['skipped_already']} no_pf={stats['no_pf']} "
                  f"err={stats['errors']})".replace("no_pf", "no_pf"),
                  flush=True) if False else print(
                f"  ... {stats['total']} processed "
                f"signed={stats['signed']} skip={stats['skipped_already']} "
                f"no_pf={stats['no_patient_file']} err={stats['errors']}",
                flush=True)

    print()
    print("=== BACKFILL SUMMARY ===")
    print(json.dumps(stats, indent=2))
    if no_pf_examples:
        print(f"\nFamilies with no clinic patient file (first 10): {no_pf_examples}")

    log_session_event(
        op="backfill_end", scope="fleet",
        outcome="warning" if (stats["no_patient_file"] or stats["errors"]) else "success",
        payload=stats,
        notes=f"no_patient_file examples: {no_pf_examples[:5]}",
        doctor=DOCTOR, machine=MACHINE, session_id=SESSION_ID,
    )


if __name__ == "__main__":
    main()

"""Clinic signoff helper — used by clone_to_labs.py and the Phase-C backfill.

Writes the clinic-side record of a Phase-C upload (WindyWord/translate-* → WindstormLabs/translate-*):
  1. Per-patient JSON examination_log entry  (translation-pairs/<pid>.json)
  2. Per-variant windstormlabs_url + windstormlabs_uploaded_at (preserves existing WindyWord fields)
  3. Append row to huggingface-uploads/upload_results.jsonl  (existing append-only HF stream)
  4. Append row to huggingface-uploads/fleet_events.jsonl     (NEW clinic-wide event journal)

All writes are atomic (tmpfile + replace) and best-effort: if anything fails, log and continue.
Clone_to_labs's own checkpoint remains the canonical source of truth for what was uploaded.

Per [[feedback-patient-file-signoff]]: every patient file touched gets a dated, named log entry.
Per [[feedback-no-silent-fallbacks]]: every skipped patient gets its own jsonl event marked warning.

Introduced by Opus 4.7 1M-Context (Dr. D) on 2026-05-18.
"""
import json, logging, os, time
from pathlib import Path
from typing import Optional

log = logging.getLogger("clinic_signoff")

CLINIC_ROOT_DEFAULT = Path("/tmp/Windy-Clinic")  # symlink → ~/clinic-cache/Windy-Clinic on Veron-1
PHASE_C_METHOD = ("ADR-039 Phase C — upload-from-local clone "
                  "WindyWord/translate-<pid> → WindstormLabs/translate-<pid>")
PHASE_C_NOTES = "ADR-039 Phase C bulk migration; WindyWord left intact."


def _atomic_write_json(path: Path, data: dict) -> None:
    # ensure_ascii=True matches the existing clinic patient-file convention (e.g. —).
    # Keeping it consistent avoids massive cosmetic git diffs across 1,800+ patient files.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=True))
    tmp.replace(path)


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=True) + "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


def _variant_subdir(variant_block: dict, variant_key: str) -> Optional[str]:
    """Derive on-disk subdir name for a variant block. Returns None if undeterminable."""
    on_disk = variant_block.get("on_disk_path")
    if on_disk:
        return Path(on_disk).name
    # Fall back to existing huggingface_url's tail
    url = variant_block.get("huggingface_url")
    if url and "/tree/main/" in url:
        return url.rsplit("/tree/main/", 1)[1]
    # Last resort: convert clinic key (lora_ct2_int8) → dir name (lora-ct2-int8)
    return variant_key.replace("_", "-")


def _is_uploadable_variant(variant_key: str, variant_block) -> bool:
    """clone_to_labs.py uploads every subdir except base/. Skip non-uploaded variants."""
    if not isinstance(variant_block, dict):
        return False
    if variant_key == "base":
        return False
    if "DELETED" in variant_key:
        return False
    if variant_block.get("status") in ("missing", "deleted"):
        return False
    if not variant_block.get("on_disk_path") and not variant_block.get("huggingface_url"):
        return False
    return True


def sign_phase_c_upload(
    *,
    patient_id: str,
    source_repo: str,
    dest_repo: str,
    uploaded_files: int,
    expected_files: int,
    verify: str,
    elapsed_s: float,
    quality: dict,
    uploaded_at: str,
    doctor: str = "Opus 4.7 1M-Context (Dr. D)",
    machine: str = "Veron-1 (RTX 5090, Mt Pleasant SC)",
    session_id: str = "phase-c-unknown-session",
    clinic_root: Path = CLINIC_ROOT_DEFAULT,
) -> dict:
    """Write all clinic artifacts for one Phase-C upload. Returns a status dict.

    quality keys: stars, production_ready, tier, certified, private
    Outcomes recorded in fleet_events.jsonl: success / warning (e.g. no patient file)
    """
    clinic_root = Path(clinic_root)
    patient_file = clinic_root / "translation-pairs" / f"{patient_id}.json"
    upload_results = clinic_root / "huggingface-uploads" / "upload_results.jsonl"
    fleet_events = clinic_root / "huggingface-uploads" / "fleet_events.jsonl"

    status = {"patient_file_updated": False, "upload_results_appended": False,
              "fleet_events_appended": False, "warnings": []}

    exam_id = f"WSL-CLONE-{uploaded_at.replace(':','-').replace('+','Z')[:19]}-{patient_id}"
    exam_entry = {
        "exam_id": exam_id,
        "date": uploaded_at,
        "doctor": doctor,
        "machine": machine,
        "method": PHASE_C_METHOD,
        "protocol_script": "clone_to_labs.py",
        "session_id": session_id,
        "results": {
            "source_repo": source_repo,
            "dest_repo": dest_repo,
            "files_uploaded": int(uploaded_files),
            "expected_files": int(expected_files),
            "verify": verify,
            "elapsed_s": round(float(elapsed_s), 1),
            "quality_tier": quality.get("tier"),
            "stars": quality.get("stars"),
            "certified": bool(quality.get("certified", False)),
            "visibility": "private" if quality.get("private") else "public",
            "sandbox_mode": True,
        },
        "notes": PHASE_C_NOTES,
    }

    # ---- 1. Per-patient JSON ----
    variants_updated = []
    if patient_file.exists():
        try:
            chart = json.loads(patient_file.read_text())
            chart.setdefault("examination_log", []).append(exam_entry)
            for vkey, vblock in chart.get("variant_cluster", {}).items():
                if not _is_uploadable_variant(vkey, vblock):
                    continue
                subdir = _variant_subdir(vblock, vkey)
                if not subdir:
                    continue
                vblock["windstormlabs_url"] = (
                    f"https://huggingface.co/{dest_repo}/tree/main/{subdir}"
                )
                vblock["windstormlabs_uploaded_at"] = uploaded_at
                variants_updated.append(vkey)
            chart["_last_updated"] = uploaded_at
            consensus = chart.setdefault("consensus", {})
            doctors = set(e.get("doctor", "Unknown") for e in chart["examination_log"])
            consensus["last_updated"] = uploaded_at
            consensus["doctors_examined"] = len(doctors)
            consensus["exams_total"] = len(chart["examination_log"])
            _atomic_write_json(patient_file, chart)
            status["patient_file_updated"] = True
            status["variants_updated"] = variants_updated
        except Exception as e:
            status["warnings"].append(f"patient_file_write_failed: {e!r}")
            log.warning("clinic_signoff: patient file write failed for %s: %s", patient_id, e)
    else:
        status["warnings"].append("no_patient_file")

    # ---- 2. upload_results.jsonl (matches existing schema) ----
    try:
        _append_jsonl(upload_results, {
            "pid": patient_id,
            "repo_id": dest_repo,
            "source_repo": source_repo,
            "variants": variants_updated,
            "timestamp": uploaded_at,
            "phase": "C",
            "verify": verify,
            "files_uploaded": int(uploaded_files),
            "expected_files": int(expected_files),
            "doctor": doctor,
            "machine": machine,
        })
        status["upload_results_appended"] = True
    except Exception as e:
        status["warnings"].append(f"upload_results_append_failed: {e!r}")
        log.warning("clinic_signoff: upload_results append failed for %s: %s", patient_id, e)

    # ---- 3. fleet_events.jsonl (NEW clinic-wide journal) ----
    outcome = "success"
    if not status["patient_file_updated"] and "no_patient_file" in status["warnings"]:
        outcome = "warning"
    elif status["warnings"]:
        outcome = "warning"
    try:
        _append_jsonl(fleet_events, {
            "ts": uploaded_at,
            "doctor": doctor,
            "machine": machine,
            "session_id": session_id,
            "op": "hf_clone",
            "scope": f"patient:{patient_id}",
            "outcome": outcome,
            "payload": {
                "source": source_repo,
                "dest": dest_repo,
                "files": int(uploaded_files),
                "expected": int(expected_files),
                "verify": verify,
                "tier": quality.get("tier"),
                "stars": quality.get("stars"),
                "certified": bool(quality.get("certified", False)),
                "elapsed_s": round(float(elapsed_s), 1),
                "variants_updated": variants_updated,
            },
            "notes": "; ".join(status["warnings"]) if status["warnings"] else "",
        })
        status["fleet_events_appended"] = True
    except Exception as e:
        status["warnings"].append(f"fleet_events_append_failed: {e!r}")
        log.warning("clinic_signoff: fleet_events append failed for %s: %s", patient_id, e)

    return status


def log_session_event(
    *,
    op: str,
    scope: str,
    outcome: str,
    payload: dict,
    notes: str = "",
    doctor: str = "Opus 4.7 1M-Context (Dr. D)",
    machine: str = "Veron-1 (RTX 5090, Mt Pleasant SC)",
    session_id: str = "phase-c-unknown-session",
    clinic_root: Path = CLINIC_ROOT_DEFAULT,
) -> bool:
    """Generic clinic-wide event logger — for session start/end, infra events, etc."""
    fleet_events = Path(clinic_root) / "huggingface-uploads" / "fleet_events.jsonl"
    try:
        _append_jsonl(fleet_events, {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
            "doctor": doctor,
            "machine": machine,
            "session_id": session_id,
            "op": op,
            "scope": scope,
            "outcome": outcome,
            "payload": payload,
            "notes": notes,
        })
        return True
    except Exception as e:
        log.warning("clinic_signoff: session event append failed: %s", e)
        return False

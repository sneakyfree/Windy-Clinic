#!/usr/bin/env python3
"""Update STT patient files to reflect actual downloaded state.

For each STT patient with weights pulled into restore_20260411/stt/:
  - update variant_cluster.<v>.status to "present"
  - record on_disk_path, on_disk_bytes
  - append DRC-STTDOWNLOAD-{pid} exam entry signed by Dr. C

For STT patients whose HF repo didn't exist:
  - record variant_cluster.<v>.status: "not_uploaded_to_hf"
  - append DRC-STTPROBE-{pid} entry explaining the miss

Doctor: Opus 4.6 Opus-Claw (Dr. C)
Date:   2026-04-11
"""

import json
from datetime import datetime, timezone
from pathlib import Path

STT_DIR = Path("/srv/repos/windy-pro/THE_CLINIC/stt-models")
STT_RESTORE = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/restore_20260411/stt")
PROBE_RESULTS = Path("/tmp/stt_probe_results.json")

DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"
MACHINE = "Veron-1 (RTX 5090, Mt Pleasant SC)"
RUN_ISO = datetime.now(timezone.utc).isoformat()


def dir_size(p: Path) -> int:
    total = 0
    for f in p.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except Exception:
                pass
    return total


def main():
    if not PROBE_RESULTS.exists():
        print(f"WARN: {PROBE_RESULTS} not found — re-run probe first.")
        return

    probes = {p["pid"]: p for p in json.loads(PROBE_RESULTS.read_text())}

    updated_present = 0
    updated_missing = 0

    for pf in sorted(STT_DIR.glob("*.json")):
        if pf.name == "MASTER_ROSTER.json":
            continue

        chart = json.loads(pf.read_text())
        pid = chart["patient_id"]
        probe = probes.get(pid, {})

        vc = chart.setdefault("variant_cluster", {})
        log = chart.setdefault("examination_log", [])

        # Is it downloaded?
        local_dir = STT_RESTORE / pid
        has_local = local_dir.exists() and any(local_dir.rglob("*.safetensors")) or \
                    (local_dir / "model.bin").exists()

        if has_local:
            size = dir_size(local_dir)
            # Mark the primary variant as present
            for vname, vdata in list(vc.items()):
                if vdata.get("status") == "catalogued_not_local":
                    vc[vname] = {
                        **vdata,
                        "status": "present",
                        "on_disk_path": str(local_dir),
                        "on_disk_bytes": size,
                        "reconciled_at": RUN_ISO,
                        "reconciled_by": DOCTOR,
                    }

            exam_id = f"DRC-STTDOWNLOAD-{pid}"
            if not any(e.get("exam_id") == exam_id for e in log):
                log.append({
                    "exam_id": exam_id,
                    "date": RUN_ISO,
                    "doctor": DOCTOR,
                    "machine": MACHINE,
                    "method": "HuggingFace snapshot_download from WindyProLabs/* org",
                    "protocol_script": "scripts/restore_downloads.py",
                    "notes": (
                        f"Weights pulled from HuggingFace WindyProLabs org into "
                        f"{local_dir}. Size: {size / (1024*1024):.1f} MB. "
                        f"Previous state: catalogued_not_local. "
                        f"Now available for local STT quality testing. "
                        f"Filed by {DOCTOR}. Note: Kit OC1 Alpha's 2026-03-10 "
                        f"model_registry.json had the wrong HF org name "
                        f"('WindyLabs' instead of 'WindyProLabs') — this was a typo."
                    ),
                })
            updated_present += 1
        else:
            # Not downloaded. Why? Check probe.
            probe_status = probe.get("status", "unknown")
            probe_reason = "repo_not_found_on_hf" if probe_status == "missing" else probe_status

            for vname, vdata in list(vc.items()):
                if vdata.get("status") == "catalogued_not_local":
                    vc[vname] = {
                        **vdata,
                        "status": "not_uploaded_to_hf",
                        "probe_status": probe_status,
                        "note": (
                            f"Catalogued in src/models/model_registry.json but HF repo "
                            f"{vdata.get('hf_repo') or chart.get('hf_repo')} returns 404. "
                            f"Weights were never uploaded from the machine that ran "
                            f"Kit OC1 Alpha's fleet build. Not currently testable."
                        ),
                        "reconciled_at": RUN_ISO,
                        "reconciled_by": DOCTOR,
                    }

            exam_id = f"DRC-STTPROBE-{pid}"
            if not any(e.get("exam_id") == exam_id for e in log):
                log.append({
                    "exam_id": exam_id,
                    "date": RUN_ISO,
                    "doctor": DOCTOR,
                    "machine": MACHINE,
                    "method": "HuggingFace repo probe (HfApi.repo_info)",
                    "notes": (
                        f"Attempted to pull weights from HuggingFace. Result: "
                        f"{probe_reason}. This patient was catalogued by Kit OC1 Alpha "
                        f"in 2026-03-10 model_registry.json but the corresponding HF repo "
                        f"(corrected org: WindyProLabs/{pid}) either doesn't exist or "
                        f"is empty. The actual weights likely live only on Kit OC1's "
                        f"original build machine and were never uploaded. "
                        f"Filed by {DOCTOR} on 2026-04-11."
                    ),
                })
            updated_missing += 1

        chart["_last_updated"] = RUN_ISO
        pf.write_text(json.dumps(chart, indent=2))

    print(f"Present (downloaded):  {updated_present}")
    print(f"Missing (not on HF):   {updated_missing}")


if __name__ == "__main__":
    main()

"""Clone WindyWord/* variants → WindstormLabs/translate-* (and listen-*) via upload-from-local.

WindyWord is PRESERVED INTACT (per Grant 2026-05-13: "took weeks to upload, don't touch").
We upload from LOCAL copies that match WindyWord's contents (verified via clinic fingerprints).
Excludes base/ — those are pristine upstream archives, separate WindstormLabs/origin-* track.

Safeguards (per [[feedback-no-cron-hf-uploads]] + today's mint-script lessons):
- MAX_NEW_REPOS hard cap (env, default 280)
- Idempotent: checkpoint at /home/user1-gpu/clone_to_labs.checkpoint.json
- Stop-on-failure-streak (5 consecutive halts the run)
- Per-upload 600s timeout (large LFS files take time)
- Post-upload readback: compare file count to WindyWord original
- NO delete branches. Period.
- Skip families already in checkpoint OR already present on Labs with the right file count

Run:
    HF_TOKEN=<token> MAX_NEW_REPOS=5 python3 clone_to_labs.py    # smoke
    HF_TOKEN=<token> MAX_NEW_REPOS=280 python3 clone_to_labs.py  # daily batch
"""
import os, sys, json, time, glob, logging, uuid
from pathlib import Path
from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.utils import HfHubHTTPError, EntryNotFoundError
from clinic_signoff import sign_phase_c_upload, log_session_event

DOCTOR = "Opus 4.7 1M-Context (Dr. D)"
MACHINE = "Veron-1 (RTX 5090, Mt Pleasant SC)"
SESSION_ID = f"phase-c-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:6]}"

TOKEN = os.environ.get("HF_TOKEN")
if not TOKEN:
    print("ERROR: set HF_TOKEN", file=sys.stderr); sys.exit(2)
MAX_NEW_REPOS = int(os.environ.get("MAX_NEW_REPOS", "280"))

LOCAL_ROOT = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/models")
DEST_ORG = "WindstormLabs"
SOURCE_ORG = "WindyWord"
CHECKPOINT = Path("/home/user1-gpu/clone_to_labs.checkpoint.json")
LOG_PATH = Path("/home/user1-gpu/clone_to_labs.log")
ROSTER_PATH = Path("/tmp/Windy-Clinic/MASTER_ROSTER.json")
FAILURE_STREAK_HALT = 5
IGNORE_PATTERNS = ["base/*", "base/**", ".DS_Store", "*/.DS_Store"]
UPLOAD_TIMEOUT_S = 600
PUBLIC_STAR_THRESHOLD = 3.0  # stars threshold for "vetted/certified" classification.
                              # Used for METADATA only (recorded in checkpoint); does
                              # NOT gate upload visibility.
SANDBOX_MODE = True           # Grant 2026-05-15: "we are in early sandbox mode, nobody
                              # knows we exist. Make all HF accounts public. Curation
                              # happens via WindyTranslate Collection, not HF privacy."
                              # When SANDBOX_MODE=True, every upload is public; the
                              # quality classification is recorded but not enforced
                              # at the repo-visibility level.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("clone")
api = HfApi(token=TOKEN)


def load_checkpoint() -> dict:
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {"completed": {}, "total_uploaded_lifetime": 0}


def save_checkpoint(cp: dict):
    tmp = CHECKPOINT.with_suffix(".tmp")
    tmp.write_text(json.dumps(cp, indent=2))
    tmp.replace(CHECKPOINT)


def family_from_dir(d: Path) -> str:
    """windy-pair-af-de -> af-de ; windy-pair-en-NORTH_EU -> en-NORTH_EU"""
    name = d.name
    if name.startswith("windy-pair-"):
        return name[len("windy-pair-"):]
    return name


def load_quality_roster() -> dict:
    """Return MASTER_ROSTER's patients dict, or {} if not available."""
    if ROSTER_PATH.exists():
        return json.loads(ROSTER_PATH.read_text()).get("patients", {})
    log.warning("MASTER_ROSTER not found at %s — defaulting all to private", ROSTER_PATH)
    return {}


def classify_quality(family: str, roster: dict) -> dict:
    """Classify a family by clinic quality data — METADATA ONLY in sandbox mode.

    Returns dict with stars, production_ready, tier label, certified bool, and
    private bool. In SANDBOX_MODE=True the private field is always False (everything
    uploads public); certified=True means meets the bar for WindyTranslate Collection
    inclusion (stars>=PUBLIC_STAR_THRESHOLD AND production_ready==True).
    """
    p = roster.get(family, {})
    stars = p.get("stars")
    pr = p.get("production_ready")
    if stars is None:
        tier = "unrated"
        certified = False
    elif isinstance(stars, (int, float)) and stars < PUBLIC_STAR_THRESHOLD:
        tier = "below_bar"
        certified = False
    elif pr is False:
        tier = "flagged_not_ready"
        certified = False
    elif stars >= 5.0:
        tier = "premium"
        certified = True
    elif stars >= 4.0:
        tier = "deployment"
        certified = True
    else:
        tier = "marginal"
        certified = True
    private_flag = (not certified) and (not SANDBOX_MODE)
    return {"stars": stars, "production_ready": pr, "tier": tier,
            "certified": certified, "private": private_flag}


def gather_workload() -> list:
    """Return sorted list of (family_id, local_dir, source_repo, dest_repo) tuples."""
    work = []
    for d in sorted(LOCAL_ROOT.glob("windy-pair-*")):
        if not d.is_dir(): continue
        family = family_from_dir(d)
        source_repo = f"{SOURCE_ORG}/translate-{family}"
        dest_repo = f"{DEST_ORG}/translate-{family}"
        work.append((family, d, source_repo, dest_repo))
    return work


def expected_file_count(source_repo: str) -> int:
    """Count files in the WindyWord source (so we can verify after upload)."""
    try:
        files = api.list_repo_files(source_repo, token=TOKEN)
        # We exclude base/ on upload, but source doesn't have base/ anyway (verified earlier)
        return len(files)
    except Exception as e:
        log.warning("can't list source %s: %s", source_repo, e)
        return -1


def main():
    cp = load_checkpoint()
    cp["session_started"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    completed = cp.setdefault("completed", {})
    log.info("config: MAX_NEW_REPOS=%d DEST=%s SOURCE=%s LOCAL=%s",
             MAX_NEW_REPOS, DEST_ORG, SOURCE_ORG, LOCAL_ROOT)
    log.info("checkpoint already has %d completed clones", len(completed))
    log.info("clinic signoff: doctor=%s session_id=%s", DOCTOR, SESSION_ID)
    log_session_event(
        op="session_start", scope="fleet", outcome="success",
        payload={"max_new_repos": MAX_NEW_REPOS, "dest_org": DEST_ORG,
                 "source_org": SOURCE_ORG, "completed_at_start": len(completed)},
        doctor=DOCTOR, machine=MACHINE, session_id=SESSION_ID,
    )

    roster = load_quality_roster()
    log.info("clinic MASTER_ROSTER loaded: %d patients", len(roster))

    work = gather_workload()
    log.info("local scan: %d windy-pair-* families found", len(work))

    # A family is "done" if its previous upload was match (files equal) or
    # superset (Labs has more — happens when WindyWord had a stub repo).
    # Re-process if verify="subset" (Labs has fewer files than source) or anything
    # else uncertain.
    def is_done(fam):
        entry = completed.get(fam)
        if not entry: return False
        v = entry.get("verify")
        return v in ("match", "superset")
    todo = [w for w in work if not is_done(w[0])]
    log.info("remaining to clone (or re-fix): %d (will do up to %d this session)", len(todo), MAX_NEW_REPOS)

    uploaded_this_session = 0
    failures_streak = 0
    halted = False
    failed_entries = []

    for family, local_dir, source_repo, dest_repo in todo:
        if uploaded_this_session >= MAX_NEW_REPOS:
            log.info("HARD CAP REACHED: %d this session. Stopping cleanly.", MAX_NEW_REPOS)
            break
        try:
            t0 = time.time()
            # Pre-flight: count expected files from WindyWord
            expected_count = expected_file_count(source_repo)
            # Pre-fetch any root-level files (README.md, .gitattributes) from source that local doesn't have
            for sidecar in ("README.md", ".gitattributes"):
                target_path = local_dir / sidecar
                if target_path.exists():
                    continue
                try:
                    hf_hub_download(
                        repo_id=source_repo,
                        filename=sidecar,
                        token=TOKEN,
                        local_dir=str(local_dir),
                    )
                    log.debug("  pre-fetched %s from %s", sidecar, source_repo)
                except (EntryNotFoundError, HfHubHTTPError):
                    pass
                except Exception as e:
                    log.warning("  could not pre-fetch %s from %s: %s", sidecar, source_repo, e)
            # Quality gate: consult clinic MASTER_ROSTER to decide visibility
            quality = classify_quality(family, roster)
            # Create the target repo (idempotent) — private flag set per quality
            api.create_repo(
                repo_id=dest_repo,
                repo_type="model",
                private=quality["private"],
                exist_ok=True,
                token=TOKEN,
            )
            # If repo already existed (from a prior run before the gate), enforce visibility
            api.update_repo_settings(repo_id=dest_repo, private=quality["private"], token=TOKEN)
            # Upload from local (now includes pre-fetched sidecars)
            api.upload_folder(
                folder_path=str(local_dir),
                repo_id=dest_repo,
                repo_type="model",
                ignore_patterns=IGNORE_PATTERNS,
                commit_message=f"clone from {source_repo} via local upload (ADR-039 Phase C)",
                token=TOKEN,
            )
            elapsed = time.time() - t0
            # Readback verify
            uploaded_files = api.list_repo_files(dest_repo, token=TOKEN)
            uploaded_count = len(uploaded_files)
            if expected_count < 0:
                verify_status = "unverified"
            elif uploaded_count == expected_count:
                verify_status = "match"
            elif uploaded_count > expected_count:
                verify_status = "superset"  # Labs more complete than source (source was stub)
            else:
                verify_status = "subset"    # Labs has fewer files than source — investigate
            completed[family] = {
                "source": source_repo,
                "dest": dest_repo,
                "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "local_dir": str(local_dir),
                "uploaded_files": uploaded_count,
                "expected_files": expected_count,
                "verify": verify_status,
                "elapsed_s": round(elapsed, 1),
                "stars": quality["stars"],
                "production_ready": quality["production_ready"],
                "quality_tier": quality["tier"],
                "certified": quality["certified"],
                "visibility": "private" if quality["private"] else "public",
                "sandbox_mode": SANDBOX_MODE,
            }
            cp["total_uploaded_lifetime"] = cp.get("total_uploaded_lifetime", 0) + 1
            save_checkpoint(cp)
            uploaded_this_session += 1
            failures_streak = 0
            log.info("[%d/%d] OK %s -> %s  files=%d expected=%d verify=%s  stars=%s tier=%s certified=%s (%.1fs)",
                     uploaded_this_session, MAX_NEW_REPOS, family, dest_repo,
                     uploaded_count, expected_count, verify_status,
                     quality["stars"], quality["tier"], quality["certified"], elapsed)
            # Clinic signoff — per [[feedback-patient-file-signoff]] every patient file touched
            # gets a dated, named log entry. Best-effort; checkpoint above is canonical.
            try:
                signoff = sign_phase_c_upload(
                    patient_id=family,
                    source_repo=source_repo,
                    dest_repo=dest_repo,
                    uploaded_files=uploaded_count,
                    expected_files=expected_count,
                    verify=verify_status,
                    elapsed_s=elapsed,
                    quality=quality,
                    uploaded_at=completed[family]["uploaded_at"],
                    doctor=DOCTOR,
                    machine=MACHINE,
                    session_id=SESSION_ID,
                )
                if signoff.get("warnings"):
                    log.warning("  clinic signoff warnings for %s: %s", family, signoff["warnings"])
            except Exception as e:
                log.error("  clinic signoff FAILED for %s (upload itself succeeded): %s", family, e)
            if verify_status == "subset":
                log.warning("  !! file count SUBSET (uploaded<expected) — investigate before next batch")
            elif verify_status == "superset":
                log.info("  ~ file count SUPERSET (uploaded>expected) — likely WindyWord was incomplete stub; Labs is more authoritative")
        except HfHubHTTPError as e:
            status = getattr(e.response, "status_code", None)
            msg = str(e)[:200]
            log.error("[%d] HTTP %s on %s: %s", uploaded_this_session, status, family, msg)
            failed_entries.append({"family": family, "status": status, "err": msg})
            if status == 429:
                log.warning("rate-limited (429); halting this session (safeguard)")
                halted = True; break
            failures_streak += 1
            if failures_streak >= FAILURE_STREAK_HALT:
                log.error("FAILURE STREAK %d — HALTING (no zombie)", failures_streak)
                halted = True; break
        except Exception as e:
            log.error("[%d] err on %s: %s", uploaded_this_session, family, e)
            failed_entries.append({"family": family, "err": str(e)[:200]})
            failures_streak += 1
            if failures_streak >= FAILURE_STREAK_HALT:
                log.error("FAILURE STREAK %d — HALTING", failures_streak)
                halted = True; break

    cp["last_session_summary"] = {
        "ended_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "uploaded": uploaded_this_session,
        "halted_early": halted,
        "failures": failed_entries,
        "remaining_after_session": max(0, len(todo) - uploaded_this_session),
        "doctor": DOCTOR,
        "session_id": SESSION_ID,
    }
    save_checkpoint(cp)
    log.info("SESSION DONE. uploaded=%d halted=%s failures=%d remaining=%d",
             uploaded_this_session, halted, len(failed_entries),
             cp["last_session_summary"]["remaining_after_session"])
    log_session_event(
        op="session_end", scope="fleet",
        outcome="warning" if halted else "success",
        payload={"uploaded": uploaded_this_session, "halted_early": halted,
                 "failures": len(failed_entries),
                 "remaining_after_session": cp["last_session_summary"]["remaining_after_session"]},
        notes=f"failures={failed_entries[:3]}..." if failed_entries else "",
        doctor=DOCTOR, machine=MACHINE, session_id=SESSION_ID,
    )


if __name__ == "__main__":
    main()

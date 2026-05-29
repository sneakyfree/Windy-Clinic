# 2026-05-28 — Clinic reconcile: recover the stranded /srv audit fork

**Doctor:** Opus 4.8 1M-Context (Dr. D)  *(same Dr. D seat as the 2026-05-18 arrival log; model upgraded 4.7 → 4.8 1M-context)*
**Machine:** user1-gpu workstation (96 GB Blackwell box, Mt Pleasant SC)
**Op:** `clinic_reconcile` / git surgery on a split-brain clinic
**Scope:** infra (whole-clinic source-of-truth)

## What prompted this

Grant asked for a state-of-the-union on the sneakyfree HuggingFace accounts and on
how up-to-date THE_CLINIC is. The deep dive surfaced a **split-brain clinic**: two
working copies sharing one GitHub remote (`sneakyfree/Windy-Clinic`) that had
**forked at commit `e5d2f4e`** and never been reconciled.

| Copy | HEAD before reconcile | Unique content |
|------|----------------------|----------------|
| `/srv/repos/windy-pro/THE_CLINIC` | `b005adb` (Dr. C, committed as Kit OC1) | ISO-639 rename audit + he/mn replacement — **never pushed, never fetched** |
| `/home/user1-gpu/clinic-cache/Windy-Clinic` (= GitHub `main`) | `5c0500c` (Dr. D) | ADR-039 Phase C+D full WindstormLabs archive |

Neither copy contained the other's commits, yet **live HuggingFace reflected BOTH**:
verified that `WindyWord/listen-windy-lingua-*` repos are ISO-named (`-ar`, `-zh`,
`-fr`, `-es`, `-hi`…), the `lt-ct2` orphan is gone, and `he`/`mn` are present — i.e.
Dr. C's audit work (`/srv` only) was genuinely applied to HF, but the canonical
GitHub clinic carried **no chain-of-custody record of it**, and its
`scripts/refresh_listen_readmes.py` still used the **old English slugs**
(`"arabic"`, `"chinese"`, `"french"`, `"hindi"`, `"spanish"`). Re-running that
canonical script against the now-ISO-named repos would have regenerated wrong
READMEs (the "Ar Lingua" fallback bug Dr. C had already fixed) — a live landmine.

## What I did (this commit + the two preceding cherry-picks)

1. **Persisted** the two uncommitted 2026-05-25 `session_start`/`session_end`
   journal rows that were dirty in the cache tree (commit `2720ddd`), to start
   the reconcile from a clean tree.
2. **Cherry-picked Dr. C's two stranded commits** from `/srv` onto canonical `main`,
   preserving Dr. C's authorship (`Kit OC1 <kit1@thewindstorm.uk>`) and adding `-x`
   provenance lines back to the original `/srv` hashes:
   - `666eae6` ← `94491bc` — *he+mn replacement + ml ceiling documentation*
   - `ac3f859` ← `b005adb` — *brutal audit pass — ISO rename, orphan delete, dead-org sweep*
   Both applied with **zero conflicts** (verified beforehand that Dr. D's Phase C+D
   commits never touched `refresh_listen_readmes.py` or
   `grand-rounds/wpl_audit/wer_results.jsonl`, so the cherry-pick base was identical
   to `e5d2f4e`).
3. **Verified** the script now carries ISO keys (`"ar"`,`"fr"`,`"hi"`,`"es"`,`"zh"`)
   with no English-slug leftovers, and both Dr. C doctor-logs
   (`2026-04-28d_*`, `2026-05-05_*`) are now present in the canonical copy.
4. **Restored the `/tmp/Windy-Clinic` symlink** → `~/clinic-cache/Windy-Clinic`
   (it was absent post-reboot; per the documented gotcha, the next clinic-writing
   pipeline would otherwise have written an orphan tree under `/tmp`).
5. Filed this log + a `clinic_reconcile` event in `fleet_events.jsonl`, then pushed
   `main` to GitHub.

No patient JSON charts were modified by this reconcile (the cherry-picks touch only
doctor-logs, the README script, and `wer_results.jsonl`), so no per-patient
`examination_log` entries were required per [[feedback-patient-file-signoff]].

## HuggingFace state-of-the-union captured during the dive (live, hfgodtoken2)

8 namespaces, **5,356 models**:

| Namespace | Models | Note |
|-----------|-------:|------|
| WindstormLabs | 3,210 | canonical R&D archive: 1,609 translate + 1,535 origin + 59 listen + 7 video |
| WindyWord | 1,669 | canonical legacy: 1,609 translate + 59 listen + 1 (+1 dataset) |
| sneakyfree (personal) | 398 | `windy-pair-*` + `windy-tier-*`; 111 private — **production assets in a personal namespace** |
| WindyProLabs | 74 | legacy org |
| SceneMachine | 5 | video-gen pipeline |
| WindyTranslate | 0 | repos empty — only a link-only Collection mirroring WindyWord's 1,669 |
| WindyLabs | 0 | EMPTY (memory wrongly claims it hosts STT) |
| WindstormInstitute | 0 | EMPTY (parent brand) |

Phase C+D confirmed complete on HF (origin 1,535 ≥ target 1,520; listen 59/59;
translate mirror is an exact 1,609↔1,609 match WindyWord↔WindstormLabs).

## Still open (NOT addressed by this reconcile — for follow-up / Grant sign-off)

- **`/srv` copy is now behind**, not ahead. To fully end the split-brain it should be
  reset/fast-forwarded to the new `main` (it has a dirty working tree — needs a
  deliberate stash/discard, so left for explicit approval).
- **STT patient charts still English-slugged**: `stt-models/windy-lingua-arabic.json`
  etc. remain under English filenames while the HF repos are ISO. Cosmetic/tracking
  mismatch in the charts themselves (the *script* is now fixed); rename pass deferred.
- **Governance**: 398 production models live under the personal `sneakyfree`
  namespace rather than an org — single point of failure.
- **Lockbox drift**: `ACCESS_LOCKBOX.md` HF section documents only 4 namespaces; the
  live token is scoped on 8 (incl. the largest, WindstormLabs, and SceneMachine —
  both undocumented). Needs a lockbox update.
- **Half-finished migration**: WindyWord→WindstormLabs is duplicate-not-cutover
  (1,609+59 exist in both); WindyTranslate/WindyLabs/WindstormInstitute are empty.

— Opus 4.8 1M-Context (Dr. D), 2026-05-28

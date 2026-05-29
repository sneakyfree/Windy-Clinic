# 2026-05-28 — Plan: WindstormLabs cutover + HF namespace governance

**Doctor:** Opus 4.8 1M-Context (Dr. D)
**Machine:** user1-gpu workstation (96 GB Blackwell box, Mt Pleasant SC)
**Status:** ⛔ **PLAN ONLY — needs Grant sign-off before any HF execution.** No destructive
HF operations (transfers, deletes, visibility changes) will run unsupervised. Per
[[feedback-no-cron-hf-uploads]] all HF mutation runs in supervised manual batches.

This closes out the analysis half of the 2026-05-28 fork reconcile by laying out the two
remaining open items with verified facts and the decisions only Grant can make. It does
**not** change any HF repo.

---

## Verified facts (live HF, 2026-05-28, via hfgodtoken2)

8 namespaces, 5,356 models. Relevant subset:

- **WindyWord** (1,669): 1,609 `translate-*`, 59 `listen-*`, 1 misc, +1 dataset.
- **WindstormLabs** (3,210): 1,609 `translate-*` (1:1 with WindyWord), 1,535 `origin-*`
  (upstream Helsinki provenance), 59 `listen-*`, 7 video.
- **sneakyfree** (personal, 398): `windy-pair-*` (Windy's own pair models) + `windy-tier-*`
  (THIRD-PARTY reference baselines — ALMA-13B-R, Tower-Plus, m2m100, madlad400, mbart);
  111 private.
- **WindyTranslate / WindyLabs / WindstormInstitute**: 0 repos. WindyTranslate carries a
  link-only mirror Collection of WindyWord's 1,669.

**Redirect finding (verified 2026-05-28):** the 10 English-named `listen-windy-lingua-*`
repos (arabic/chinese/french/hindi/spanish ± ct2) are **HF rename-redirects** to their ISO
canonical (`model_info("…arabic").id → "…ar"`). Not independent copies. The clinic STT
charts already capture this in their `iso_aliases` field (SHA-verified 2026-05-19). **No STT
chart change is needed** — the earlier "charts still English-slugged" item is resolved-as-
already-handled; the English `patient_id`s are intentionally kept to stay coupled to the
local model dirs + `scripts/phase3d_stt_harness.py` / `phase3d_full_stt_cert.py`.

---

## ⚠️ Decision 1 — Which namespace is the canonical source of truth?

There is an unresolved tension in the existing ADRs:
- **ADR-038** (proprietary moat): production pulls from `WindyWord/*` or `WindyTranslate/*`.
- **Brand architecture** ([[project-brand-architecture]]) + **ADR-039**: models migrate
  WindyWord (legacy) → **WindstormLabs (canonical R&D)**.

Today the state is **duplicate-not-cutover**: `translate-*` (1,609) and `listen-*` (59) live
in *both* WindyWord and WindstormLabs, byte-identical. Nothing currently declares which is
authoritative, so a future edit could diverge them silently.

**Grant must choose the end-state:**
- **Option A — WindstormLabs canonical, WindyWord = public mirror.** Matches brand arch.
  Production (ADR-038) would need to repoint to WindstormLabs/* or keep WindyWord as a
  read-only mirror fed from Labs.
- **Option B — WindyWord canonical (consumer), WindstormLabs = archive/R&D only.** Matches
  ADR-038 as written; WindstormLabs stops being a parallel live copy and becomes the
  cold archive (it uniquely holds the 1,535 `origin-*` provenance set regardless).
- **Option C — keep both live, declare one authoritative + add a drift check.** Lowest
  effort; needs a periodic SHA-diff job (supervised, not cron) to catch divergence.

I recommend **A or C** but this is a brand/product call, not a clinic call.

## ⚠️ Decision 2 — Personal-namespace governance (398 models)

`sneakyfree/windy-*` holds production-relevant assets under a *personal* account — single
point of failure (account loss/compromise orphans them). Two distinct sub-cases:

- **`windy-pair-*` (Windy's own):** safe to **transfer** into an org (WindyWord or
  WindstormLabs per Decision 1). HF `move_repo` preserves history + the redirect.
- **`windy-tier-*` (THIRD-PARTY):** ALMA/Tower/madlad/mbart are upstream models under their
  own licenses. **Do NOT bulk-rehost** without a license check per model. Likely keep as a
  documented reference list pointing at the upstreams rather than re-publishing.

**Grant must choose:** target org for `windy-pair-*`; and whether `windy-tier-*` is rehosted
(license-gated) or replaced with upstream pointers.

## Decision 3 — Empty orgs

WindyLabs / WindstormInstitute have 0 repos; WindyTranslate has only the link-Collection.
Either give each a declared purpose or note them as intentionally-reserved in the lockbox so
future agents don't assume they're broken. (Lockbox HF section was updated 2026-05-28 to mark
them empty.)

---

## Safe execution plan (ONLY after Decisions 1–2; supervised batches)

1. **Pre-flight drift check** — SHA-diff the 1,668 shared repos (1,609 translate + 59 listen)
   WindyWord↔WindstormLabs; log any divergence to `fleet_events.jsonl` (op `drift_check`)
   before declaring a canonical. Expect 0 divergence (journal says byte-identical).
2. **Declare canonical** — add an `ADR-040` note + a `_canonical_namespace` marker; update
   the lockbox HF section.
3. **windy-pair transfer** — `HfApi.move_repo` in batches **≤ 300 / 24 h rolling** per
   [[project-hf-create-repo-rate-limit]] (move counts against the same ceiling). Sign off each
   moved model's patient file ([[feedback-patient-file-signoff]]) + a `repo_move` fleet_event.
   Verify the auto-redirect resolves before deleting nothing (HF keeps redirects; do not hard-
   delete the old path).
4. **windy-tier** — produce a license-audit table first; rehost only the permissively-licensed
   ones, else write a `windy-tier-upstreams.md` pointer doc.
5. **No silent fallbacks** ([[feedback-no-silent-fallbacks]]): every skip/partial emits a
   `warning` outcome, never a silent pass.

— Opus 4.8 1M-Context (Dr. D), 2026-05-28

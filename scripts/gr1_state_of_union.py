#!/usr/bin/env python3
"""Compute Grand Rounds v1 state-of-union numbers from merged patient files.

Writes a summary JSON + prints human-readable breakdown.
"""

import json
from collections import Counter, defaultdict
from pathlib import Path

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
PATIENTS = CLINIC / "translation-pairs"
OUT = CLINIC / "grand-rounds" / "GR1_STATE_OF_UNION.json"

GRADE_RANK = {
    "A+": 13, "A": 12, "A-": 11,
    "B+": 10, "B": 9, "B-": 8,
    "C+": 7, "C": 6, "C-": 5,
    "D+": 4, "D": 3, "D-": 2,
    "F": 1,
}
PASS_THRESHOLD = GRADE_RANK["C-"]   # ≥ C- counts as "working"
STRONG_THRESHOLD = GRADE_RANK["A-"] # ≥ A- counts as "strong"


def main():
    by_variant_grade = defaultdict(Counter)
    patients_with_gr1 = 0
    patients_total = 0
    improvement_deltas = []
    base_pass = 0
    base_strong = 0
    base_fail = 0
    base_absent = 0
    fail_list = []
    improved_winners = 0
    improved_losers = 0
    no_gr1 = []

    for pf in sorted(PATIENTS.glob("*.json")):
        patients_total += 1
        chart = json.loads(pf.read_text())
        pid = chart["patient_id"]
        exams = chart.get("examination_log", [])
        gr1 = next((e for e in exams if e.get("exam_id", "").startswith("GR1-")), None)
        if not gr1:
            no_gr1.append(pid)
            continue
        patients_with_gr1 += 1

        results = gr1.get("results", {})
        for variant, r in results.items():
            grade = r.get("composite_grade")
            if grade:
                by_variant_grade[variant][grade] += 1

        base = results.get("base", {})
        base_grade = base.get("composite_grade")
        base_score = base.get("composite_score")
        if base_grade is None:
            base_absent += 1
        else:
            rank = GRADE_RANK.get(base_grade, 0)
            if rank >= STRONG_THRESHOLD:
                base_strong += 1
            if rank >= PASS_THRESHOLD:
                base_pass += 1
            else:
                base_fail += 1
                fail_list.append({
                    "patient_id": pid,
                    "grade": base_grade,
                    "score": base_score,
                })

        herm0 = results.get("herm0") or results.get("herm0_scripture")
        if herm0 and herm0.get("composite_score") is not None and base_score is not None:
            delta = herm0["composite_score"] - base_score
            improvement_deltas.append({
                "patient_id": pid,
                "base": base_score,
                "improved": herm0["composite_score"],
                "delta": delta,
                "base_grade": base_grade,
                "improved_grade": herm0.get("composite_grade"),
            })
            if delta > 1.0:
                improved_winners += 1
            elif delta < -1.0:
                improved_losers += 1

    def grade_bucket_summary(c: Counter) -> dict:
        total = sum(c.values())
        passing = sum(n for g, n in c.items() if GRADE_RANK.get(g, 0) >= PASS_THRESHOLD)
        strong = sum(n for g, n in c.items() if GRADE_RANK.get(g, 0) >= STRONG_THRESHOLD)
        return {
            "total": total,
            "passing_c_minus_or_better": passing,
            "strong_a_minus_or_better": strong,
            "distribution": dict(sorted(c.items(), key=lambda kv: -GRADE_RANK.get(kv[0], 0))),
        }

    improvement_deltas.sort(key=lambda d: -d["delta"])

    summary = {
        "_generated": "2026-04-11",
        "_filed_by": "Opus 4.6 Opus-Claw (Dr. C)",
        "_source": "Grand Rounds v1, run 2026-03-28/29 by Herm Zero",
        "clinic_patients_total": patients_total,
        "patients_with_gr1_exam": patients_with_gr1,
        "patients_without_gr1_exam": len(no_gr1),
        "non_gr1_sample": no_gr1[:20],
        "pass_threshold": "C-",
        "strong_threshold": "A-",
        "base_variant": {
            "total": patients_with_gr1 - base_absent,
            "passing": base_pass,
            "strong": base_strong,
            "failing": base_fail,
            "absent_grade": base_absent,
            "pass_pct": round(base_pass / max(patients_with_gr1 - base_absent, 1) * 100, 1),
            "strong_pct": round(base_strong / max(patients_with_gr1 - base_absent, 1) * 100, 1),
        },
        "by_variant": {
            variant: grade_bucket_summary(grades)
            for variant, grades in sorted(by_variant_grade.items())
        },
        "herm0_vs_base": {
            "models_compared": len(improvement_deltas),
            "winners_delta_gt_1": improved_winners,
            "losers_delta_lt_neg1": improved_losers,
            "average_delta": round(sum(d["delta"] for d in improvement_deltas) / max(len(improvement_deltas), 1), 2),
            "top_10_winners": improvement_deltas[:10],
            "top_10_losers": improvement_deltas[-10:][::-1],
        },
        "base_failing_count": len(fail_list),
        "base_failing_sample": fail_list[:30],
    }

    OUT.write_text(json.dumps(summary, indent=2))
    print(f"Wrote {OUT}")
    print()
    print(f"Clinic patients total:           {patients_total}")
    print(f"  With GR1 exam:                 {patients_with_gr1}")
    print(f"  Without GR1 exam:              {len(no_gr1)}")
    print()
    print(f"Base variant (out of {patients_with_gr1 - base_absent}):")
    print(f"  Passing (≥ C-):    {base_pass}  ({summary['base_variant']['pass_pct']}%)")
    print(f"  Strong (≥ A-):     {base_strong}  ({summary['base_variant']['strong_pct']}%)")
    print(f"  Failing (< C-):    {base_fail}")
    print()
    print("By variant:")
    for variant, stats in sorted(by_variant_grade.items()):
        s = grade_bucket_summary(stats)
        print(f"  {variant:18}  {s['passing_c_minus_or_better']:4}/{s['total']:4} pass   {s['strong_a_minus_or_better']:4} strong")
    print()
    print(f"Herm0 vs base: {improved_winners} winners, {improved_losers} losers, avg Δ {summary['herm0_vs_base']['average_delta']:+.2f}")


if __name__ == "__main__":
    main()

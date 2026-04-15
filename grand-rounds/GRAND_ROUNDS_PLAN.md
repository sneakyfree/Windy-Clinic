# GRAND ROUNDS: Comprehensive Fleet Stress Testing Plan
**Version:** 1.0
**Author:** Herm Zero (Dr. B)
**Date:** 2026-03-28
**Ordered by:** Grant Whitmer, Fleet Commander

---

## Mission

Subject every model in the Windy Pro fleet to six distinct stress tests.
When we are done, every model has a composite grade (A through F) derived
from uniform criteria applied across the entire fleet. No translation lab
in the world will know their models better than we know ours.

---

## Fleet Inventory

| Category | Count | Variants Tested |
|----------|-------|-----------------|
| Base models | 1,607 | base, lora, ct2 |
| OPUS herm0 improved | 375 | + herm0 |
| eBible herm0-scripture | 299 | + herm0-scripture |
| Total model-variant pairs | ~6,400 | |

---

## The Six Tests

### TEST 1: BLOODWORK (Round-Trip Fidelity)
STATUS: COMPLETE (ran 2026-03-28, 107 minutes)
Translate A->B and back. Score round-trip output against original.
Metric: Round-trip BLEU + chrF. Already in patient files.

### TEST 2: CROSSMATCH (Direct BLEU Against Reference)
STATUS: TO BUILD
Raw translation quality against known-good references.
Uses OPUS-100 test splits (~100 pairs) and eBible held-out verses (299 pairs).
Metric: BLEU + chrF + TER (Translation Edit Rate).

### TEST 3: VITALS (Speed and Throughput Benchmark)
STATUS: TO BUILD
Latency per sentence, throughput, GPU memory footprint.
Metric: ms/sentence, sentences/sec, peak GPU MB.
Variants: base vs ct2 (deployment-relevant comparison).

### TEST 4: STRESS FRACTURE (Edge Case and Robustness)
STATUS: TO BUILD
10 adversarial input types: empty string, single word, 500-word paragraph,
numbers/dates, special characters, mixed-language, repeated words, URLs,
all-caps, unicode/diacritics.
Metric: 0-10 pass score. Catches crashes, empty output, identity copies.

### TEST 5: CONSISTENCY CHECK (Determinism and Stability)
STATUS: TO BUILD
Translate same sentence 5 times. Should get identical output every time.
Metric: % consistency across runs. Flags unstable or corrupt models.

### TEST 6: SCRIPTURE EVAL (Biblical Text Specialist Test)
STATUS: TO BUILD
eBible held-out verses scored against reference translations.
The fair benchmark for herm0-scripture models.
Coverage: 299 scripture models only.

---

## Grading System

### Per-Test Scoring (0-100 scale)

| Test | A (90-100) | B (75-89) | C (60-74) | D (40-59) | F (<40) |
|------|------------|-----------|-----------|-----------|---------|
| Bloodwork | >=70 BLEU | 50-69 | 30-49 | 15-29 | <15 |
| Crossmatch | >=40 BLEU | 25-39 | 15-24 | 8-14 | <8 |
| Vitals | <=50ms | 50-100ms | 100-200ms | 200-500ms | >500ms |
| Stress Fracture | 10/10 | 8-9 | 6-7 | 4-5 | <4 |
| Consistency | 100% | 96-99% | 80-95% | 50-79% | <50% |
| Scripture | >=35 BLEU | 20-34 | 10-19 | 5-9 | <5 |

### Composite Grade Formula

bloodwork * 0.20 + crossmatch * 0.30 + vitals * 0.10 +
stress_fracture * 0.15 + consistency * 0.15 + scripture * 0.10

Models without reference data redistribute Crossmatch weight.
Models without scripture variants redistribute Scripture weight.

### Letter Grades

| Score | Grade | Label |
|-------|-------|-------|
| 95-100 | A+ | Elite |
| 90-94 | A | Excellent |
| 85-89 | A- | Very Good |
| 80-84 | B+ | Good |
| 75-79 | B | Above Average |
| 70-74 | B- | Solid |
| 60-69 | C | Average |
| 50-59 | D | Below Average |
| <50 | F | Failing |

---

## Execution Plan

### Phase 0: Infrastructure Setup (15 min)
- Install sacremoses
- Download OPUS-100 test splits
- Prepare eBible held-out verse pairs
- Build Grand Rounds harness with checkpoint/resume

### Phase 1: Stress Fracture + Consistency (2.5 hr)
1,607 models x edge cases + determinism checks.
Catches broken/corrupt models before expensive evals.

### Phase 2: Vitals (1.5 hr)
1,607 models x 2 variants (base + ct2).
Speed and memory benchmarking.

### Phase 3: Crossmatch (1.5 hr)
~700 models with reference data x all variants.
Gold-standard quality scoring.

### Phase 4: Scripture Eval (45 min)
299 herm0-scripture models vs base on biblical text.

### Phase 5: Grading and Reporting (30 min)
Composite scores, letter grades, patient file updates, doctor log.

---

## Time Budget

| Phase | Time | Cumulative |
|-------|------|------------|
| Setup | 15 min | 0:15 |
| Stress + Consistency | 2.5 hr | 2:45 |
| Vitals | 1.5 hr | 4:15 |
| Crossmatch | 1.5 hr | 5:45 |
| Scripture Eval | 45 min | 6:30 |
| Grading | 30 min | 7:00 |
| TOTAL | ~7 hours | |

Conservative with overhead: 8-9 hours.
Checkpoint/resume at every model boundary.

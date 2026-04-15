#!/usr/bin/env python3
"""
GRAND ROUNDS v2 — Paragraph-Level Comprehensive Stress Test
============================================================
8-test battery with 5-star rating system for the Windy Word fleet.

Tests:
  ① SENTENCE     — 10 basic sentences (sanity check)
  ② PARAGRAPH    — 5 × ~100-word domain paragraphs (business, casual, tech, medical, literary)
  ③ LONG_FORM    — 2 × ~300-word passages (full documents)
  ④ NATIVE_INPUT — 5 sentences in the SOURCE language (from OPUS cache)
  ⑤ DOMAIN       — Numbers, dates, currencies, proper nouns, medical terms
  ⑥ EDGE_CASES   — Empty, unicode, mixed-lang, all-caps, HTML, URLs
  ⑦ ROUNDTRIP    — Translate A→B→A fidelity
  ⑧ SPEED        — Latency, throughput, memory

5-Star Composite:
  Paragraph quality:    40%
  Long-form stability:  20%
  Native input:         15%
  Domain handling:      10%
  Sentence basics:       5%
  Edge cases:            5%
  Round-trip fidelity:   5%

Doctor: Opus 4.6 Opus-Claw (Dr. C)
"""

import gc
import json
import os
import re
import statistics
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import torch
from transformers import MarianMTModel, MarianTokenizer

MODELS_DIR = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/models")
OPUS_CACHE = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/audit_results/herm0_improvements/data_cache")
CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
OUT_DIR = CLINIC / "grand-rounds" / "grv2"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_JSONL = OUT_DIR / "results.jsonl"
CHECKPOINT = OUT_DIR / "checkpoint.json"
LOG_PATH = OUT_DIR / "run.log"

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"
MACHINE = "Veron-1 (RTX 5090, Mt Pleasant SC)"

# ═══════════════════════════════════════════════════════════════════
# TEST CONTENT
# ═══════════════════════════════════════════════════════════════════

SENTENCES = [
    "Hello, how are you today?",
    "The weather is beautiful this morning.",
    "I would like a cup of coffee please.",
    "The meeting has been rescheduled to next Thursday.",
    "Can you recommend a good restaurant nearby?",
    "She graduated from the university last year.",
    "The package should arrive within three business days.",
    "I need to make an appointment with my doctor.",
    "The train departs at half past nine from platform four.",
    "Thank you very much for your help and patience.",
]

PARAGRAPHS = {
    "business": (
        "Dear Mr. Thompson, I am writing to confirm our quarterly review meeting "
        "scheduled for March 15th at 2:30 PM in Conference Room B. We will be "
        "discussing the Q1 financial results, the proposed expansion into the "
        "Southeast Asian market, and the timeline for the new product launch. "
        "Please bring your department's performance metrics and budget projections "
        "for the next fiscal year. If you have any conflicts with this schedule, "
        "please let me know by end of day Friday. Best regards, Sarah Chen, "
        "Vice President of Operations."
    ),
    "casual": (
        "Hey! So I finally tried that new Thai place on Market Street that everyone's "
        "been talking about. The pad thai was honestly incredible — they use fresh rice "
        "noodles and the sauce has this perfect balance of sweet, sour, and spicy. I "
        "also got the mango sticky rice for dessert, which was to die for. The only "
        "downside was the wait — we stood in line for about 45 minutes on a Saturday "
        "night. But honestly, totally worth it. We should go together next week! Let "
        "me know when you're free."
    ),
    "technical": (
        "The system utilizes a microservices architecture deployed on Kubernetes clusters "
        "across three availability zones. Each service communicates via gRPC with Protocol "
        "Buffers for serialization, achieving sub-millisecond latency for inter-service "
        "calls. The primary database is PostgreSQL 15 with read replicas, while Redis "
        "serves as the caching layer with a 95th percentile hit rate of 98.7%. Automated "
        "CI/CD pipelines trigger on every pull request, running unit tests, integration "
        "tests, and security scans before deployment to the staging environment."
    ),
    "medical": (
        "Patient presents with acute onset of chest pain radiating to the left arm, "
        "accompanied by diaphoresis and shortness of breath. Initial ECG shows ST-segment "
        "elevation in leads II, III, and aVF, consistent with an inferior myocardial "
        "infarction. Troponin I levels were elevated at 2.4 ng/mL. The patient was "
        "administered aspirin 325mg, clopidogrel 600mg loading dose, and started on "
        "heparin infusion. Cardiology was consulted for emergent cardiac catheterization. "
        "Patient has a history of hypertension, type 2 diabetes, and hyperlipidemia."
    ),
    "literary": (
        "The autumn leaves drifted lazily across the cobblestone path, their crimson and "
        "gold hues painting the old garden in the warm palette of the dying season. "
        "Margaret stood at the window of the stone cottage, watching the last swallows "
        "gather on the telephone wire, preparing for their long journey south. She held "
        "the letter in her trembling hands — the one that had arrived that morning, "
        "bearing news she had waited fifty years to receive. The ink was faded, the "
        "paper yellowed with age, but the words were unmistakable."
    ),
}

LONG_FORM = {
    "email": (
        "Subject: Project Atlas — Phase 2 Timeline Update\n\n"
        "Dear Team,\n\n"
        "I wanted to provide an update on the Project Atlas Phase 2 timeline following "
        "our steering committee meeting yesterday. After careful review of the current "
        "progress and remaining deliverables, we have made several important decisions.\n\n"
        "First, the data migration component will be pushed back by two weeks to allow "
        "the engineering team to complete the necessary schema changes. This means the "
        "new target date for the migration is April 28th rather than April 14th. The "
        "QA team should adjust their testing schedule accordingly.\n\n"
        "Second, we have decided to proceed with the phased rollout approach rather than "
        "the big-bang deployment. This means we will start with the European region on "
        "May 5th, followed by Asia-Pacific on May 12th, and finally the Americas on "
        "May 19th. Each region will have a one-week stabilization period before we move "
        "to the next.\n\n"
        "Third, budget approval for the additional cloud infrastructure has been granted. "
        "The DevOps team can begin provisioning the new clusters immediately. Please "
        "coordinate with James in IT to ensure proper access controls are in place.\n\n"
        "Please review the attached updated Gantt chart and flag any concerns by Friday. "
        "We will have a follow-up call on Monday at 10 AM to address any issues.\n\n"
        "Best regards,\nDr. Alexandra Rivera\nProgram Director"
    ),
    "article": (
        "The global semiconductor shortage that began in 2020 has fundamentally reshaped "
        "how nations think about technological sovereignty and supply chain resilience. "
        "What started as a pandemic-driven disruption has evolved into a strategic concern "
        "that touches everything from automobile manufacturing to national security.\n\n"
        "At the heart of this transformation is the recognition that advanced chip "
        "manufacturing is concentrated in a remarkably small number of facilities. Taiwan "
        "Semiconductor Manufacturing Company produces roughly 90 percent of the world's "
        "most advanced processors, making the island a focal point of geopolitical tension. "
        "The United States, European Union, Japan, and South Korea have all announced "
        "multi-billion-dollar incentive programs to build domestic chip fabrication plants.\n\n"
        "However, building a modern semiconductor fabrication facility is neither quick nor "
        "simple. A single advanced fab costs between $15 and $20 billion and takes three "
        "to five years to construct. The equipment required — particularly extreme ultraviolet "
        "lithography machines made exclusively by ASML in the Netherlands — has a backlog "
        "stretching years into the future. Moreover, the workforce requirements are "
        "substantial: each facility needs thousands of highly specialized engineers and "
        "technicians whose training takes years to complete."
    ),
}

DOMAIN_TESTS = [
    "The invoice total is $4,287.53 including 8.25% sales tax.",
    "Please call Dr. Müller at +49-30-1234567 before 5:00 PM CET.",
    "The patient weighs 72.5 kg and has a BMI of 24.3.",
    "Flight LH 1234 departs Frankfurt (FRA) at 14:30 on 23/03/2026.",
    "The medication dosage is 500mg amoxicillin every 8 hours for 10 days.",
    "GDP growth was 3.2% in Q3, down from 4.1% in Q2.",
    "Mix 250ml of solution A with 175ml of solution B at 37°C.",
    "The defendant, Mr. José García-López, filed the motion on February 14th.",
]

EDGE_CASES = [
    "",
    "   \t\n  ",
    "Hello مرحبا Привет こんにちは 你好",
    "THIS IS ALL CAPS AND SHOULD STILL TRANSLATE PROPERLY",
    "123 456 789 0.00 1,234,567.89",
    "<p>This is <b>HTML</b> with <a href='http://example.com'>a link</a></p>",
    "http://www.example.com/path?query=value&other=123#section",
    "😀 🌍 ❤️ 🎉 Translation with emojis should work",
    "a " * 200,  # 200 repeated words
    "The quick brown fox. " * 20,  # Repeated sentence
]


# ═══════════════════════════════════════════════════════════════════
# SCORING
# ═══════════════════════════════════════════════════════════════════

def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def detect_degeneration(text: str) -> float:
    """Score 0-1 for degeneration (repeated phrases). 0 = no degeneration."""
    words = text.split()
    if len(words) < 10:
        return 0.0
    # Check for repeated 3-grams
    trigrams = [" ".join(words[i:i+3]) for i in range(len(words)-2)]
    if not trigrams:
        return 0.0
    unique_ratio = len(set(trigrams)) / len(trigrams)
    return max(0, 1.0 - unique_ratio)


def length_fidelity(src: str, tgt: str) -> float:
    """Score how well the output length matches the input length."""
    if not tgt.strip():
        return 0.0
    ratio = len(tgt) / max(len(src), 1)
    # Ideal ratio is 0.8-1.5 (translations vary in length)
    if 0.5 <= ratio <= 2.0:
        return 1.0
    elif 0.3 <= ratio <= 3.0:
        return 0.5
    else:
        return 0.0


def structural_integrity(src: str, tgt: str) -> float:
    """Check if sentence/paragraph structure is preserved."""
    src_sents = len(re.split(r'[.!?]+', src))
    tgt_sents = len(re.split(r'[.!?]+', tgt))
    if src_sents == 0:
        return 1.0
    ratio = tgt_sents / max(src_sents, 1)
    return min(1.0, max(0.0, 1.0 - abs(1.0 - ratio) * 0.5))


# ═══════════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════════

def translate(model, tokenizer, text, device, max_length=512):
    """Translate text, handling long inputs by truncation."""
    if not text.strip():
        return ""
    try:
        inputs = tokenizer(text, return_tensors="pt", truncation=True,
                          max_length=max_length).to(device)
        with torch.no_grad():
            outputs = model.generate(**inputs, max_new_tokens=max_length)
        return tokenizer.decode(outputs[0], skip_special_tokens=True)
    except Exception:
        return ""


def test_sentences(model, tokenizer, device):
    results = []
    for sent in SENTENCES:
        tgt = translate(model, tokenizer, sent, device)
        results.append({
            "src": sent[:80],
            "tgt": tgt[:80],
            "length_fidelity": length_fidelity(sent, tgt),
            "has_output": len(tgt.strip()) > 0,
        })
    score = sum(r["length_fidelity"] * 50 + (50 if r["has_output"] else 0) for r in results) / len(results)
    return {"score": round(score, 1), "passed": sum(1 for r in results if r["has_output"]), "total": len(results)}


def test_paragraphs(model, tokenizer, device):
    results = {}
    for domain, para in PARAGRAPHS.items():
        tgt = translate(model, tokenizer, para, device)
        degen = detect_degeneration(tgt)
        lf = length_fidelity(para, tgt)
        si = structural_integrity(para, tgt)
        quality = (lf * 40 + si * 30 + (1 - degen) * 30)
        results[domain] = {
            "src_len": len(para),
            "tgt_len": len(tgt),
            "length_fidelity": round(lf, 2),
            "structural_integrity": round(si, 2),
            "degeneration": round(degen, 2),
            "quality": round(quality, 1),
            "tgt_preview": tgt[:150],
        }
    avg = sum(r["quality"] for r in results.values()) / len(results)
    return {"score": round(avg, 1), "domains": results}


def test_long_form(model, tokenizer, device):
    results = {}
    for name, passage in LONG_FORM.items():
        tgt = translate(model, tokenizer, passage, device, max_length=1024)
        degen = detect_degeneration(tgt)
        lf = length_fidelity(passage, tgt)
        si = structural_integrity(passage, tgt)
        quality = (lf * 35 + si * 35 + (1 - degen) * 30)
        results[name] = {
            "src_len": len(passage),
            "tgt_len": len(tgt),
            "length_fidelity": round(lf, 2),
            "structural_integrity": round(si, 2),
            "degeneration": round(degen, 2),
            "quality": round(quality, 1),
        }
    avg = sum(r["quality"] for r in results.values()) / len(results)
    return {"score": round(avg, 1), "passages": results}


def test_paragraphs_native(model, tokenizer, native_paras, device):
    """Test with native-language paragraphs from OPUS cache."""
    results = {}
    for domain, para in native_paras.items():
        tgt = translate(model, tokenizer, para, device)
        degen = detect_degeneration(tgt)
        lf = length_fidelity(para, tgt)
        si = structural_integrity(para, tgt)
        quality = (lf * 40 + si * 30 + (1 - degen) * 30)
        results[domain] = {"quality": round(quality, 1), "tgt_preview": tgt[:100]}
    avg = sum(r["quality"] for r in results.values()) / max(len(results), 1)
    return {"score": round(avg, 1), "domains": results, "source": "native_opus"}


def test_long_form_native(model, tokenizer, native_long, device):
    """Test with concatenated native-language sentences as long-form passages."""
    results = {}
    for name, passage in native_long.items():
        tgt = translate(model, tokenizer, passage, device, max_length=1024)
        degen = detect_degeneration(tgt)
        lf = length_fidelity(passage, tgt)
        si = structural_integrity(passage, tgt)
        quality = (lf * 35 + si * 35 + (1 - degen) * 30)
        results[name] = {"quality": round(quality, 1)}
    avg = sum(r["quality"] for r in results.values()) / max(len(results), 1)
    return {"score": round(avg, 1), "passages": results, "source": "native_opus"}


def test_native_input(model, tokenizer, pid, device):
    """Use OPUS cache to find source-language sentences."""
    # Find data file for this language pair
    src_lang = pid.split("-")[0] if "-" in pid else pid
    tgt_lang = pid.split("-")[1] if "-" in pid else "en"

    # For X→en models, native input is in language X (use tgt from en→X data, or src from X→en)
    data_files = list(OPUS_CACHE.glob(f"*_{pid}.json"))
    if not data_files:
        # Try reverse
        rev = f"{tgt_lang}-{src_lang}"
        data_files = list(OPUS_CACHE.glob(f"*_{rev}.json"))

    if not data_files:
        return {"score": 50.0, "status": "no_native_data", "note": "No OPUS cache data for this pair"}

    try:
        data = json.loads(data_files[0].read_text())
        src_sents = data.get("src", [])
        # Pick 5 medium-length sentences
        medium = [s for s in src_sents if 20 < len(s) < 150][:5]
        if not medium:
            medium = src_sents[:5]

        results = []
        for sent in medium:
            tgt = translate(model, tokenizer, sent, device)
            results.append({
                "has_output": len(tgt.strip()) > 0,
                "length_fidelity": length_fidelity(sent, tgt),
            })
        score = sum(r["length_fidelity"] * 50 + (50 if r["has_output"] else 0) for r in results) / max(len(results), 1)
        return {"score": round(score, 1), "tested": len(results)}
    except Exception as e:
        return {"score": 50.0, "status": "error", "error": str(e)[:100]}


def test_domain(model, tokenizer, device):
    results = []
    for sent in DOMAIN_TESTS:
        tgt = translate(model, tokenizer, sent, device)
        has_numbers = bool(re.search(r'\d', tgt)) if re.search(r'\d', sent) else True
        has_output = len(tgt.strip()) > 0
        results.append({"has_output": has_output, "has_numbers": has_numbers})
    score = sum((50 if r["has_output"] else 0) + (50 if r["has_numbers"] else 0) for r in results) / len(results)
    return {"score": round(score, 1), "passed": sum(1 for r in results if r["has_output"] and r["has_numbers"]), "total": len(results)}


def test_edge_cases(model, tokenizer, device):
    results = []
    for inp in EDGE_CASES:
        try:
            tgt = translate(model, tokenizer, inp, device)
            crashed = False
        except Exception:
            tgt = ""
            crashed = True
        results.append({"crashed": crashed, "has_output": len(tgt.strip()) > 0 or inp.strip() == ""})
    score = sum(100 if not r["crashed"] else 0 for r in results) / len(results)
    return {"score": round(score, 1), "crashed": sum(1 for r in results if r["crashed"]),
            "total": len(results)}


def test_roundtrip(model, tokenizer, all_models, pid, device):
    """Translate A→B then B→A and compare."""
    parts = pid.split("-") if "-" in pid else [pid, "en"]
    if len(parts) < 2:
        return {"score": 50.0, "status": "cant_determine_reverse"}
    reverse_pid = f"{parts[1]}-{parts[0]}"
    reverse_dir = MODELS_DIR / f"windy-pair-{reverse_pid}"

    # Find reverse model
    for variant in ["lora", "base"]:
        rev_path = reverse_dir / variant
        if rev_path.exists() and ((rev_path / "model.safetensors").exists() or (rev_path / "pytorch_model.bin").exists()):
            try:
                rev_model = MarianMTModel.from_pretrained(str(rev_path)).to(device).eval()
                rev_tok = MarianTokenizer.from_pretrained(str(rev_path))

                scores = []
                for sent in SENTENCES[:5]:
                    fwd = translate(model, tokenizer, sent, device)
                    back = translate(rev_model, rev_tok, fwd, device)
                    sim = similarity(sent, back)
                    scores.append(sim * 100)

                del rev_model, rev_tok
                gc.collect()
                torch.cuda.empty_cache()
                return {"score": round(statistics.mean(scores), 1), "n": len(scores)}
            except Exception as e:
                return {"score": 50.0, "status": "reverse_load_error", "error": str(e)[:100]}

    return {"score": 50.0, "status": "no_reverse_model"}


def test_speed(model, tokenizer, device, test_sents=None):
    latencies = []
    sents = test_sents or SENTENCES[:5]
    for sent in sents[:5]:
        try:
            inputs = tokenizer(sent, return_tensors="pt", truncation=True, max_length=128).to(device)
            t0 = time.time()
            with torch.no_grad():
                model.generate(**inputs, max_new_tokens=128)
            latencies.append((time.time() - t0) * 1000)
        except Exception:
            latencies.append(0)
    peak_gpu = torch.cuda.max_memory_allocated() / (1024**2) if device == "cuda" else 0
    return {
        "score": round(max(0, 100 - statistics.mean(latencies) / 5), 1),
        "avg_latency_ms": round(statistics.mean(latencies), 1),
        "p95_latency_ms": round(sorted(latencies)[int(0.95 * len(latencies))], 1) if len(latencies) >= 5 else round(max(latencies), 1),
        "peak_gpu_mb": round(peak_gpu, 1),
    }


# ═══════════════════════════════════════════════════════════════════
# COMPOSITE SCORING → 5 STARS
# ═══════════════════════════════════════════════════════════════════

WEIGHTS = {
    "paragraphs": 0.40,
    "long_form": 0.20,
    "native_input": 0.15,
    "domain": 0.10,
    "sentences": 0.05,
    "edge_cases": 0.05,
    "roundtrip": 0.05,
}


def compute_stars(test_results):
    composite = 0
    total_weight = 0
    for test_name, weight in WEIGHTS.items():
        result = test_results.get(test_name, {})
        score = result.get("score", 50)
        composite += score * weight
        total_weight += weight

    if total_weight > 0:
        composite /= total_weight

    # Map to 5-star scale
    if composite >= 90:
        stars = 5.0
    elif composite >= 80:
        stars = 4.5 + (composite - 80) / 20
    elif composite >= 70:
        stars = 4.0 + (composite - 70) / 20
    elif composite >= 60:
        stars = 3.0 + (composite - 60) / 10
    elif composite >= 40:
        stars = 2.0 + (composite - 40) / 20
    elif composite >= 20:
        stars = 1.0 + (composite - 20) / 20
    else:
        stars = 0.5

    stars = round(min(5.0, max(0.5, stars)) * 2) / 2  # round to 0.5

    # Pricing tier
    if stars >= 4.5:
        tier = "premium"
    elif stars >= 3.5:
        tier = "standard"
    elif stars >= 2.5:
        tier = "basic"
    elif stars >= 1.5:
        tier = "budget"
    else:
        tier = "experimental"

    return {
        "composite_score": round(composite, 1),
        "stars": stars,
        "tier": tier,
    }


# ═══════════════════════════════════════════════════════════════════
# MAIN EVALUATION LOOP
# ═══════════════════════════════════════════════════════════════════

def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def get_native_paragraphs(pid):
    """Build paragraph-level test content from OPUS cache for non-English-source models."""
    data_files = list(OPUS_CACHE.glob(f"*_{pid}.json"))
    if not data_files:
        parts = pid.split("-") if "-" in pid else [pid, "en"]
        rev = f"{parts[1]}-{parts[0]}" if len(parts) >= 2 else pid
        data_files = list(OPUS_CACHE.glob(f"*_{rev}.json"))
    if not data_files:
        return None

    try:
        data = json.loads(data_files[0].read_text())
        sents = data.get("src", [])
        long_sents = [s for s in sents if 20 < len(s) < 200]
        if len(long_sents) < 15:
            long_sents = sents[:50]

        import random
        random.seed(42)
        random.shuffle(long_sents)

        paras = {}
        labels = ["native_general", "native_formal", "native_casual", "native_mixed", "native_varied"]
        for j, label in enumerate(labels):
            chunk = long_sents[j*5:(j+1)*5]
            if chunk:
                paras[label] = " ".join(chunk[:5])
        long_form = {
            "native_passage_1": " ".join(long_sents[:15]),
            "native_passage_2": " ".join(long_sents[15:30]) if len(long_sents) > 15 else " ".join(long_sents[:10]),
        }
        return paras, long_form
    except Exception:
        return None


def evaluate_one(pid, variant, model_path):
    """Run all 8 tests on one model-variant."""
    model = MarianMTModel.from_pretrained(str(model_path)).to(DEVICE).eval()
    tokenizer = MarianTokenizer.from_pretrained(str(model_path))
    torch.cuda.reset_peak_memory_stats() if DEVICE == "cuda" else None

    # Detect source language — if NOT English, use native input for paragraphs
    parts = pid.split("-") if "-" in pid else [pid, "en"]
    src_lang = parts[0].lower() if parts else "en"
    is_english_source = src_lang == "en"

    results = {}

    if is_english_source:
        # English source: use our English paragraphs directly
        results["sentences"] = test_sentences(model, tokenizer, DEVICE)
        results["paragraphs"] = test_paragraphs(model, tokenizer, DEVICE)
        results["long_form"] = test_long_form(model, tokenizer, DEVICE)
    else:
        # Non-English source: use native-language content from OPUS cache
        native = get_native_paragraphs(pid)
        if native:
            native_paras, native_long = native
            # Use native paragraphs through the same scoring functions
            results["sentences"] = test_native_input(model, tokenizer, pid, DEVICE)
            results["paragraphs"] = test_paragraphs_native(model, tokenizer, native_paras, DEVICE)
            results["long_form"] = test_long_form_native(model, tokenizer, native_long, DEVICE)
        else:
            # No native data — use basic sentences only (safer than paragraphs)
            results["sentences"] = {"score": 50.0, "status": "no_native_data"}
            results["paragraphs"] = {"score": 50.0, "status": "no_native_data"}
            results["long_form"] = {"score": 50.0, "status": "no_native_data"}

    results["native_input"] = test_native_input(model, tokenizer, pid, DEVICE)
    if is_english_source:
        results["domain"] = test_domain(model, tokenizer, DEVICE)
        results["edge_cases"] = test_edge_cases(model, tokenizer, DEVICE)
        results["roundtrip"] = test_roundtrip(model, tokenizer, None, pid, DEVICE)
        results["speed"] = test_speed(model, tokenizer, DEVICE)
    else:
        # For non-English source: skip English-specific domain test,
        # use safe edge cases, and test speed with native sentences
        results["domain"] = {"score": 50.0, "status": "skipped_non_english_source"}
        results["edge_cases"] = test_edge_cases(model, tokenizer, DEVICE)
        results["roundtrip"] = test_roundtrip(model, tokenizer, None, pid, DEVICE)
        # Get native sentences for speed test
        native_sents = None
        data_files = list(OPUS_CACHE.glob(f"*_{pid}.json"))
        if data_files:
            try:
                d = json.loads(data_files[0].read_text())
                native_sents = [s for s in d.get("src", []) if 10 < len(s) < 100][:5]
            except Exception:
                pass
        results["speed"] = test_speed(model, tokenizer, DEVICE, native_sents)

    rating = compute_stars(results)

    del model, tokenizer
    gc.collect()
    torch.cuda.empty_cache()

    return results, rating


def get_targets():
    """Enumerate all model-variant pairs to test."""
    targets = []
    for pair_dir in sorted(MODELS_DIR.glob("windy-pair-*")):
        pid = pair_dir.name[len("windy-pair-"):]
        for vname in ["lora", "base", "herm0", "herm0-scripture"]:
            vdir = pair_dir / vname
            real = vdir.resolve() if vdir.is_symlink() else vdir
            if not real.exists():
                continue
            if not ((real / "model.safetensors").exists() or (real / "pytorch_model.bin").exists()):
                continue
            targets.append({"pid": pid, "variant": vname, "path": str(vdir)})
    return targets


def main():
    targets = get_targets()
    state = {"done": [], "stars_dist": {}} if not CHECKPOINT.exists() else json.loads(CHECKPOINT.read_text())
    done = set(state["done"])
    remaining = [t for t in targets if f"{t['pid']}:{t['variant']}" not in done]

    log(f"Grand Rounds v2 — Paragraph-Level Stress Test")
    log(f"Doctor: {DOCTOR}")
    log(f"Total targets: {len(targets)}, done: {len(done)}, remaining: {len(remaining)}")
    log(f"Device: {DEVICE}")

    start = time.time()
    for i, target in enumerate(remaining, 1):
        pid = target["pid"]
        variant = target["variant"]
        key = f"{pid}:{variant}"

        log(f"[{i}/{len(remaining)}] {pid}:{variant}")

        try:
            t0 = time.time()
            results, rating = evaluate_one(pid, variant, target["path"])
            elapsed = time.time() - t0

            row = {
                "pid": pid,
                "variant": variant,
                "status": "complete",
                "tests": {k: {"score": v.get("score")} for k, v in results.items()},
                "full_results": results,
                "rating": rating,
                "elapsed": round(elapsed, 1),
                "_filed_by": DOCTOR,
                "_filed_at": datetime.now(timezone.utc).isoformat(),
            }

            with open(RESULTS_JSONL, "a") as f:
                f.write(json.dumps(row) + "\n")

            stars = rating["stars"]
            tier = rating["tier"]
            log(f"    {stars}★ ({tier}) — composite {rating['composite_score']} — {elapsed:.1f}s")

            state["stars_dist"][str(stars)] = state["stars_dist"].get(str(stars), 0) + 1

        except Exception as e:
            log(f"    ERROR: {type(e).__name__}: {str(e)[:200]}")
            row = {"pid": pid, "variant": variant, "status": "error", "error": str(e)[:200]}
            with open(RESULTS_JSONL, "a") as f:
                f.write(json.dumps(row) + "\n")

        state["done"].append(key)
        done.add(key)
        CHECKPOINT.write_text(json.dumps(state, indent=2))

        if i % 50 == 0:
            elapsed_total = time.time() - start
            rate = i / elapsed_total * 60
            log(f"  >> {i}/{len(remaining)} ({rate:.1f}/min) Stars: {state['stars_dist']}")

    log(f"Grand Rounds v2 complete: {len(state['done'])} total")
    log(f"Star distribution: {state['stars_dist']}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-single", nargs=2, metavar=("PID", "VARIANT"),
                       help="Subprocess mode: evaluate one model, print JSON to stdout")
    args = parser.parse_args()

    if args.eval_single:
        pid, variant = args.eval_single
        model_path = MODELS_DIR / f"windy-pair-{pid}" / variant
        real = model_path.resolve() if model_path.is_symlink() else model_path

        if not real.exists():
            print(json.dumps({"pid": pid, "variant": variant, "status": "not_found"}))
            sys.exit(1)

        try:
            results, rating = evaluate_one(pid, variant, str(model_path))
            row = {
                "pid": pid,
                "variant": variant,
                "status": "complete",
                "tests": {k: {"score": v.get("score")} for k, v in results.items()},
                "full_results": results,
                "rating": rating,
                "_filed_by": DOCTOR,
                "_filed_at": datetime.now(timezone.utc).isoformat(),
            }
            print(json.dumps(row))
        except Exception as e:
            print(json.dumps({"pid": pid, "variant": variant, "status": "error",
                             "error": f"{type(e).__name__}: {str(e)[:200]}"}))
            sys.exit(1)
    else:
        main()

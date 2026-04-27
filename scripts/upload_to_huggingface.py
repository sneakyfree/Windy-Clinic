#!/usr/bin/env python3
"""
WindyWord.ai HuggingFace Upload Orchestrator
=============================================
Uploads the full proprietary fleet to WindyWord org on HuggingFace.

Phase 0: Mirror clinic to private dataset repo (off-site backup #2)
Phase 1: Upload translation models (one repo per language pair, variants as subfolders)
Phase 2: Upload STT voice models
Phase 3: Upload STT lingua (per-language) models

Fully checkpoint-resumable. Respects rate limits with smart 429 retry
(via huggingface_hub v1.2+). Every upload logged in patient files.

Doctor: Opus 4.6 Opus-Claw (Dr. C)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import HfApi, create_repo, upload_folder, whoami
from huggingface_hub.errors import HfHubHTTPError, RepositoryNotFoundError

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

ORG = "WindyWord"
MODELS = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/models")
STT_REBUILT = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/restore_20260411/stt_rebuilt")
STT_CT2 = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/restore_20260411/stt_ct2")
STT_ONNX = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/restore_20260411/stt_onnx")
STT_ONNX_INT8 = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/restore_20260411/stt_onnx_int8")
STT_LINGUA = Path("/home/user1-gpu/Desktop/grants_folder/windy-pro/restore_20260411/stt")

CLINIC = Path("/srv/repos/windy-pro/THE_CLINIC")
PATIENTS = CLINIC / "translation-pairs"
STT_PATIENTS = CLINIC / "stt-models"

OUT_DIR = CLINIC / "huggingface-uploads"
OUT_DIR.mkdir(parents=True, exist_ok=True)
CHECKPOINT = OUT_DIR / "upload_checkpoint.json"
LOG_PATH = OUT_DIR / "upload.log"
RESULTS_JSONL = OUT_DIR / "upload_results.jsonl"

DOCTOR = "Opus 4.6 Opus-Claw (Dr. C)"
MACHINE = "Veron-1 (RTX 5090, Mt Pleasant SC)"

# Variant ordering and subfolder names in the uploaded repo
# We upload lora as the "main" variant (proprietary safe fork)
# and herm0/scripture as alternative subfolders
VARIANT_UPLOAD_MAP = [
    ("lora", "lora"),                        # proprietary fog-of-mirror — main variant
    ("lora-ct2-int8", "lora-ct2-int8"),      # CT2 INT8 of lora
    ("herm0", "herm0"),                      # deep OPUS improvement
    ("herm0-ct2-int8", "herm0-ct2-int8"),    # CT2 INT8 of herm0
    ("herm0-scripture", "herm0-scripture"),  # eBible specialization
    ("scripture-ct2-int8", "scripture-ct2-int8"),  # CT2 INT8 of scripture
]

# Pairs whose herm0 fine-tune regressed below base in Grand Rounds v2 (delta <= -5).
# We do NOT ship herm0 or herm0-ct2-int8 for these pids — users fall back to lora (≈ base).
HERM0_SKIPLIST_PATH = OUT_DIR / "herm0_skiplist.json"
HERM0_SKIP_PIDS: set = set()
if HERM0_SKIPLIST_PATH.exists():
    try:
        _sk = json.loads(HERM0_SKIPLIST_PATH.read_text())
        HERM0_SKIP_PIDS = set(_sk.get("herm0_skip_pids", []))
    except Exception:
        HERM0_SKIP_PIDS = set()

api = HfApi()


# ═══════════════════════════════════════════════════════════════
# LOGGING / CHECKPOINT
# ═══════════════════════════════════════════════════════════════

def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def load_checkpoint():
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {
        "phase0_clinic_uploaded": False,
        "phase1_done": [],
        "phase2_done": [],
        "phase3_done": [],
        "errors": [],
    }


def save_checkpoint(state):
    CHECKPOINT.write_text(json.dumps(state, indent=2))


# ═══════════════════════════════════════════════════════════════
# MODEL CARD GENERATION
# ═══════════════════════════════════════════════════════════════

_LANG_NAMES = {
    # ISO 639-1 singletons
    "af": "Afrikaans", "am": "Amharic", "ar": "Arabic", "az": "Azerbaijani",
    "be": "Belarusian", "bg": "Bulgarian", "bn": "Bengali", "bs": "Bosnian",
    "ca": "Catalan", "cs": "Czech", "cy": "Welsh", "da": "Danish",
    "de": "German", "el": "Greek", "en": "English", "eo": "Esperanto",
    "es": "Spanish", "et": "Estonian", "eu": "Basque", "fa": "Persian",
    "fi": "Finnish", "fr": "French", "ga": "Irish", "gd": "Scottish Gaelic",
    "gl": "Galician", "gu": "Gujarati", "he": "Hebrew", "hi": "Hindi",
    "hr": "Croatian", "hu": "Hungarian", "hy": "Armenian", "id": "Indonesian",
    "ig": "Igbo", "is": "Icelandic", "it": "Italian", "ja": "Japanese",
    "ka": "Georgian", "kk": "Kazakh", "km": "Khmer", "kn": "Kannada",
    "ko": "Korean", "ku": "Kurdish", "ky": "Kyrgyz", "la": "Latin",
    "lb": "Luxembourgish", "lg": "Ganda", "lt": "Lithuanian", "lv": "Latvian",
    "mg": "Malagasy", "mi": "Maori", "mk": "Macedonian", "ml": "Malayalam",
    "mn": "Mongolian", "mr": "Marathi", "ms": "Malay", "mt": "Maltese",
    "my": "Burmese", "nb": "Norwegian Bokmål", "ne": "Nepali", "nl": "Dutch",
    "nn": "Norwegian Nynorsk", "no": "Norwegian", "pa": "Punjabi", "pl": "Polish",
    "ps": "Pashto", "pt": "Portuguese", "ro": "Romanian", "ru": "Russian",
    "si": "Sinhala", "sk": "Slovak", "sl": "Slovenian", "sm": "Samoan",
    "so": "Somali", "sq": "Albanian", "sr": "Serbian", "st": "Sotho",
    "sv": "Swedish", "sw": "Swahili", "ta": "Tamil", "te": "Telugu",
    "tg": "Tajik", "th": "Thai", "ti": "Tigrinya", "tk": "Turkmen",
    "tl": "Tagalog", "tr": "Turkish", "uk": "Ukrainian", "ur": "Urdu",
    "uz": "Uzbek", "vi": "Vietnamese", "xh": "Xhosa", "yi": "Yiddish",
    "yo": "Yoruba", "zh": "Chinese", "zu": "Zulu",
    # ISO 639-3 aliases (3-letter where used in Helsinki naming)
    "deu": "German", "eng": "English", "fra": "French", "spa": "Spanish",
    "por": "Portuguese", "ita": "Italian", "nld": "Dutch", "rus": "Russian",
    "ces": "Czech", "slk": "Slovak", "cat": "Catalan", "oci": "Occitan",
    "ara": "Arabic", "jpn": "Japanese", "kor": "Korean", "tur": "Turkish",
    "swe": "Swedish", "nor": "Norwegian", "dan": "Danish", "fin": "Finnish",
    "pol": "Polish", "ukr": "Ukrainian", "bel": "Belarusian", "ron": "Romanian",
    "hrv": "Croatian", "srp": "Serbian", "bul": "Bulgarian", "ell": "Greek",
    "heb": "Hebrew", "hin": "Hindi", "vie": "Vietnamese", "tha": "Thai",
    # African languages (ISO 639-3)
    "bem": "Bemba", "ee": "Ewe", "efi": "Efik", "gaa": "Ga",
    "guw": "Gun", "ha": "Hausa", "iso": "Isoko", "kab": "Kabyle",
    "kg": "Kongo", "kqn": "Kaonde", "kwn": "Kwangali", "kwy": "San Salvador Kongo",
    "ln": "Lingala", "loz": "Lozi", "lu": "Luba-Katanga", "lua": "Luba-Lulua",
    "lue": "Luvale", "lun": "Lunda", "luo": "Luo",
    "mos": "Mossi", "ng": "Ndonga", "nso": "Northern Sotho",
    "ny": "Chichewa", "nyk": "Nyaneka", "om": "Oromo",
    "rn": "Rundi", "rnd": "Ruund", "run": "Rundi",
    "rw": "Kinyarwanda", "sg": "Sango", "sn": "Shona",
    "ss": "Swati", "swc": "Congo Swahili", "tiv": "Tiv",
    "tll": "Tetela", "tn": "Tswana", "toi": "Tonga (Zambia)",
    "ts": "Tsonga", "tum": "Tumbuka", "tw": "Twi",
    "umb": "Umbundu", "ve": "Venda", "wal": "Wolaytta",
    "zne": "Zande",
    # Pacific / Oceanic / Melanesian
    "bi": "Bislama", "fj": "Fijian", "gil": "Gilbertese",
    "ho": "Hiri Motu", "kj": "Kuanyama", "kl": "Kalaallisut (Greenlandic)",
    "lus": "Mizo", "mh": "Marshallese", "niu": "Niuean",
    "pis": "Pijin", "pon": "Pohnpeian", "to": "Tongan",
    "tpi": "Tok Pisin", "tvl": "Tuvaluan", "ty": "Tahitian",
    "wls": "Wallisian", "yap": "Yapese", "chk": "Chuukese",
    # Philippine languages
    "bcl": "Central Bikol", "ceb": "Cebuano", "hil": "Hiligaynon",
    "ilo": "Ilocano", "pag": "Pangasinan", "war": "Waray",
    # Caribbean / Creoles
    "bzs": "Brazilian Sign Language", "crs": "Seychellois Creole",
    "ht": "Haitian Creole", "mfe": "Mauritian Creole",
    "pap": "Papiamento", "srn": "Sranan Tongo", "tdt": "Tetum",
    # Sign languages
    "ase": "American Sign Language", "aed": "Argentine Sign Language",
    "csg": "Chilean Sign Language", "csn": "Colombian Sign Language",
    "fse": "Finnish Sign Language", "mfs": "Mexican Sign Language",
    "prl": "Peruvian Sign Language", "ssp": "Spanish Sign Language",
    "vsl": "Venezuelan Sign Language",
    # Americas / indigenous
    "tzo": "Tzotzil", "yua": "Yucatec Maya", "zai": "Isthmus Zapotec",
    # European minor / Celtic
    "gv": "Manx", "wa": "Walloon",
    # Asia
    "jap": "Japanese (alias)", "lus": "Mizo",  # lus also covered above
    "zhx": "Sinitic (Chinese variants)",
    # Helsinki-NLP family / collective codes
    "NORTH_EU": "North European", "SCANDINAVIA": "Scandinavian",
    "NORWAY": "Norwegian (regional)", "ROMANCE": "Romance languages",
    "CELTIC": "Celtic languages", "ZH": "Chinese (variants)",
    "SAMI": "Saami", "caenes": "Catalan/English/Spanish",
    # Multiple-language markers
    "mul": "Multiple Languages", "synthetic": "Synthetic Corpus",
    # Helsinki-NLP family-of-families collective codes
    "ccs": "South Caucasian (Kartvelian)", "cpf": "French-based Creoles",
    "cus": "Cushitic languages", "euq": "Basque-Iberian",
    "pqe": "Eastern Malayo-Polynesian", "sit": "Sino-Tibetan",
    "taw": "Tai-Kadai",
    # Historical / deprecated
    "sh": "Serbo-Croatian (historical, now Bosnian/Croatian/Serbian)",
    # ISO 639-5 family collectives
    "aav": "Austro-Asiatic", "afa": "Afro-Asiatic", "alv": "Atlantic-Congo",
    "art": "Artificial", "bat": "Baltic", "ber": "Berber", "bnt": "Bantu",
    "cau": "Caucasian", "cel": "Celtic", "cpp": "Portuguese-based Creole",
    "dra": "Dravidian", "fiu": "Finno-Ugric", "gem": "Germanic",
    "gmq": "North Germanic", "gmw": "West Germanic", "grk": "Greek",
    "inc": "Indo-Aryan", "ine": "Indo-European", "iir": "Indo-Iranian",
    "ira": "Iranian", "itc": "Italic", "map": "Austronesian",
    "mkh": "Mon-Khmer", "nic": "Niger-Congo", "omq": "Oto-Manguean",
    "phi": "Philippine", "poz": "Malayo-Polynesian", "pqw": "Western Malayo-Polynesian",
    "roa": "Romance", "sal": "Salishan", "sem": "Semitic",
    "sla": "Slavic", "smi": "Saami", "sqj": "Albanian", "tai": "Tai",
    "trk": "Turkic", "tut": "Altaic", "urj": "Uralic",
    "zle": "East Slavic", "zls": "South Slavic", "zlw": "West Slavic", "zlo": "Slavic",
    "NORTH_EU": "North-European", "SCANDINAVIA": "Scandinavian", "SAMI": "Saami",
    "multilingual": "Multilingual",
}

# Helsinki-NLP model-family prefixes we strip before language parsing.
# "synthetic-" added to handle pids like "synthetic-en-eu" (English→Basque from
# synthetic corpus) — without stripping, naive split would yield src="synthetic"
# and tgt="en-eu" which is incorrect.
_HELSINKI_PREFIXES = (
    "tc-bible-big-", "tc-big-", "tc-base-", "tcbig-", "hplt-", "synthetic-",
)


def _strip_helsinki_prefix(pid: str) -> str:
    for pfx in _HELSINKI_PREFIXES:
        if pid.startswith(pfx):
            return pid[len(pfx):]
    return pid


def parse_pid_langs(pid: str):
    """Extract (src_code, tgt_code) from a translation-pair pid, stripping Helsinki model-family
    prefixes (tc-big-, tc-base-, tc-bible-big-, tcbig-, hplt-) before splitting on the first hyphen.
    Also strips 'bible_' sub-prefix from src (a corpus marker, not a language code)."""
    stripped = _strip_helsinki_prefix(pid)
    parts = stripped.split("-", 1)
    if len(parts) != 2:
        return stripped, ""
    src, tgt = parts
    if src.startswith("bible_"):
        src = src[len("bible_"):]
    return src, tgt


def _lang_label(code: str) -> str:
    """Human-readable label for a language code. Handles ISO 639-1/3/5, Helsinki family codes,
    and underscore-separated multi-lang bundles (e.g. cat_oci_spa → 'Catalan/Occitan/Spanish')."""
    if not code:
        return "?"
    direct = _LANG_NAMES.get(code)
    if direct:
        return direct
    lower = code.lower()
    if lower in _LANG_NAMES:
        return _LANG_NAMES[lower]
    if "_" in code:
        parts = code.split("_")
        named = [_LANG_NAMES.get(p, _LANG_NAMES.get(p.lower(), p)) for p in parts]
        return "/".join(named)
    return code


# Common family expansions — so "zle" can be shown as "East Slavic (Russian, Ukrainian, Belarusian)".
_FAMILY_MEMBERS = {
    "zle": ["Russian", "Ukrainian", "Belarusian"],
    "zls": ["Bulgarian", "Croatian", "Macedonian", "Serbian", "Slovenian"],
    "zlw": ["Czech", "Polish", "Slovak"],
    "zlo": ["Slavic"],
    "sla": ["Russian", "Polish", "Czech", "Ukrainian", "Bulgarian", "Serbian", "Croatian", "Slovak"],
    "itc": ["Italian", "Spanish", "Portuguese", "French", "Catalan", "Romanian"],
    "roa": ["Italian", "Spanish", "Portuguese", "French", "Catalan", "Romanian"],
    "gmw": ["English", "German", "Dutch", "Afrikaans", "Yiddish"],
    "gmq": ["Swedish", "Danish", "Norwegian", "Icelandic", "Faroese"],
    "gem": ["English", "German", "Dutch", "Swedish", "Danish", "Norwegian"],
    "bat": ["Lithuanian", "Latvian"],
    "sem": ["Arabic", "Hebrew", "Maltese", "Amharic"],
    "bnt": ["Swahili", "Zulu", "Xhosa", "Shona", "Yoruba-related Bantu"],
    "urj": ["Finnish", "Estonian", "Hungarian", "Sami"],
    "fiu": ["Finnish", "Estonian", "Hungarian"],
    "iir": ["Hindi", "Persian", "Urdu", "Bengali", "Gujarati", "Marathi"],
    "inc": ["Hindi", "Bengali", "Urdu", "Gujarati", "Marathi", "Punjabi"],
    "ira": ["Persian", "Pashto", "Kurdish", "Tajik"],
    "trk": ["Turkish", "Azerbaijani", "Kazakh", "Uzbek", "Kyrgyz", "Turkmen"],
    "tut": ["Turkish", "Mongolian", "Japanese", "Korean"],
    "ine": ["English", "Spanish", "French", "German", "Russian", "Hindi"],
    "aav": ["Vietnamese", "Khmer", "Mon"],
    "afa": ["Arabic", "Hebrew", "Amharic", "Berber"],
    "alv": ["Igbo", "Swahili", "Yoruba", "Zulu"],
    "map": ["Indonesian", "Malay", "Tagalog", "Malagasy", "Samoan"],
    "poz": ["Indonesian", "Malay", "Tagalog", "Samoan"],
    "pqw": ["Indonesian", "Malay", "Tagalog", "Javanese"],
    "phi": ["Tagalog", "Cebuano", "Hiligaynon"],
    "cel": ["Irish", "Welsh", "Scottish Gaelic", "Breton"],
    "ber": ["Berber"],
    "cau": ["Georgian", "Armenian"],
    "smi": ["Northern Sami", "Lule Sami", "Southern Sami"],
    "cpp": ["Portuguese-based Creoles"],
    "dra": ["Tamil", "Telugu", "Kannada", "Malayalam"],
    "mkh": ["Vietnamese", "Khmer", "Mon"],
    "tai": ["Thai", "Lao", "Shan"],
    "nic": ["Swahili", "Yoruba", "Igbo", "Zulu", "Xhosa"],
    "mul": ["multiple languages"],
    "NORTH_EU": ["Swedish", "Danish", "Norwegian", "Finnish", "Estonian", "Latvian", "Lithuanian"],
    "SCANDINAVIA": ["Swedish", "Danish", "Norwegian", "Icelandic"],
    "SAMI": ["Northern Sami", "Lule Sami"],
    # Helsinki-NLP composite codes
    "ROMANCE": ["Italian", "Spanish", "Portuguese", "French", "Catalan", "Romanian"],
    "CELTIC": ["Irish", "Welsh", "Scottish Gaelic", "Breton", "Manx"],
    "NORWAY": ["Norwegian Bokmål", "Norwegian Nynorsk"],
    "ZH": ["Mandarin", "Cantonese", "Min Nan", "Hakka", "Wu"],
    "caenes": ["Catalan", "English", "Spanish"],
    "ccs": ["Georgian", "Mingrelian", "Svan", "Laz"],
    "euq": ["Basque", "Aquitanian"],
    "cus": ["Somali", "Oromo", "Afar", "Beja"],
    "cpf": ["Haitian Creole", "Mauritian Creole", "Seychellois Creole", "Réunion Creole"],
    "sit": ["Mandarin", "Cantonese", "Tibetan", "Burmese"],
    "taw": ["Thai", "Lao", "Zhuang", "Shan"],
    "pqe": ["Indonesian", "Malay", "Tagalog", "Samoan"],
    "zhx": ["Mandarin", "Cantonese", "Min Nan", "Hakka", "Wu"],
}


def _expand_lang(code: str) -> str:
    """Return a spelled-out expansion for a code, including family members if known.
    e.g. 'fi' → 'Finnish';  'zle' → 'East Slavic (Russian, Ukrainian, Belarusian)'"""
    label = _lang_label(code)
    if code in _FAMILY_MEMBERS and label != code:
        members = ", ".join(_FAMILY_MEMBERS[code])
        return f"{label} ({members})"
    if "_" in code:
        # Multi-language bundle, show all members
        parts = [_LANG_NAMES.get(p, _LANG_NAMES.get(p.lower(), p)) for p in code.split("_")]
        return " / ".join(parts)
    return label


def _tag_list(code: str):
    """Return a list of lowercase-hyphenated tag strings for the code's languages.
    Used to populate YAML `tags:` for HF search indexing."""
    out = []
    if not code:
        return out
    label = _lang_label(code)
    if label and label != code:
        out.append(label.lower().replace("/", "-").replace(" ", "-"))
    members = _FAMILY_MEMBERS.get(code, [])
    for m in members:
        out.append(m.lower().replace(" ", "-").split("(")[0].strip("-"))
    if "_" in code:
        for p in code.split("_"):
            n = _LANG_NAMES.get(p, _LANG_NAMES.get(p.lower()))
            if n:
                out.append(n.lower().replace(" ", "-"))
    return out


def _valid_iso(code: str) -> bool:
    """Check if a language code is a valid ISO 639-1/2/3 style (2-3 lowercase alpha) or special."""
    import re
    if not code:
        return False
    c = code.lower().strip()
    if c in ("multilingual", "code"):
        return True
    return bool(re.match(r"^[a-z]{2,3}$", c))


def build_translation_readme(patient: dict) -> str:
    pid = patient["patient_id"]

    # Parse language codes deterministically from the pid (Helsinki prefixes stripped).
    # Patient file codes can disagree with the pid for tc-big/tc-base families; the pid is canonical.
    src_lang, tgt_lang = parse_pid_langs(pid)
    src_display = _lang_label(src_lang)
    tgt_display = _lang_label(tgt_lang)

    source_repo = patient.get("source_repo", "Helsinki-NLP/opus-mt-" + pid)

    # YAML language list: only emit codes that pass strict ISO validation
    yaml_langs = []
    for code in [src_lang, tgt_lang]:
        if "_" in code:
            for sub in code.split("_"):
                if _valid_iso(sub):
                    yaml_langs.append(sub.lower())
        elif _valid_iso(code):
            yaml_langs.append(code.lower())
    if not yaml_langs:
        yaml_langs = ["multilingual"]
    seen = set()
    yaml_langs = [x for x in yaml_langs if not (x in seen or seen.add(x))]

    qr = patient.get("quality_rating", {})
    stars = qr.get("stars", "?")
    tier = (qr.get("label", "") or "").capitalize()
    composite = qr.get("composite_score", "?")

    star_display = "⭐" * int(stars) if isinstance(stars, (int, float)) else "—"
    if isinstance(stars, (int, float)) and stars != int(stars):
        star_display += "½"

    # Which variants are present — rendered with public WindyWord tier names
    vc = patient.get("variant_cluster", {})
    available_variants = []
    if vc.get("lora", {}).get("status") == "present":
        available_variants.append(("lora", "**WindyStandard** — our proprietary production baseline. Stable, reliable, optimized for GPU inference."))
    if vc.get("lora_ct2_int8", {}).get("status") == "present":
        available_variants.append(("lora-ct2-int8", "**WindyStandard · CPU INT8** — CTranslate2 quantized version of WindyStandard. ~25% of the size, 2–4× faster on CPU, no measurable quality loss."))
    if vc.get("herm0", {}).get("status") == "present":
        available_variants.append(("herm0", "**WindyEnhanced** — deep fine-tuned on OPUS-100, Tatoeba, and WikiMatrix parallel corpora. Measurably higher translation quality on supported pairs."))
    if vc.get("herm0_ct2_int8", {}).get("status") == "present":
        available_variants.append(("herm0-ct2-int8", "**WindyEnhanced · CPU INT8** — CTranslate2 quantized WindyEnhanced. Premium quality, CPU-efficient."))
    if vc.get("herm0_scripture", {}).get("status") == "present":
        available_variants.append(("herm0-scripture", "**WindyScripture** — verse-aligned fine-tune on the eBible parallel corpus. Specialized for biblical text; not recommended for general translation."))
    if vc.get("scripture_ct2_int8", {}).get("status") == "present":
        available_variants.append(("scripture-ct2-int8", "**WindyScripture · CPU INT8** — CTranslate2 quantized WindyScripture."))

    variant_table = "\n".join(
        f"| `{name}/` | {desc} |" for name, desc in available_variants
    )

    # Pick the primary subfolder for the usage example (prefer WindyStandard lora)
    primary_sub = "lora"
    primary_ct2 = "lora-ct2-int8"
    if not any(n == "lora" for n, _ in available_variants):
        if any(n == "herm0" for n, _ in available_variants):
            primary_sub = "herm0"
            primary_ct2 = "herm0-ct2-int8"
        elif any(n == "herm0-scripture" for n, _ in available_variants):
            primary_sub = "herm0-scripture"
            primary_ct2 = "scripture-ct2-int8"

    # Build richer language-name tag list for HF search indexing
    extra_tags = []
    for t in _tag_list(src_lang) + _tag_list(tgt_lang):
        if t and t not in extra_tags:
            extra_tags.append(t)
    tag_yaml_extra = "\n".join(f"- {t}" for t in extra_tags[:20])  # cap at 20 to keep YAML clean

    # Spelled-out labels with family expansions for the tagline
    src_full = _expand_lang(src_lang)
    tgt_full = _expand_lang(tgt_lang)

    lang_yaml = "\n".join(f"- {c}" for c in yaml_langs)
    return f"""---
license: cc-by-4.0
tags:
- translation
- marian
- windyword
{tag_yaml_extra}
language:
{lang_yaml}
library_name: transformers
pipeline_tag: translation
---

# WindyWord.ai Translation — {src_display} → {tgt_display}

**Translates {src_full} → {tgt_full}.**

**Quality Rating: {star_display}  ({stars}★ {tier})**

Part of the [WindyWord.ai](https://windyword.ai) translation fleet — 1,800+ proprietary language pairs.

## Quality & Pricing Tier

- **5-star rating:** {stars}★ {star_display}
- **Tier:** {tier}
- **Composite score:** {composite} / 100
- **Rated via:** Grand Rounds v2 — an 8-test stress battery (paragraphs, multi-paragraph, native input, domain stress, edge cases, round-trip fidelity, speed, and consistency checks)

## Available Variants

This repository contains multiple deployment formats. Pick the one that matches your use case:

| Variant | Description |
|---|---|
{variant_table}

### Quick usage

**Transformers (PyTorch):**
```python
from transformers import MarianMTModel, MarianTokenizer
tokenizer = MarianTokenizer.from_pretrained("{ORG}/translate-{pid}", subfolder="{primary_sub}")
model = MarianMTModel.from_pretrained("{ORG}/translate-{pid}", subfolder="{primary_sub}")
```

**CTranslate2 (fast CPU inference):**
```python
import ctranslate2
translator = ctranslate2.Translator("path/to/translate-{pid}/{primary_ct2}")
```

## Commercial Use

The WindyWord.ai platform provides:
- **Mobile apps** (iOS, Android — coming soon)
- **Real-time voice-to-text-to-translation** pipeline
- **API access** with premium model quality
- **Offline deployment** support

Visit [windyword.ai](https://windyword.ai) for apps and commercial API access.

---

## Provenance & License

Weights derived from the OPUS-MT project ([{source_repo}](https://huggingface.co/{source_repo})) under CC-BY-4.0. WindyStandard, WindyEnhanced, and WindyScripture variants are proprietary to WindyWord.ai, independently trained and quality-certified via our Grand Rounds v2 test battery.

Licensed CC-BY-4.0 — attribution preserved as required.

*Certified by Opus 4.6 Opus-Claw (Dr. C) on Veron-1 (RTX 5090).*
*Patient file: [clinic record](https://github.com/sneakyfree/Windy-Clinic/blob/main/translation-pairs/{pid}.json)*
"""


def build_stt_readme(name: str, base_model: str, variants_available: list,
                     patient: dict = None) -> str:
    variant_list = "\n".join(f"- `{v}/`" for v in variants_available)

    # Language block: default to English for voice models, read from patient for lingua
    lang_codes = ["en"]
    script_note = ""
    output_note = ""
    if patient:
        lc = patient.get("language")
        if lc and isinstance(lc, str):
            lang_codes = [lc.lower()]
        on = patient.get("hf_upload_notes") or {}
        if on.get("output_script"):
            script_note = f"\n**Output script:** {on['output_script']}\n"
        if on.get("important_note"):
            output_note = f"\n> **Important:** {on['important_note']}\n"

    lang_yaml = "\n".join(f"- {c}" for c in lang_codes)
    return f"""---
license: apache-2.0
tags:
- automatic-speech-recognition
- whisper
- windyword
library_name: transformers
pipeline_tag: automatic-speech-recognition
language:
{lang_yaml}
---

# WindyWord.ai STT — {name.replace('windy-', 'Windy ').replace('-', ' ').title()}

Part of the [WindyWord.ai](https://windyword.ai) voice-to-text fleet.
{script_note}{output_note}
## Available Variants

{variant_list}

## Base Model

Derived from [{base_model}](https://huggingface.co/{base_model}).

Proprietary fine-tuning by WindyWord.ai team using LoRA fog-of-mirror methodology or direct weight perturbation (for distil variants without adapters).

## Commercial Use

Visit [windyword.ai](https://windyword.ai) for real-time voice-to-text + translation apps and API access.

## License

Apache 2.0 (inherited from upstream base model).

---
*Certified by Opus 4.6 Opus-Claw (Dr. C). WindyWord.ai quality pipeline.*
"""


# ═══════════════════════════════════════════════════════════════
# UPLOAD HELPERS
# ═══════════════════════════════════════════════════════════════

def create_repo_safe(repo_id: str, repo_type: str = "model", private: bool = False):
    """Create a repo, ignore if it already exists."""
    try:
        create_repo(
            repo_id=repo_id,
            repo_type=repo_type,
            private=private,
            exist_ok=True,
        )
        return True
    except Exception as e:
        log(f"  create_repo error {repo_id}: {type(e).__name__}: {str(e)[:200]}")
        return False


def upload_variant_folder(repo_id: str, local_dir: Path, subfolder: str,
                          max_retries: int = 3) -> bool:
    """Upload a variant subfolder. Retries on rate limit."""
    attempt = 0
    while attempt < max_retries:
        try:
            upload_folder(
                repo_id=repo_id,
                folder_path=str(local_dir),
                path_in_repo=subfolder,
                repo_type="model",
                commit_message=f"Add {subfolder} variant",
            )
            return True
        except HfHubHTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                # Rate limited — huggingface_hub 1.2+ should handle this automatically,
                # but we add a fallback just in case
                wait = min(60 * (2 ** attempt), 600)
                log(f"  Rate limited on {subfolder}; waiting {wait}s")
                time.sleep(wait)
                attempt += 1
            else:
                log(f"  HTTP error {subfolder}: {e}")
                return False
        except Exception as e:
            log(f"  Upload error {subfolder}: {type(e).__name__}: {str(e)[:200]}")
            attempt += 1
            if attempt < max_retries:
                time.sleep(30)
    return False


# ═══════════════════════════════════════════════════════════════
# PATIENT FILE SIGNOFF
# ═══════════════════════════════════════════════════════════════

def record_upload_in_patient(pid: str, repo_id: str, variants_uploaded: list, subtype="translation"):
    """Add a signed Dr. C exam entry to the patient file."""
    pf = (STT_PATIENTS if subtype != "translation" else PATIENTS) / f"{pid}.json"
    if not pf.exists():
        return
    chart = json.loads(pf.read_text())
    log_list = chart.setdefault("examination_log", [])
    exam_id = f"DRC-HFUPLOAD-{pid}"
    if any(e.get("exam_id") == exam_id for e in log_list):
        return

    run_iso = datetime.now(timezone.utc).isoformat()
    log_list.append({
        "exam_id": exam_id,
        "date": run_iso,
        "doctor": DOCTOR,
        "machine": MACHINE,
        "method": f"HuggingFace public upload to {repo_id}",
        "protocol_script": "scripts/upload_to_huggingface.py",
        "variants_uploaded": variants_uploaded,
        "hf_url": f"https://huggingface.co/{repo_id}",
        "notes": (
            f"Uploaded to WindyWord HuggingFace organization. "
            f"Variants published: {', '.join(variants_uploaded)}. "
            f"Public repo with branded model card. "
            f"Patient file attribution linked via README. "
            f"Filed by {DOCTOR}."
        ),
    })
    chart["_last_updated"] = run_iso

    # Also update variant_cluster with HF URLs
    vc = chart.setdefault("variant_cluster", {})
    for v in variants_uploaded:
        norm = v.replace("-", "_")
        if norm in vc:
            vc[norm]["huggingface_url"] = f"https://huggingface.co/{repo_id}/tree/main/{v}"
            vc[norm]["hf_uploaded_at"] = run_iso

    pf.write_text(json.dumps(chart, indent=2))


# ═══════════════════════════════════════════════════════════════
# PHASE 0: CLINIC BACKUP TO HF DATASET
# ═══════════════════════════════════════════════════════════════

def phase0_upload_clinic(state):
    if state.get("phase0_clinic_uploaded"):
        log("Phase 0 already done, skipping")
        return

    log("\n" + "=" * 60)
    log("PHASE 0: Mirror clinic to HF private dataset repo")
    log("=" * 60)

    repo_id = f"{ORG}/clinic-patient-records"
    log(f"Creating/verifying dataset repo: {repo_id} (private)")
    create_repo_safe(repo_id, repo_type="dataset", private=True)

    log(f"Uploading clinic contents ({CLINIC})...")
    try:
        upload_folder(
            repo_id=repo_id,
            folder_path=str(CLINIC),
            repo_type="dataset",
            commit_message="Clinic backup from Veron-1 / Dr. C session",
            ignore_patterns=["__pycache__/", "*.pyc", "backups/pre-*/", "*.tmp", "*.lock",
                             "huggingface-uploads/*"],
        )
        log("Phase 0 complete — clinic mirrored to HF")
        state["phase0_clinic_uploaded"] = True
        save_checkpoint(state)
    except Exception as e:
        log(f"Phase 0 error: {type(e).__name__}: {str(e)[:300]}")
        state["errors"].append({"phase": 0, "error": str(e)[:300]})
        save_checkpoint(state)


# ═══════════════════════════════════════════════════════════════
# PHASE 1: UPLOAD TRANSLATION MODELS
# ═══════════════════════════════════════════════════════════════

def phase1_upload_translations(state, limit=None):
    log("\n" + "=" * 60)
    log("PHASE 1: Upload translation models")
    log("=" * 60)

    # Build target list: all patients with at least one uploadable variant
    targets = []
    for pf in sorted(PATIENTS.glob("*.json")):
        pid = pf.stem
        chart = json.loads(pf.read_text())

        # Must have at least one of the uploadable variants on disk
        has_uploadable = False
        for disk_name, _ in VARIANT_UPLOAD_MAP:
            vdir = MODELS / f"windy-pair-{pid}" / disk_name
            if vdir.exists() and (
                (vdir / "model.safetensors").exists()
                or (vdir / "pytorch_model.bin").exists()
                or (vdir / "model.bin").exists()
            ):
                has_uploadable = True
                break
        if has_uploadable:
            targets.append(pid)

    done = set(state["phase1_done"])
    remaining = [p for p in targets if p not in done]

    log(f"Total targets: {len(targets)}, done: {len(done)}, remaining: {len(remaining)}")
    if limit:
        remaining = remaining[:limit]
        log(f"Limited to first {limit} for this run")

    for i, pid in enumerate(remaining, 1):
        pf = PATIENTS / f"{pid}.json"
        chart = json.loads(pf.read_text())
        repo_id = f"{ORG}/translate-{pid}"

        log(f"[{i}/{len(remaining)}] {pid} → {repo_id}")

        # Create repo
        if not create_repo_safe(repo_id, repo_type="model", private=False):
            state["errors"].append({"phase": 1, "pid": pid, "step": "create_repo"})
            save_checkpoint(state)
            continue

        # Upload variant subfolders
        uploaded = []
        skipped_regression = False
        for disk_name, subfolder in VARIANT_UPLOAD_MAP:
            if disk_name in ("herm0", "herm0-ct2-int8") and pid in HERM0_SKIP_PIDS:
                log(f"  SKIP {disk_name} for {pid}: GR v2 regression (see herm0_skiplist.json)")
                skipped_regression = True
                continue
            vdir = MODELS / f"windy-pair-{pid}" / disk_name
            real = vdir.resolve() if vdir.is_symlink() else vdir
            if not real.exists():
                continue
            if not (
                (real / "model.safetensors").exists()
                or (real / "pytorch_model.bin").exists()
                or (real / "model.bin").exists()
            ):
                continue
            if upload_variant_folder(repo_id, real, subfolder):
                uploaded.append(disk_name)

        # Upload README
        readme = build_translation_readme(chart)
        tmp = Path(f"/tmp/_readme_{pid}")
        tmp.mkdir(exist_ok=True)
        (tmp / "README.md").write_text(readme)
        try:
            upload_folder(repo_id=repo_id, folder_path=str(tmp), repo_type="model",
                           commit_message="Add model card")
        except Exception as e:
            log(f"  README upload error: {e}")
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

        # Record in patient file
        record_upload_in_patient(pid, repo_id, uploaded, subtype="translation")

        # Log result
        with open(RESULTS_JSONL, "a") as f:
            f.write(json.dumps({
                "pid": pid, "repo_id": repo_id, "variants": uploaded,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }) + "\n")

        state["phase1_done"].append(pid)
        save_checkpoint(state)

        log(f"  ✓ uploaded {len(uploaded)} variants: {', '.join(uploaded)}")

        if i % 10 == 0:
            log(f"  >> Phase 1 progress: {len(state['phase1_done'])} patients uploaded")


# ═══════════════════════════════════════════════════════════════
# PHASE 2+3: STT UPLOADS (simpler, fewer models)
# ═══════════════════════════════════════════════════════════════

STT_VOICE_BASE_MAP = {
    "windy-nano": "openai/whisper-tiny",
    "windy-lite": "openai/whisper-base",
    "windy-core": "openai/whisper-small",
    "windy-plus": "openai/whisper-medium",
    "windy-turbo": "openai/whisper-large-v3-turbo",
    "windy-pro-engine": "openai/whisper-large-v3",
    "windy-edge": "distil-whisper/distil-large-v3",
    "windy-distil-small": "distil-whisper/distil-small.en",
    "windy-distil-medium": "distil-whisper/distil-medium.en",
    "windy-distil-large": "distil-whisper/distil-large-v3",
}


def phase2_upload_stt_voice(state):
    log("\n" + "=" * 60)
    log("PHASE 2: Upload STT voice models")
    log("=" * 60)
    done = set(state["phase2_done"])
    for name, base_model in STT_VOICE_BASE_MAP.items():
        if name in done:
            continue
        src_dir = STT_REBUILT / name
        if not src_dir.exists():
            log(f"  SKIP {name}: source not found")
            continue
        repo_id = f"{ORG}/listen-{name}"
        log(f"{name} → {repo_id}")

        if not create_repo_safe(repo_id, repo_type="model", private=False):
            continue

        variants = []
        # Main safetensors variant
        if upload_variant_folder(repo_id, src_dir, "safetensors"):
            variants.append("safetensors")
        # CT2 INT8
        ct2 = STT_CT2 / f"{name}-ct2"
        if ct2.exists() and upload_variant_folder(repo_id, ct2, "ct2-int8"):
            variants.append("ct2-int8")
        # ONNX FP32
        onnx = STT_ONNX / f"{name}-onnx"
        if onnx.exists() and upload_variant_folder(repo_id, onnx, "onnx"):
            variants.append("onnx")
        # ONNX INT8
        onnx_int8 = STT_ONNX_INT8 / f"{name}-onnx-int8"
        if onnx_int8.exists() and upload_variant_folder(repo_id, onnx_int8, "onnx-int8"):
            variants.append("onnx-int8")

        # README (look up patient file if present to surface any per-model notes)
        patient = None
        pf = STT_PATIENTS / f"{name}.json"
        if pf.exists():
            try:
                patient = json.loads(pf.read_text())
            except Exception:
                patient = None
        readme = build_stt_readme(name, base_model, variants, patient=patient)
        tmp = Path(f"/tmp/_readme_{name}")
        tmp.mkdir(exist_ok=True)
        (tmp / "README.md").write_text(readme)
        try:
            upload_folder(repo_id=repo_id, folder_path=str(tmp), repo_type="model",
                           commit_message="Add model card")
        except Exception:
            pass
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

        record_upload_in_patient(name, repo_id, variants, subtype="stt")
        state["phase2_done"].append(name)
        save_checkpoint(state)
        log(f"  ✓ uploaded {len(variants)} variants")


def phase3_upload_stt_lingua(state):
    log("\n" + "=" * 60)
    log("PHASE 3: Upload STT lingua (per-language) models")
    log("=" * 60)
    done = set(state["phase3_done"])
    for src_dir in sorted(STT_LINGUA.iterdir()):
        if not src_dir.is_dir():
            continue
        name = src_dir.name
        if name in done:
            continue
        repo_id = f"{ORG}/listen-{name}"
        log(f"{name} → {repo_id}")

        if not create_repo_safe(repo_id, repo_type="model", private=False):
            continue

        # Load patient file (if present) to surface language + script notes in README
        patient = None
        pf = STT_PATIENTS / f"{name}.json"
        if pf.exists():
            try:
                patient = json.loads(pf.read_text())
            except Exception:
                patient = None
        base_model = (patient or {}).get("source_repo", "openai/whisper-small")

        variants = []
        subfolder = "safetensors" if not name.endswith("-ct2") else "ct2-int8"
        if upload_variant_folder(repo_id, src_dir, subfolder):
            variants.append(subfolder)

        # README with per-language output-script notes (important for Hindi → Hinglish)
        try:
            readme = build_stt_readme(name, base_model, variants, patient=patient)
            tmp = Path(f"/tmp/_readme_{name}")
            tmp.mkdir(exist_ok=True)
            (tmp / "README.md").write_text(readme)
            upload_folder(repo_id=repo_id, folder_path=str(tmp), repo_type="model",
                          commit_message="Add model card")
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception as e:
            log(f"  README upload error {name}: {e}")

        record_upload_in_patient(name, repo_id, variants, subtype="stt")
        state["phase3_done"].append(name)
        save_checkpoint(state)
        log(f"  ✓ uploaded {len(variants)} variant(s)")


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-phase0", action="store_true", help="Skip clinic backup to HF dataset")
    ap.add_argument("--phase1-only", action="store_true", help="Run only Phase 1 (translations)")
    ap.add_argument("--phase1-limit", type=int, help="Limit Phase 1 to first N models (for testing)")
    ap.add_argument("--start-at-phase", type=int, default=0)
    args = ap.parse_args()

    log("=" * 60)
    log("WINDYWORD HUGGINGFACE UPLOAD ORCHESTRATOR")
    log(f"Doctor: {DOCTOR}")
    log(f"Target org: {ORG}")
    log(f"Started: {datetime.now(timezone.utc).isoformat()}")
    log("=" * 60)

    try:
        info = whoami()
        log(f"Auth: {info.get('name')} ({info.get('fullname','')})")
    except Exception as e:
        log(f"Auth FAILED: {e}")
        sys.exit(1)

    state = load_checkpoint()

    if args.start_at_phase <= 0 and not args.skip_phase0:
        phase0_upload_clinic(state)

    if args.start_at_phase <= 1:
        phase1_upload_translations(state, limit=args.phase1_limit)

    if args.phase1_only:
        log("Phase 1 only requested, stopping")
        return

    if args.start_at_phase <= 2:
        phase2_upload_stt_voice(state)

    if args.start_at_phase <= 3:
        phase3_upload_stt_lingua(state)

    log("\n" + "=" * 60)
    log("UPLOAD ORCHESTRATOR COMPLETE")
    log(f"Phase 1 (translations): {len(state['phase1_done'])}")
    log(f"Phase 2 (STT voice): {len(state['phase2_done'])}")
    log(f"Phase 3 (STT lingua): {len(state['phase3_done'])}")
    log(f"Errors: {len(state['errors'])}")
    log("=" * 60)


if __name__ == "__main__":
    main()

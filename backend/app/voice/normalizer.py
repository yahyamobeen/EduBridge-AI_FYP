"""Text normalization and sentence splitting for speech synthesis (TTS).

Transforms raw LLM / RAG markdown responses into clean, natural speakable prose:
- Strips markdown formatting (headers, bold, italics, code spans, lists).
- Strips textbook citations like (p155), [1], and figure markers.
- Expands common science & math notation (equations, units, chemical symbols).
- Splits into natural, balanced sentences for low-latency streaming audio.
"""

from __future__ import annotations

import re

# Common math and physics units expansion in English/Urdu contexts
UNIT_REPLACEMENTS = [
    (r"\b(\d+)\s*m/s\^2\b", r"\1 meters per second squared"),
    (r"\b(\d+)\s*m/s\b", r"\1 meters per second"),
    (r"\b(\d+)\s*km/h\b", r"\1 kilometers per hour"),
    (r"\b(\d+)\s*kg\b", r"\1 kilograms"),
    (r"\b(\d+)\s*cm\b", r"\1 centimeters"),
    (r"\b(\d+)\s*mm\b", r"\1 millimeters"),
    (r"\b(\d+)\s*m\b", r"\1 meters"),
    (r"\b(\d+)\s*s\b", r"\1 seconds"),
    (r"\b(\d+)\s*N\b", r"\1 Newtons"),
    (r"\b(\d+)\s*J\b", r"\1 Joules"),
    (r"\b(\d+)\s*W\b", r"\1 Watts"),
    (r"\b(\d+)\s*Hz\b", r"\1 Hertz"),
    (r"\b(\d+)\s*K\b", r"\1 Kelvin"),
    (r"\b(\d+)\s*°C\b", r"\1 degrees Celsius"),
]

# Science formula and equation symbols
SYMBOL_REPLACEMENTS = [
    (r"=", " equals "),
    (r"\+", " plus "),
    (r"±", " plus or minus "),
    (r"×", " multiplied by "),
    (r"÷", " divided by "),
    (r"≈", " approximately "),
    (r"≠", " not equal to "),
    (r"≤", " less than or equal to "),
    (r"≥", " greater than or equal to "),
    (r"%", " percent "),
    (r"\bH2O\b", "H 2 O"),
    (r"\bCO2\b", "C O 2"),
    (r"\bO2\b", "O 2"),
    (r"\bNaCl\b", "N A C l"),
]


def is_arabic_script(text: str) -> bool:
    """Returns True if the text predominantly contains Arabic/Urdu script."""
    arabic_chars = len(re.findall(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]", text))
    latin_chars = len(re.findall(r"[a-zA-Z]", text))
    return arabic_chars > latin_chars


def clean_markdown_for_speech(text: str) -> str:
    """Strips markdown syntax, citations, and non-speakable elements from text."""
    if not text:
        return ""

    # Remove code blocks ```...```
    cleaned = re.sub(r"```[\s\S]*?```", "", text)
    # Remove inline code `...`
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    # Remove page citations: (p155), (p042), (page 12), [1], [2]
    cleaned = re.sub(r"\((?:p\d{1,4}|page\s*\d{1,4})\)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[\d+\]", "", cleaned)
    # Remove markdown image syntax ![alt](url)
    cleaned = re.sub(r"!\[.*?\]\(.*?\)", "", cleaned)
    # Convert markdown links [text](url) -> text
    cleaned = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", cleaned)
    # Remove markdown headings (# H1, ## H2, etc.)
    cleaned = re.sub(r"^\s*#{1,6}\s+", "", cleaned, flags=re.MULTILINE)
    # Remove blockquotes >
    cleaned = re.sub(r"^\s*>\s*", "", cleaned, flags=re.MULTILINE)
    # Remove bold and italic markers: **text**, *text*, __text__, _text_
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*([^*]+)\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    cleaned = re.sub(r"_([^_]+)_", r"\1", cleaned)
    # Remove list bullet markers (*, -, +)
    cleaned = re.sub(r"^\s*[-*+]\s+", "", cleaned, flags=re.MULTILINE)
    # Remove numbered lists (1. , 2. )
    cleaned = re.sub(r"^\s*\d+\.\s+", "", cleaned, flags=re.MULTILINE)
    # Strip HTML tags
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    # Strip LaTeX math markers $...$ and $$...$$
    cleaned = re.sub(r"\$\$([\s\S]*?)\$\$", r"\1", cleaned)
    cleaned = re.sub(r"\$([^$]+)\$", r"\1", cleaned)

    # Expand physics units
    for pattern, repl in UNIT_REPLACEMENTS:
        cleaned = re.sub(pattern, repl, cleaned)

    # Expand math symbols
    for pattern, repl in SYMBOL_REPLACEMENTS:
        cleaned = re.sub(pattern, repl, cleaned)

    # Normalize whitespace
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{2,}", "\n", cleaned)
    return cleaned.strip()


def split_into_sentences(text: str) -> list[str]:
    """Splits cleaned text into balanced sentences for streaming TTS playback.

    Handles English punctuation (., !, ?) and Urdu full stops (۔).
    """
    cleaned = clean_markdown_for_speech(text)
    if not cleaned:
        return []

    # Split on sentence boundaries: periods, exclamation marks, question marks, Urdu full stop (۔)
    raw_sentences = re.split(r"(?<=[.!?۔\n])\s+", cleaned)
    sentences: list[str] = []

    for s in raw_sentences:
        s = s.strip()
        if not s:
            continue
        # If sentence is extremely long (>250 chars) and has comma/semicolon, split on comma
        if len(s) > 250 and ("," in s or "،" in s):
            sub_parts = re.split(r"(?<=[,،;])\s+", s)
            current = ""
            for p in sub_parts:
                if len(current) + len(p) < 200:
                    current = f"{current} {p}".strip()
                else:
                    if current:
                        sentences.append(current)
                    current = p
            if current:
                sentences.append(current)
        else:
            sentences.append(s)

    return sentences


# Word-level Roman Urdu -> Urdu script overrides.
#
# Only the words that carry the sentence's grammar are converted. An unknown
# Latin word (a technical term such as "force" or "Newton") is deliberately left
# in Latin so an Urdu voice reads it with English phonetics instead of mangling
# it. Ambiguous English words that are also common in Roman Urdu ("the", "do")
# are left out on purpose: converting them corrupts English phrases embedded in
# an otherwise Roman Urdu sentence.
_ROMAN_TO_URDU_OVERRIDES = {
    "kya": "کی",
    "kyun": "کیوں",
    "kyon": "کیوں",
    "kyunke": "کیونکہ",
    "hai": "ہے",
    "hain": "ہیں",
    "nahin": "نہیں",
    "nahi": "نہیں",
    "aur": "اور",
    "mein": "میں",
    "main": "میں",
    "se": "سے",
    "ko": "کو",
    "ka": "کا",
    "ki": "کی",
    "ke": "کے",
    "par": "پر",
    "yeh": "یہ",
    "ye": "یہ",
    "woh": "وہ",
    "wo": "وہ",
    "jo": "جو",
    "keh": "کہ",
    "bhi": "بھی",
    "na": "نہ",
    "to": "تو",
    "hi": "ہی",
    "ho": "ہو",
    "hota": "ہوتا",
    "hoti": "ہوتی",
    "hote": "ہوتے",
    "ja": "جا",
    "kaise": "کیسے",
    "kab": "کب",
    "kahan": "کہاں",
    "kaun": "کون",
    "kitna": "کتنا",
    "kitni": "کتنی",
    "bohat": "بہت",
    "bohot": "بہت",
    "bahut": "بہت",
    "acha": "اچھا",
    "achha": "اچھا",
    "hawa": "ہوا",
    "mujhe": "مجھے",
    "madad": "مدد",
    "chahiye": "چاہیے",
    "tum": "تم",
    "hum": "ہم",
    "aap": "آپ",
    "theek": "ٹھیک",
    "shukriya": "شکریہ",
    "karo": "کرو",
    "karna": "کرنا",
    "karta": "کرتا",
    "karti": "کرتی",
    "karte": "کرتے",
    "samajh": "سمجھ",
    "batao": "بتاؤ",
    "bata": "بتا",
    "dekho": "دیکھو",
    "suno": "سنو",
    "padho": "پڑھو",
    "likho": "لکھو",
    "sakta": "سکتا",
    "sakti": "سکتی",
    "sakte": "سکتے",
    "raha": "رہا",
    "rahi": "رہی",
    "rahe": "رہے",
    "tha": "تھا",
    "thi": "تھی",
    "ek": "ایک",
    "teen": "تین",
    "char": "چار",
    "paanch": "پانچ",
    "abhi": "ابھی",
    "phir": "پھر",
    "lekin": "لیکن",
    "magar": "مگر",
    "isliye": "اس لیے",
    "wala": "والا",
    "wali": "والی",
    "wale": "والے",
    "kuch": "کچھ",
    "sab": "سب",
    "zyada": "زیادہ",
    "kam": "کم",
}

# Used by `select_voice` to recognise Roman Urdu when the caller supplied no
# language hint. Derived from the override table so the two can never drift.
ROMAN_URDU_MARKERS = frozenset(_ROMAN_TO_URDU_OVERRIDES)


def roman_urdu_to_urdu(text: str) -> str:
    """Convert Roman Urdu text to Urdu script.

    Uses word-level overrides for common words. Unknown Latin words pass through
    unchanged, so English technical vocabulary keeps its English pronunciation
    under an Urdu voice. This is a practical approximation, not a full
    transliteration engine.
    """
    if not text:
        return text

    urdu_words: list[str] = []
    for word in text.split():
        # Strip punctuation for the lookup, then re-attach it unchanged.
        stripped = word.strip(".,!?;:()")
        if stripped.lower() in _ROMAN_TO_URDU_OVERRIDES:
            urdu_word = _ROMAN_TO_URDU_OVERRIDES[stripped.lower()]
            prefix = word[: len(word) - len(word.lstrip(".,!?;:()"))]
            suffix = word[len(word.rstrip(".,!?;:()")) :]
            urdu_words.append(prefix + urdu_word + suffix)
        else:
            urdu_words.append(word)

    return " ".join(urdu_words)

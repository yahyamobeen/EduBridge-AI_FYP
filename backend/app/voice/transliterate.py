"""Basic Arabic/Urdu script to Roman Urdu transliteration.

This is a character-level mapping — not a linguistic transliteration — so
quality is limited (e.g., missing vowels in Urdu script produce consonant-
heavy output). It is sufficient for producing consistent Latin-script
output from mixed-language Whisper transcriptions.
"""

from __future__ import annotations

# Urdu/Arabic character -> Roman equivalent
_URDU_TO_ROMAN = {
    "ا": "a",
    "آ": "aa",
    "ب": "b",
    "پ": "p",
    "ت": "t",
    "ٹ": "t",
    "ث": "s",
    "ج": "j",
    "چ": "ch",
    "ح": "h",
    "خ": "kh",
    "د": "d",
    "ڈ": "d",
    "ذ": "z",
    "ر": "r",
    "ڑ": "r",
    "ز": "z",
    "ژ": "zh",
    "س": "s",
    "ش": "sh",
    "ص": "s",
    "ض": "z",
    "ط": "t",
    "ظ": "z",
    "ع": "a",
    "غ": "gh",
    "ف": "f",
    "ق": "q",
    "ک": "k",
    "گ": "g",
    "ل": "l",
    "م": "m",
    "ن": "n",
    "ں": "n",
    "و": "w",
    "ہ": "h",
    "ھ": "h",
    "ی": "y",
    "ے": "e",
    "ئ": "y",
    "ؤ": "w",
    "ء": "'",
    "أ": "a",
    "إ": "i",
    "ة": "h",
    "َ": "a",
    "ُ": "u",
    "ِ": "i",
    "ّ": "",
    "ْ": "",
    "ٰ": "a",
    "ٔ": "",
    "ٕ": "",
}

# Common Urdu words that need better transliteration than char-by-char
_WORD_OVERRIDES = {
    "کیا": "kya",
    "ہے": "hai",
    "ہیں": "hain",
    "نہیں": "nahin",
    "اور": "aur",
    "میں": "mein",
    "سے": "se",
    "کو": "ko",
    "کا": "ka",
    "کی": "ki",
    "کے": "ke",
    "پر": "par",
    "یہ": "yeh",
    "وہ": "woh",
    "جو": "jo",
    "کہ": "keh",
    "بھی": "bhi",
    "نہ": "na",
    "تو": "to",
    "ہی": "hi",
    "ہو": "ho",
    "جا": "ja",
    "آ": "aa",
    "گا": "ga",
    "گی": "gi",
    "گے": "ge",
    "تھا": "tha",
    "تھی": "thi",
    "تھے": "the",
    "ہوا": "hua",
    "ہوئی": "hui",
    "ہوئے": "hue",
    "لیے": "liye",
    "لئے": "liye",
    "واپس": "wapas",
    "پاسکل": "Pascal",
    "نیوٹن": "Newton",
    "انرجی": "energy",
    "فورس": "force",
    "پریشر": "pressure",
    "قانون": "qanoon",
    "پہلا": "pehla",
    "حرکت": "harkat",
    "اثر": "asar",
    "قوت": "qoot",
    "دباؤ": "dabao",
    "حرارت": "hararat",
    "میٹر": "meter",
    "سیکنڈ": "second",
    "کلوگرام": "kilogram",
    "تم": "tum",
    "سکتے": "sakte",
    "لکھ": "likh",
    "انگریزی": "angrezi",
    "اردو": "urdu",
    "انداز": "andaz",
    "بوٹوں": "bolunga",
    "گئے": "gaye",
    "تمہارا": "tumhara",
    "شکریہ": "shukriya",
    "مدد": "madad",
    "سکتا": "sakta",
    "سکتی": "sakti",
    "ہوں": "hoon",
    "ہمارا": "hamara",
    "آپ": "aap",
    "آپکا": "aapka",
    "کر": "kar",
    "کرو": "karo",
    "کرنا": "karna",
    "کرتا": "karta",
    "کرتی": "karti",
    "کرتے": "karte",
    "کیسے": "kaise",
    "کیوں": "kyun",
    "کب": "kab",
    "کہاں": "kahan",
    "کون": "kaun",
    "کتنا": "kitna",
    "کیسی": "kaisi",
    "بہت": "bohat",
    "زیادہ": "ziyada",
    "کم": "kam",
    "اچھا": "acha",
    "برا": "bura",
    "بڑا": "bara",
    "چھوٹا": "chota",
    "نیا": "naya",
    "پرانا": "purana",
    "سچ": "sach",
    "جھوٹ": "jhoot",
    "پانی": "pani",
    "آگ": "aag",
    "زمین": "zameen",
    "سورج": "suraj",
    "چاند": "chaand",
    "ستارہ": "sitara",
    "انسان": "insaan",
    "جانور": "janwar",
    "پیڑ": "ped",
    "کتاب": "kitab",
    "قلم": "qalam",
    "کاغذ": "kagaz",
    "گھر": "ghar",
    "درخت": "darakht",
    "پہاڑ": "pahar",
    "دریا": "darya",
    "سمندر": "samundar",
    "آسمان": "aasman",
    "تھرموکپل": "thermocouple",
    "ہیٹ": "heat",
    "ٹمپریچر": "temperature",
}


def transliterate_to_roman(text: str) -> str:
    """Convert Arabic/Urdu script text to Roman Urdu (Latin script).

    English words and numbers pass through unchanged. Urdu words are
    transliterated using a character mapping with common-word overrides.
    """
    if not text:
        return text

    result = []
    for word in text.split():
        # Check if word is already Latin (English)
        if all(ord(c) < 128 for c in word.strip(".,!?;:()")):
            result.append(word)
            continue

        # Check word overrides
        clean = word.strip(".,!?;:()")
        if clean in _WORD_OVERRIDES:
            # Preserve punctuation
            prefix = word[: len(word) - len(word.lstrip(".,!?;:()"))]
            suffix = word[len(word.rstrip(".,!?;:()")) :]
            result.append(prefix + _WORD_OVERRIDES[clean] + suffix)
            continue

        # Character-by-character transliteration
        roman = ""
        for ch in word:
            roman += _URDU_TO_ROMAN.get(ch, ch)
        result.append(roman)

    return " ".join(result)


def has_arabic_script(text: str) -> bool:
    """Check if text contains Arabic/Urdu script characters."""
    return any(
        "\u0600" <= c <= "\u06ff"
        or "\u0750" <= c <= "\u077f"
        or "\ufb50" <= c <= "\ufdff"
        or "\ufe70" <= c <= "\ufeff"
        for c in text
    )

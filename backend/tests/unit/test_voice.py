"""Unit tests for the Voice module (Normalizer, TTS, and STT)."""

from app.voice.normalizer import (
    clean_markdown_for_speech,
    is_arabic_script,
    roman_urdu_to_urdu,
    split_into_sentences,
)
from app.voice.tts import (
    VOICE_ENGLISH_FEMALE,
    VOICE_ENGLISH_MALE,
    VOICE_URDU_FEMALE,
    VOICE_URDU_MALE,
    select_voice,
)


def test_is_arabic_script():
    assert is_arabic_script("نیوٹن کا قانون") is True
    assert is_arabic_script("What is Newton's law?") is False
    assert is_arabic_script("Newton کا قانون") is True  # Mixed Urdu text with English loan word


def test_clean_markdown_strips_syntax_and_citations():
    raw = "According to **Newton's Law** (p155), force is $F = ma$ where $a = 9.8 m/s^2$."
    cleaned = clean_markdown_for_speech(raw)
    assert "**" not in cleaned
    assert "(p155)" not in cleaned
    assert "equals" in cleaned
    assert "meters per second squared" in cleaned


def test_split_into_sentences_urdu_and_english():
    urdu_text = "یہ پہلا جملہ ہے۔ یہ دوسرا جملہ ہے۔ اور یہ تیسرا جملہ ہے۔"
    sentences = split_into_sentences(urdu_text)
    assert len(sentences) == 3
    assert sentences[0] == "یہ پہلا جملہ ہے۔"


def test_select_voice_routing():
    assert select_voice("یہ اردو متن ہے", preferred_gender="female") == VOICE_URDU_FEMALE
    assert select_voice("This is English text", preferred_gender="female") == VOICE_ENGLISH_FEMALE


def test_select_voice_honours_language_hint_and_gender():
    # An explicit hint wins over script detection: Roman Urdu must still get an
    # Urdu voice even though the text is Latin.
    assert select_voice("Pascal ka qanoon", language="roman") == VOICE_URDU_FEMALE
    assert select_voice("Pascal ka qanoon", language="roman", preferred_gender="male") == (
        VOICE_URDU_MALE
    )
    assert select_voice("What is force?", language="en", preferred_gender="male") == (
        VOICE_ENGLISH_MALE
    )
    assert select_voice("یہ اردو ہے", language="ur", preferred_gender="male") == VOICE_URDU_MALE


def test_roman_urdu_to_urdu_converts_common_words_and_keeps_technical_terms():
    converted = roman_urdu_to_urdu("Newton ka qanoon kya hai?")
    # Grammar words become Urdu script...
    assert "کی" in converted
    assert "ہے" in converted
    # ...but the English technical term is left in Latin so an Urdu voice reads
    # it with English phonetics rather than mangling it.
    assert "Newton" in converted


def test_roman_urdu_to_urdu_leaves_english_untouched():
    assert roman_urdu_to_urdu("The force is mass times acceleration") == (
        "The force is mass times acceleration"
    )


def test_voice_routes_require_auth():
    from fastapi.testclient import TestClient

    from app.main import create_app

    client = TestClient(create_app())
    assert client.post("/api/voice/transcribe").status_code == 401
    assert client.post("/api/voice/speak", json={"text": "hello"}).status_code == 401
    assert client.post("/api/voice/clean", json={"text": "hello"}).status_code == 401

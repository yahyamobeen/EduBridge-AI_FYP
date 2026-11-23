"""Text-to-Speech (TTS) service with dual-engine support and deterministic caching.

- Primary Urdu: Edge TTS (`ur-PK-AsadNeural` or `ur-PK-UzmaNeural`)
- Primary English: Edge TTS (`en-US-GuyNeural` or `en-US-JennyNeural`)
- Deterministic SHA-256 sentence disk caching in `backend/data/audio_cache/`
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import edge_tts

from app.voice.normalizer import ROMAN_URDU_MARKERS, is_arabic_script

logger = logging.getLogger("edubridge.voice.tts")

# Audio cache folder location
AUDIO_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "audio_cache"

# Edge TTS Pakistani Urdu and US English Neural voices
VOICE_URDU_MALE = "ur-PK-AsadNeural"
VOICE_URDU_FEMALE = "ur-PK-UzmaNeural"
VOICE_ENGLISH_MALE = "en-US-GuyNeural"
VOICE_ENGLISH_FEMALE = "en-US-JennyNeural"


def get_cache_path(text: str, voice: str) -> Path:
    """Generates a unique SHA-256 cache filepath for a sentence and voice."""
    AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f"{voice}::{text.strip()}".encode()).hexdigest()
    return AUDIO_CACHE_DIR / f"{key}.mp3"


def select_voice(text: str, preferred_gender: str = "female", language: str | None = None) -> str:
    """Selects the best voice based on script, language hint, and gender preference."""
    use_urdu = False
    if language in ("ur", "roman", "ur-Latn", "urdu"):
        use_urdu = True
    elif language == "en":
        use_urdu = False
    else:
        use_urdu = is_arabic_script(text)
        # Detect Roman Urdu by the same marker set the normalizer translates.
        if not use_urdu:
            words = set(text.lower().split())
            if words & ROMAN_URDU_MARKERS:
                use_urdu = True

    if use_urdu:
        return VOICE_URDU_FEMALE if preferred_gender == "female" else VOICE_URDU_MALE
    return VOICE_ENGLISH_FEMALE if preferred_gender == "female" else VOICE_ENGLISH_MALE


async def synthesize_sentence_to_bytes(text: str, voice: str | None = None) -> bytes:
    """Synthesizes a single sentence to MP3 audio bytes, using disk cache if available."""
    text = text.strip()
    if not text:
        return b""

    chosen_voice = voice or select_voice(text)
    cache_file = get_cache_path(text, chosen_voice)

    # 1. Return from disk cache if present
    if cache_file.exists() and cache_file.stat().st_size > 0:
        logger.debug("TTS Cache Hit for sentence: %s...", text[:30])
        return cache_file.read_bytes()

    # 2. Synthesize using Edge TTS
    logger.info("TTS Cache Miss - Synthesizing via %s for: %s...", chosen_voice, text[:30])
    communicate = edge_tts.Communicate(text, chosen_voice)
    audio_chunks = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_chunks.append(chunk["data"])

    audio_bytes = b"".join(audio_chunks)

    # 3. Save to disk cache (atomic: write to a temp file then rename, so a
    # crash mid-write can never leave a truncated MP3 that later gets served).
    if audio_bytes:
        try:
            tmp_file = cache_file.with_suffix(cache_file.suffix + ".tmp")
            tmp_file.write_bytes(audio_bytes)
            tmp_file.replace(cache_file)
        except Exception as e:
            logger.warning("Failed to write TTS cache file: %s", e)

    return audio_bytes

"""Speech-to-Text (STT) service using faster-whisper (CTranslate2 int8 on CPU).

Features:
- Loads WhisperModel once as a singleton or app state.
- Configured for Intel Core i5 CPU: `device="cpu"`, `compute_type="int8"`, `cpu_threads=4`.
- Voice Activity Detection (`vad_filter=True`) to suppress background noise.
- Supports optional language hints ('ur', 'en') to accelerate transcription.
"""

from __future__ import annotations

import io
import logging
from typing import Any, BinaryIO

logger = logging.getLogger("edubridge.voice.stt")

# Global singleton instance for STT model. Kept as Any so this module imports
# cleanly even when the optional `voice` extra (faster-whisper) is not
# installed; the dependency is pulled in lazily inside get_stt_model().
_STT_MODEL: Any = None
MODEL_SIZE = "small"


def get_stt_model() -> Any:
    """Returns the loaded WhisperModel singleton instance, initializing on first call."""
    global _STT_MODEL
    if _STT_MODEL is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover - depends on install
            raise RuntimeError(
                "faster-whisper is not installed; install the `voice` extra "
                "(`uv sync --extra voice`)."
            ) from exc
        logger.info(
            "Initializing faster-whisper (%s, compute_type=int8, cpu_threads=4)...",
            MODEL_SIZE,
        )
        _STT_MODEL = WhisperModel(
            model_size_or_path=MODEL_SIZE,
            device="cpu",
            compute_type="int8",
            cpu_threads=4,
        )
        logger.info("faster-whisper model loaded successfully.")
    return _STT_MODEL


def transcribe_audio_bytes(
    audio_data: bytes | BinaryIO,
    language_hint: str | None = None,
) -> tuple[str, str, float]:
    """Transcribes audio data bytes or binary stream into text.

    Args:
        audio_data: Raw audio bytes or binary stream (wav, mp3, webm, etc.)
        language_hint: Optional language code ('ur' or 'en')

    Returns:
        Tuple of (transcript_text, detected_language, duration_seconds)
    """
    model = get_stt_model()

    audio_stream = io.BytesIO(audio_data) if isinstance(audio_data, bytes) else audio_data

    # Valid language hints
    lang = language_hint if language_hint in ("ur", "en") else None

    logger.debug("Starting transcription with language hint: %s", lang)
    segments, info = model.transcribe(
        audio_stream,
        language=lang,
        beam_size=1,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
        condition_on_previous_text=False,
        no_speech_threshold=0.6,
    )

    text_parts = [segment.text.strip() for segment in segments]
    full_transcript = " ".join(text_parts).strip()

    logger.info(
        "Transcription complete: lang=%s, duration=%.1fs, chars=%d",
        info.language,
        info.duration,
        len(full_transcript),
    )
    return full_transcript, info.language, info.duration

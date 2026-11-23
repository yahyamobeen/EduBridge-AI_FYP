"""FastAPI routes for Voice (STT & TTS).

Endpoints:
- POST /api/voice/transcribe : Transcribes student voice question to text.
- POST /api/voice/speak      : Synthesizes clean text sentence to audio (MP3).
- POST /api/voice/clean      : Utility endpoint to preview cleaned text & sentences.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from app.auth.dependencies import AuthContext, require_role
from app.core.errors import model_unavailable, validation_error
from app.core.ratelimit import (
    VOICE_CLEAN_LIMIT,
    VOICE_SPEAK_LIMIT,
    VOICE_TRANSCRIBE_LIMIT,
    enforce,
)
from app.models.enums import UserRole
from app.voice.normalizer import clean_markdown_for_speech, roman_urdu_to_urdu, split_into_sentences
from app.voice.stt import transcribe_audio_bytes
from app.voice.tts import select_voice, synthesize_sentence_to_bytes

logger = logging.getLogger("edubridge.voice.routes")

router = APIRouter(prefix="/voice", tags=["voice"])

MAX_AUDIO_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB max audio size


class TranscribeResponse(BaseModel):
    transcript: str = Field(..., description="Transcribed student question")
    language: str = Field(..., description="Detected or confirmed language ('ur' or 'en')")
    duration_seconds: float = Field(..., description="Audio duration in seconds")


class SpeakRequest(BaseModel):
    text: str = Field(
        ..., min_length=1, max_length=1500, description="Sentence or passage to synthesize"
    )
    voice: str | None = Field(None, description="Explicit voice identifier (optional)")
    gender_preference: str | None = Field("female", description="'female' or 'male'")
    language: str | None = Field(None, description="Language hint: 'en', 'ur', or 'roman'")


class CleanTextResponse(BaseModel):
    original: str
    cleaned: str
    sentences: list[str]


@router.post(
    "/transcribe",
    response_model=TranscribeResponse,
    status_code=status.HTTP_200_OK,
    summary="Transcribe student voice audio to text using faster-whisper",
)
async def transcribe_audio(
    request: Request,
    ctx: Annotated[
        AuthContext, Depends(require_role(UserRole.student.value, UserRole.teacher.value))
    ],
    file: UploadFile = File(..., description="Recorded audio clip from microphone"),
    language_hint: str | None = Form(None, description="Optional 'ur' or 'en'"),
    target_script: str | None = Form(
        None, description="Optional 'latin' or 'arabic' — transliterate output"
    ),
) -> TranscribeResponse:
    """Receives student audio (webm, wav, mp3, ogg), transcribes with VAD, and returns text."""
    enforce(
        request, bucket="voice_transcribe", limit=VOICE_TRANSCRIBE_LIMIT, subject=str(ctx.user_id)
    )

    audio_bytes = await file.read()
    if not audio_bytes:
        raise validation_error(message="Uploaded audio file is empty.")

    if len(audio_bytes) > MAX_AUDIO_SIZE_BYTES:
        raise validation_error(message="Audio file exceeds 15 MB limit.")

    # Whisper is CPU-bound; run it off the event loop.
    try:
        transcript, lang, duration = await asyncio.to_thread(
            transcribe_audio_bytes, audio_bytes, language_hint=language_hint
        )
    except RuntimeError as exc:
        logger.error("STT dependency missing: %s", exc)
        raise model_unavailable(str(exc)) from exc
    except Exception as exc:
        logger.error("Error during speech transcription: %s", exc, exc_info=True)
        raise model_unavailable("Speech transcription failed.") from exc

    # Transliterate to target script if requested
    if target_script == "latin" and transcript:
        from app.voice.transliterate import has_arabic_script, transliterate_to_roman

        if has_arabic_script(transcript):
            transcript = transliterate_to_roman(transcript)

    return TranscribeResponse(
        transcript=transcript,
        language=lang,
        duration_seconds=round(duration, 2),
    )


@router.post(
    "/speak",
    summary="Synthesize text to speech audio stream (MP3) with disk caching",
)
async def speak_text(
    request: Request,
    payload: SpeakRequest,
    ctx: Annotated[
        AuthContext, Depends(require_role(UserRole.student.value, UserRole.teacher.value))
    ],
) -> Response:
    """Synthesizes text into high-fidelity speech (Edge TTS / cached MP3)."""
    enforce(request, bucket="voice_speak", limit=VOICE_SPEAK_LIMIT, subject=str(ctx.user_id))

    clean_text = clean_markdown_for_speech(payload.text)
    if not clean_text:
        raise validation_error(message="Text contained no speakable content after cleaning.")

    # Convert Roman Urdu to Urdu script for TTS (Edge TTS reads Urdu script correctly
    # with Urdu voices; Roman Urdu with Urdu voice gives English phonetics).
    if payload.language == "roman" or payload.language == "ur-Latn":
        clean_text = roman_urdu_to_urdu(clean_text)

    voice_id = payload.voice or select_voice(
        clean_text,
        preferred_gender=payload.gender_preference or "female",
        language=payload.language,
    )

    try:
        audio_bytes = await synthesize_sentence_to_bytes(clean_text, voice=voice_id)
    except Exception as exc:
        logger.error("Error during speech synthesis: %s", exc, exc_info=True)
        raise model_unavailable("Speech synthesis failed.") from exc

    if not audio_bytes:
        raise model_unavailable("Synthesizer produced empty audio.")

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-Voice-Used": voice_id,
        },
    )


@router.post(
    "/clean",
    response_model=CleanTextResponse,
    summary="Preview text cleaning and sentence splitting for a tutor response",
)
async def clean_text_endpoint(
    request: Request,
    payload: SpeakRequest,
    ctx: Annotated[
        AuthContext, Depends(require_role(UserRole.student.value, UserRole.teacher.value))
    ],
) -> CleanTextResponse:
    """Prepares and previews how a markdown response will be chunked into spoken sentences."""
    enforce(request, bucket="voice_clean", limit=VOICE_CLEAN_LIMIT, subject=str(ctx.user_id))

    cleaned = clean_markdown_for_speech(payload.text)
    sentences = split_into_sentences(payload.text)
    return CleanTextResponse(
        original=payload.text,
        cleaned=cleaned,
        sentences=sentences,
    )

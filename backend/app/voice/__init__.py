"""Voice package initialization for EduBridge AI."""

from app.voice.normalizer import clean_markdown_for_speech, is_arabic_script, split_into_sentences
from app.voice.tts import synthesize_sentence_to_bytes

__all__ = [
    "clean_markdown_for_speech",
    "is_arabic_script",
    "split_into_sentences",
    "synthesize_sentence_to_bytes",
]

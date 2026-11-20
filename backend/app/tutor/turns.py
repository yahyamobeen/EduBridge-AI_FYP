"""What kind of turn is this? (tdd.md §3.2a, §4.1)

Most turns in a real tutoring conversation are not retrieval turns. "Explain that again",
"why?", "give me a simpler one" carry no new topic, and re-retrieving on them costs the
hot path for nothing - and worse, can silently CHANGE the pages under a student in the
middle of an explanation, so the tutor appears to contradict itself.

A numbered reference is the opposite problem. "chp 4 ex 4.5 q 3" (prd.md FR-1's own
example) is a lookup, not a similarity question, and MaxSim over a 150 DPI page scan is
particularly bad at it: "7.3" is a handful of dark pixels on a page full of them.

No database, no model, no settings - the same discipline as `gate.py` and `onboarding.py`,
so every rule here is testable without a connection string.

⚠️ THE BIAS IS DELIBERATELY ASYMMETRIC. A missed follow-up costs a few seconds of
retrieval nobody needed. A FALSE follow-up answers a new question with the previous
question's pages, which is a confidently wrong answer. So every rule below is written to
fall back to `retrieve` when unsure, and the tests assert that direction specifically.
"""

from __future__ import annotations

import re
from typing import Literal

from app.retrieval.physics9.heuristic import TOPIC_TERMS

Intent = Literal["followup", "reference", "retrieve"]

# A numbered reference: a kind word followed by a number. The kind word is REQUIRED,
# which is what keeps "convert 30 degrees celsius to fahrenheit" out - a bare number is
# not a reference, and most numbers a student types are physics, not citations.
#
# Covers prd.md FR-1's canonical shape ("chp 4 ex 4.5 q 3") and the forms the Physics
# book actually prints ("Example 7.1", "numerical 7.3").
_REFERENCE = re.compile(
    r"\b(example|ex|exercise|exer|numerical|numericals|problem|problems|question|questions|q|mcq|mcqs|activity|figure|fig|table)\b"
    r"\.?\s*(no\.?\s*)?\d+",
    re.IGNORECASE,
)

# A reference to a whole chapter's exercises, with no item number: "mcqs of chapter 7",
# "chapter 7 ke numericals". Still a lookup rather than a similarity question.
_CHAPTER_EXERCISES = re.compile(r"\b(ch|chp|chap|chapter|bab)\b\.?\s*\d+", re.IGNORECASE)
_EXERCISE_WORDS = frozenset(
    {
        "exercise",
        "exercises",
        "mcq",
        "mcqs",
        "numerical",
        "numericals",
        "problem",
        "problems",
        "question",
        "questions",
        "review",
        "sawalat",
    }
)

# Follow-up markers, in the three languages the product serves. High precision on
# purpose: each of these is a phrase that only appears when a student is reacting to an
# answer they have already been given.
#
# ⚠️ Roman Urdu is NOT a transliteration of the English list. "phir se", "samajh nahi
# aya", "aur batao" are what a Pakistani student actually types; translating the English
# markers word for word would produce phrases nobody uses.
_FOLLOWUP_MARKERS = (
    # English
    "again",
    "repeat",
    "rephrase",
    "simpler",
    "simply",
    "elaborate",
    "more detail",
    "in detail",
    "go on",
    "continue",
    "what do you mean",
    "explain that",
    "explain it",
    "didn't understand",
    "did not understand",
    "don't understand",
    "do not understand",
    "not clear",
    "confusing",
    "how so",
    "why is that",
    "another example",
    "one more",
    # Roman Urdu
    "phir se",
    "phirse",
    "dobara",
    "dubara",
    "dobhara",
    "samajh nahi",
    "samajh nhi",
    "samjha nahi",
    "samjhao",
    "samjha do",
    "aur batao",
    "aur bata",
    "thora asan",
    "thoda asan",
    "asan karke",
    "aasan karke",
    "matlab kya",
    "kya matlab",
    "aik aur",
    "ek aur",
    # Urdu script
    "دوبارہ",  # dobara
    "سمجھ نہیں",  # samajh nahin
    "مزید",  # mazeed (more)
    "مطلب",  # matlab
    "آسان",  # asan (easy)
)

# Bare interrogatives, which are follow-ups ONLY when the question is almost nothing
# else. "Why?" is the commonest follow-up a student types; "why is the sky blue" is a
# new question that starts the same way. The length gate below is what separates them,
# and it is why these are kept apart from the phrase markers above.
_BARE_INTERROGATIVES = frozenset(
    {
        "why",
        "how",
        "when",
        "where",
        "which",
        "really",
        "huh",
        "kyun",
        "kyu",
        "kaise",
        "kahan",
        "kab",
        "acha",
        "achha",
        "کیوں",  # kyun
        "کیسے",  # kaise
    }
)
_MAX_BARE_WORDS = 3

# Above this, a question is carrying enough of its own content to be worth retrieving
# for, whatever markers it contains. "Explain again why a thermocouple needs two
# junctions of dissimilar metals" is a new question that happens to say "again".
_MAX_FOLLOWUP_WORDS = 8


# Words that carry no topic, for books WITHOUT a syllabus vocabulary (every book except
# Physics 9). There, the guard inverts: a turn is a follow-up only if NOTHING remains
# after removing these, the follow-up markers and the bare interrogatives. Any other
# word may name a new topic, and the turn retrieves - the same bias as for Physics,
# kept by a different test (tdd.md §3.2a, turn routing). Missing a filler here costs a
# retrieval; never a wrong answer.
_FILLERS = frozenset(
    {
        # English
        "a",
        "an",
        "the",
        "that",
        "this",
        "it",
        "its",
        "is",
        "are",
        "was",
        "were",
        "be",
        "to",
        "of",
        "in",
        "on",
        "for",
        "and",
        "or",
        "but",
        "so",
        "about",
        "me",
        "my",
        "i",
        "you",
        "your",
        "can",
        "could",
        "would",
        "will",
        "do",
        "does",
        "did",
        "please",
        "plz",
        "pls",
        "more",
        "once",
        "one",
        "same",
        "thing",
        "part",
        "step",
        "steps",
        "point",
        "last",
        "previous",
        "above",
        "answer",
        "explain",
        "explanation",
        "tell",
        "say",
        "said",
        "mean",
        "means",
        "meaning",
        "example",
        "examples",
        "detail",
        "details",
        "understand",
        "understood",
        "not",
        "dont",
        "didnt",
        "no",
        "yes",
        "ok",
        "okay",
        "thanks",
        "thank",
        "sir",
        "miss",
        "madam",
        "bit",
        "little",
        "simple",
        "easier",
        "easy",
        "short",
        "shorter",
        "again",
        "still",
        "get",
        "got",
        "how",
        "give",
        "another",
        "different",
        "what",
        "why",
        "which",
        "with",
        "words",
        "word",
        "now",
        "just",
        "really",
        "very",
        # Roman Urdu
        "ye",
        "yeh",
        "wo",
        "woh",
        "us",
        "ko",
        "ka",
        "ki",
        "ke",
        "se",
        "mein",
        "main",
        "mujhe",
        "muje",
        "hai",
        "hain",
        "tha",
        "thi",
        "nahi",
        "nai",
        "nahin",
        "samajh",
        "samjh",
        "samjhao",
        "samjhaen",
        "samjhayen",
        "samjha",
        "aya",
        "ayi",
        "dobara",
        "phir",
        "aur",
        "batao",
        "bataen",
        "bataiye",
        "zara",
        "thora",
        "thoda",
        "asaan",
        "asan",
        "kya",
        "kyun",
        "kyon",
        "kaise",
        "kaisay",
        "matlab",
        "yani",
        "acha",
        "achha",
        "ji",
        "jee",
        "na",
        "bhi",
        "tum",
        "ap",
        "aap",
        # Urdu script
        "یہ",
        "وہ",
        "اس",
        "کو",
        "کا",
        "کی",
        "کے",
        "سے",
        "میں",
        "مجھے",
        "ہے",
        "ہیں",
        "نہیں",
        "سمجھ",
        "سمجھائیں",
        "دوبارہ",
        "پھر",
        "اور",
        "بتائیں",
        "کیا",
        "کیوں",
        "کیسے",
        "مطلب",
        "آپ",
    }
)


def _words(question: str) -> list[str]:
    return re.sub(r"[^\w\s]", " ", question.lower()).split()


def looks_like_reference(question: str) -> bool:
    """A numbered item or a chapter's exercise set."""
    if _REFERENCE.search(question):
        return True
    if _CHAPTER_EXERCISES.search(question):
        return bool(_EXERCISE_WORDS & set(_words(question)))
    return False


def has_content_words(question: str) -> bool:
    """Does anything remain once fillers, follow-up markers and bare interrogatives are
    removed? For books without a syllabus vocabulary, any remaining word might name a
    new topic, so the turn must be retrieved for."""
    marker_words = {w for marker in _FOLLOWUP_MARKERS for w in _words(marker)}
    ignorable = _FILLERS | marker_words | _BARE_INTERROGATIVES
    return any(word not in ignorable for word in _words(question))


def mentions_a_topic(question: str, topic_terms: frozenset[str] = TOPIC_TERMS) -> bool:
    """Does the question name something the syllabus index recognises?

    This is the guard that keeps a follow-up reading honest. "Explain that again" names
    nothing; "explain thermocouples again" names a topic and must be retrieved for, even
    though it ends in a follow-up marker.

    ⚠️ Plurals are matched in both directions, and that is not cosmetic. The index holds
    "thermocouple" and a student types "thermocouples"; an exact set intersection missed
    it, and the failure direction was the dangerous one - a new question answered from
    the previous question's pages. Caught by smoke-testing the classifier before writing
    its tests.

    Deliberately NOT a general prefix match: "heat" is a topic term and would then be
    found inside "heather", "heating", "heathen". A trailing 's' is the one inflection
    worth handling, because it is the one the index's own singular/plural choices create.
    """
    words = set(_words(question))
    if topic_terms & words:
        return True
    return any(word.rstrip("s") in topic_terms or f"{word}s" in topic_terms for word in words)


def classify(
    question: str,
    *,
    has_prior_turn: bool,
    topic_terms: frozenset[str] | None = TOPIC_TERMS,
) -> Intent:
    """`reference`, `followup` or `retrieve`.

    Order matters. A reference wins over a follow-up marker, because "ex 4.5 again" is
    still a request for a specific exercise - the marker only says the student has seen
    it before.

    `topic_terms` is the book's syllabus vocabulary - Physics 9's by default. `None`
    means the book has none, and then any word that is not a filler, a marker or a bare
    interrogative counts as a possible new topic (`has_content_words`).
    """
    if looks_like_reference(question):
        return "reference"

    if not has_prior_turn:
        # Nothing to follow up ON. The first turn of a session is always a retrieval,
        # even if it opens with "explain again" - which a student rejoining a topic
        # genuinely does type.
        return "retrieve"

    words = _words(question)
    if len(words) > _MAX_FOLLOWUP_WORDS:
        return "retrieve"
    if topic_terms is None:
        if has_content_words(question):
            return "retrieve"
    elif mentions_a_topic(question, topic_terms):
        return "retrieve"

    lowered = question.lower()
    if any(marker in lowered for marker in _FOLLOWUP_MARKERS):
        return "followup"

    # A bare interrogative, and almost nothing else. "Why?" / "kyun?" / "kaise?"
    if len(words) <= _MAX_BARE_WORDS and (_BARE_INTERROGATIVES & set(words)):
        return "followup"

    # Short, topicless, and no recognised marker. Could be a follow-up in words we do
    # not know, or could be a new question in three words. Retrieval is the safe
    # reading: it costs latency, not correctness.
    return "retrieve"

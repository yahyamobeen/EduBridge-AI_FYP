"""Turn classification: follow-up, reference, or retrieve (tdd.md §3.2a, §4.1).

⚠️ The asymmetry is the point of most of these. A missed follow-up costs a few seconds
of retrieval nobody needed. A FALSE follow-up answers a new question with the previous
question's pages - a confidently wrong answer. So the tests that matter most are the
ones asserting the classifier falls back to `retrieve` when unsure.
"""

from __future__ import annotations

import pytest

from app.tutor.turns import classify, looks_like_reference, mentions_a_topic


@pytest.mark.parametrize(
    "question",
    [
        "math 9 chp 4 ex 4.5 q 3",  # prd.md FR-1's own example
        "example 7.1",
        "Example 7.1",
        "numerical 7.3",
        "exercise 7.5",
        "problem 4",
        "question no. 3",
        "q 3",
        "mcq 5",
        "activity 7.1",
        "figure 7.8",
        "mcqs of chapter 7",
        "chapter 7 ke numericals",
        "ch 3 exercises",
    ],
)
def test_references_are_routed_to_the_index(question):
    """MaxSim over a 150 DPI scan is bad at '7.3' - it is a few dark pixels on a page
    full of them. The syllabus index maps the reference directly."""
    assert looks_like_reference(question)
    assert classify(question, has_prior_turn=False) == "reference"


@pytest.mark.parametrize(
    "question",
    [
        "convert 30 degrees celsius to fahrenheit",  # a number, not a reference
        "what is absolute zero",
        "how does a thermocouple thermometer work",
        "define heat as energy in transit",
        "what happens at 100 degrees",
        "explain the 3 states of matter",
    ],
)
def test_numbers_in_physics_are_not_references(question):
    """A bare number is not a citation. Most numbers a student types are physics.

    This is why the pattern REQUIRES a kind word before the digit - without it,
    'convert 30 degrees celsius' routes to an index lookup and returns nothing useful.
    """
    assert not looks_like_reference(question)
    assert classify(question, has_prior_turn=False) == "retrieve"
    # And still not a reference mid-conversation, where a follow-up reading is available.
    assert classify(question, has_prior_turn=True) != "reference"


@pytest.mark.parametrize(
    "question",
    [
        # English
        "explain that again",
        "repeat that",
        "can you rephrase",
        "simpler please",
        "i didn't understand",
        "that's confusing",
        "go on",
        "one more",
        # Roman Urdu - what a student actually types, not a translation of the above
        "phir se samjhao",
        "dobara batao",
        "samajh nahi aya",
        "aur batao",
        "thora asan karke",
        "matlab kya hai",
        "aik aur",
        # bare interrogatives
        "why?",
        "why",
        "kyun",
        "kaise",
        "how so",
    ],
)
def test_follow_ups_reuse_the_previous_pages(question):
    assert classify(question, has_prior_turn=True) == "followup"


def test_the_first_turn_is_never_a_follow_up():
    """A student rejoining a topic genuinely opens with 'explain again' - and there is
    nothing to follow up on, so it must retrieve."""
    assert classify("explain that again", has_prior_turn=False) == "retrieve"
    assert classify("why?", has_prior_turn=False) == "retrieve"


@pytest.mark.parametrize(
    "question",
    [
        "explain thermocouples again",  # plural; the index holds the singular
        "explain thermocouple again",
        "what is plasma again",
        "tell me about momentum again",
        "phir se thermocouple samjhao",
        "repeat the kinetic molecular theory",
    ],
)
def test_naming_a_topic_defeats_a_follow_up_marker(question):
    """⚠️ THE DANGEROUS DIRECTION.

    These all end in a follow-up marker but name a topic, so they are new questions.
    Reading them as follow-ups would answer them from whatever pages happened to be on
    screen. The plural case here is a real bug this caught: the index holds
    'thermocouple' and an exact word-set intersection missed 'thermocouples'.
    """
    assert mentions_a_topic(question)
    assert classify(question, has_prior_turn=True) == "retrieve"


def test_a_long_question_is_never_a_follow_up():
    """Enough of its own content to be worth retrieving for, whatever it says."""
    question = "explain again why a thermocouple needs two junctions of dissimilar metals"
    assert classify(question, has_prior_turn=True) == "retrieve"


def test_a_bare_interrogative_only_counts_when_the_question_is_little_else():
    """'Why?' is the commonest follow-up there is. 'Why is the sky blue' is not."""
    assert classify("why", has_prior_turn=True) == "followup"
    assert classify("but why", has_prior_turn=True) == "followup"
    assert classify("why is the sky blue", has_prior_turn=True) == "retrieve"
    assert classify("how do magnets attract iron filings", has_prior_turn=True) == "retrieve"


def test_a_reference_beats_a_follow_up_marker():
    """'ex 4.5 again' is still a request for that exercise; the marker only says the
    student has seen it before."""
    assert classify("ex 4.5 again", has_prior_turn=True) == "reference"
    assert classify("numerical 7.3 phir se", has_prior_turn=True) == "reference"


def test_unknown_short_phrases_fall_back_to_retrieval():
    """Short, topicless, no recognised marker. Could be a follow-up in words we do not
    know, or a new question in three words. Retrieval costs latency, not correctness."""
    assert classify("hmm ok sure", has_prior_turn=True) == "retrieve"
    assert classify("the blue one", has_prior_turn=True) == "retrieve"


def test_topic_terms_are_built_from_the_index_itself():
    """Not a hand-written stopword list, which would drift from the retriever's own
    vocabulary - and the drift would show up as follow-ups being misread."""
    from app.retrieval.physics9.heuristic import TOPIC_TERMS

    assert "thermocouple" in TOPIC_TERMS
    assert "plasma" in TOPIC_TERMS
    assert "momentum" in TOPIC_TERMS
    # Function words are excluded, or a single "of" would veto every follow-up.
    assert "of" not in TOPIC_TERMS
    assert "the" not in TOPIC_TERMS
    assert "is" not in TOPIC_TERMS

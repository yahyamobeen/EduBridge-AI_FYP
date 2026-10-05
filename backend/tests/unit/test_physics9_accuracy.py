"""Unit tests for Class 9 Physics Retrieval Engine Accuracy.

Tests that queries across all 9 chapters of the Punjab Textbook Board (PCTB)
textbook accurately retrieve the exact ground-truth pages.
"""

from __future__ import annotations

import pytest
from app.retrieval.physics9.retriever import PhysicsRetriever


@pytest.fixture
def retriever() -> PhysicsRetriever:
    return PhysicsRetriever()


@pytest.mark.parametrize(
    ("query", "expected_pages", "desc"),
    [
        (
            "Define inertia and Newton's first law",
            [58, 59, 60],
            "Newton 1st law and inertia",
        ),
        (
            "Newton ka pehla qanoon aur inertia kya hai",
            [58, 59, 60],
            "Newton 1st law in Roman Urdu",
        ),
        (
            "State Newton's second law of motion with formula f=ma",
            [60, 61, 62],
            "Newton 2nd law F=ma",
        ),
        (
            "What is the difference between mass and weight?",
            [62, 63],
            "Mass vs Weight",
        ),
        (
            "Newton's third law of motion and action reaction",
            [63, 64, 65],
            "Newton 3rd law",
        ),
        (
            "Law of conservation of momentum with example",
            [73, 71, 72, 74],
            "Conservation of momentum",
        ),
        (
            "What is kinetic energy? State its formula.",
            [108, 109, 110],
            "Kinetic energy formula",
        ),
        (
            "What is potential energy and gravitational potential energy?",
            [110, 111, 112],
            "Potential energy",
        ),
        (
            "What is the unit of power watt?",
            [120],
            "Unit of power watt",
        ),
        (
            "What is Hooke's law and elastic limit?",
            [127, 128, 129, 130],
            "Hooke's law and elasticity",
        ),
        (
            "Applications of Hooke's law",
            [130],
            "Hooke's law applications",
        ),
        (
            "Archimedes principle and upthrust of liquid",
            [142, 143, 144, 145],
            "Archimedes principle",
        ),
        (
            "Pascal's law and hydraulic press",
            [138, 139, 140, 141, 142],
            "Pascal's law and hydraulic press",
        ),
        (
            "How does a thermocouple thermometer work?",
            [154, 155],
            "Thermocouple thermometer",
        ),
        (
            "Convert celsius to fahrenheit formula",
            [154],
            "Celsius to Fahrenheit conversion",
        ),
        (
            "What is absolute zero?",
            [154],
            "Absolute zero",
        ),
        (
            "Kinetic molecular theory of matter",
            [149],
            "Kinetic molecular theory",
        ),
        (
            "What is plasma the fourth state of matter?",
            [150],
            "Plasma 4th state of matter",
        ),
        (
            "Labelled parts of vernier callipers",
            [12, 13],
            "Vernier callipers",
        ),
        (
            "What is pitch and least count of screw gauge?",
            [16, 17, 18, 19],
            "Screw gauge",
        ),
        (
            "Gradient or slope of speed time graph",
            [41, 43],
            "Speed-time graph slope",
        ),
        (
            "Uniform and non uniform acceleration",
            [36, 37],
            "Acceleration definitions",
        ),
        (
            "Three equations of motion derivation",
            [44, 45, 46, 47, 48],
            "Equations of motion",
        ),
        (
            "What is moment of force or torque?",
            [82, 83, 84],
            "Torque / Moment of force",
        ),
        (
            "Uses of electromagnets in telephone and cranes",
            [171],
            "Electromagnets applications",
        ),
    ],
)
def test_retriever_accuracy(
    retriever: PhysicsRetriever,
    query: str,
    expected_pages: list[int],
    desc: str,
) -> None:
    hits, _, _ = retriever.search(query, top_k=3)
    retrieved_page_numbers = [h["page"] for h in hits]
    # Check that at least one of the expected ground truth pages is in the top-3 hits
    matched = any(p in retrieved_page_numbers for p in expected_pages)
    assert matched, (
        f"Failed for '{desc}' (Query: '{query}'). "
        f"Expected one of {expected_pages}, got {retrieved_page_numbers}"
    )

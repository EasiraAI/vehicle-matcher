"""Per-input validation matrix: a semantic expectation for every line of
inputs.txt. Where the challenge pins an exact answer we assert the ID; where
the input is genuinely ambiguous we assert the properties any correct answer
must have (right model family, right fuel, bounded confidence) rather than
overfitting to one row. The byte-exact regression net is the snapshot test.
"""

from pathlib import Path

import pytest

from vehicle_matcher.config import get_settings
from vehicle_matcher.matcher import Matcher

pytestmark = pytest.mark.integration

INPUTS = Path(__file__).parents[2] / "data" / "inputs.txt"

CASES = [
    # (description, expectation dict)
    (
        "Volkswagen Golf 110TSI Comfortline Petrol Automatic Front Wheel Drive",
        {"id": "4749339721203712", "confidence": 9},
    ),
    (
        "Volkswagen Golf 132TSI Automatic",
        # Alltrack rows are the only 132TSI Golfs; variant is ambiguous.
        {"model": "Golf", "badge_contains": "132TSI", "max_confidence": 7},
    ),
    (
        "Volkswagen Golf Alltrack 132TSI",
        {"model": "Golf", "badge_contains": "Alltrack 132TSI"},
    ),
    (
        "VW Golf R with engine swap from Toyota 86 GT",
        {"id": "5824662093168640", "confidence": 6},
    ),
    ("Golf GTI", {"model": "Golf", "badge": "GTI"}),
    ("Golf cart", {"null": True, "confidence": 10}),
    (
        "VW tiguan 162tsi allspace",
        {"model": "Tiguan", "badge": "162TSI Highline Allspace"},
    ),
    ("R-Line Tiguan", {"model": "Tiguan", "badge": "132TSI R-Line Edition"}),
    (
        "Selling my tiguan r-line in exchange for a toyota camry hybrid",
        # must resolve to the Tiguan being sold, never the Camry wanted
        {"model": "Tiguan", "badge": "132TSI R-Line Edition"},
    ),
    ("VW Amarok Ultimate", {"id": "4951649860714496", "confidence": 7}),
    (
        "Amrok h/line 4x4",
        {
            "model": "Amarok",
            "badge_contains": "Highline",
            "drive": "Four Wheel Drive",
            "max_confidence": 6,
        },
    ),
    ("RAV4 GX 4x4", {"id": "4637157457133568"}),
    (
        "Toyota Camry Hybrid",
        # three hybrid Camrys tie on evidence; any is defensible, hybrid is not
        {"model": "Camry", "fuel": "Hybrid-Petrol", "max_confidence": 7},
    ),
    (
        "Toyota Kluger Sports Hybrid (It's actually a Toyota 86 GT"
        " but the website didn't let me select that, sorry)",
        # the correction governs; reinterpretation caps certainty
        {"model": "86", "badge": "GT", "max_confidence": 6},
    ),
    ("Toyota 86 GT Manual Petrol RWD", {"id": "5027098813005824", "min_confidence": 7}),
    ("Toyota 86 GTS Apollo Manual", {"id": "4655849154805760"}),
    ("Toyota 86 GTS Auto", {"id": "5871523743137792"}),
    ("Toyota Corolla Ascent Sport Auto", {"null": True, "min_confidence": 8}),
    ("Toyota Ascent Sports Hybrid", {"id": "5118775628136448"}),
    ("Toyota Kluger Black E/d 4WD", {"id": "5387024387276800"}),
]


@pytest.fixture(scope="module")
def matcher(db_conn):
    return Matcher(db_conn, settings=get_settings())


@pytest.mark.parametrize(("description", "expected"), CASES, ids=[c[0][:40] for c in CASES])
def test_expected_result(matcher, description, expected):
    result = matcher.match(description)

    if expected.get("null"):
        assert result.vehicle_id is None
    else:
        assert result.vehicle_id is not None
        top = result.debug.scored[0].candidate
        if "id" in expected:
            assert result.vehicle_id == expected["id"]
        if "model" in expected:
            assert top.model == expected["model"]
        if "badge" in expected:
            assert top.badge == expected["badge"]
        if "badge_contains" in expected:
            assert expected["badge_contains"] in top.badge
        if "fuel" in expected:
            assert top.fuel_type == expected["fuel"]
        if "drive" in expected:
            assert top.drive_type == expected["drive"]

    if "confidence" in expected:
        assert result.confidence == expected["confidence"]
    if "min_confidence" in expected:
        assert result.confidence >= expected["min_confidence"]
    if "max_confidence" in expected:
        assert result.confidence <= expected["max_confidence"]


def test_matrix_covers_every_input_line():
    lines = [ln.strip() for ln in INPUTS.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert [c[0] for c in CASES] == lines


def test_distractor_costs_confidence(matcher):
    plain = matcher.match("R-Line Tiguan")
    distracted = matcher.match("Selling my tiguan r-line in exchange for a toyota camry hybrid")
    assert distracted.vehicle_id == plain.vehicle_id
    assert distracted.confidence < plain.confidence

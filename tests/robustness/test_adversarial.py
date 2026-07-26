"""Hostile and degenerate input through the full pipeline. The contract under
fire: never raise, always return a confidence in [0, 10], never mutate the
database, and stay deterministic under cosmetic variation."""

import pytest

from vehicle_matcher.config import get_settings
from vehicle_matcher.matcher import Matcher

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def matcher(db_conn):
    return Matcher(db_conn, settings=get_settings())


DEGENERATE = [
    "",
    "   \t  ",
    "!!!???...",
    "0000000000",
    "a",
    "🚗🔥💯 quick sale 🔥",
    "ГОЛЬФ ГТИ",  # cyrillic
    "ゴルフ GTI",  # mixed scripts
    "Toyota " * 500,  # pathological repetition, ~3.5k chars
    "x" * 10_000,  # single enormous token
    "SELECT * FROM vehicle; -- Golf GTI",
    "null",
    "None",
    "Vehicle ID: 4749339721203712",  # output format echoed back as input
]


@pytest.mark.parametrize("text", DEGENERATE, ids=[repr(t[:24]) for t in DEGENERATE])
def test_never_raises_and_stays_in_range(matcher, text):
    result = matcher.match(text)
    assert 0 <= result.confidence <= 10
    assert result.vehicle_id is None or result.vehicle_id.isdigit()


def test_token_order_does_not_change_the_match(matcher):
    a = matcher.match("Toyota 86 GT Manual Petrol RWD")
    b = matcher.match("Manual Petrol RWD 86 GT Toyota")
    assert a.vehicle_id == b.vehicle_id
    assert a.confidence == b.confidence


def test_case_and_whitespace_insensitive(matcher):
    a = matcher.match("VW Amarok Ultimate")
    b = matcher.match("  vw   AMAROK    ultimate ")
    assert (a.vehicle_id, a.confidence) == (b.vehicle_id, b.confidence)


def test_repeated_calls_are_deterministic(matcher):
    results = {
        (r.vehicle_id, r.confidence)
        for r in (matcher.match("VW tiguan 162tsi allspace") for _ in range(5))
    }
    assert len(results) == 1


def test_two_vehicles_in_one_line_resolves_to_first_subject(matcher):
    # No distractor marker, so the first-mentioned vehicle governs (first-wins
    # extraction). The important property is a deterministic, sane answer.
    result = matcher.match("Toyota Camry Hybrid and VW Golf GTI")
    assert result.vehicle_id is not None
    assert result.debug.scored[0].candidate.model == "Camry"


def test_agreeing_detail_never_lowers_confidence_end_to_end(matcher):
    ladder = [
        "Golf GTI",
        "VW Golf GTI",
        "VW Golf GTI Petrol",
        "VW Golf GTI Petrol Automatic",
    ]
    confidences = [matcher.match(text).confidence for text in ladder]
    assert confidences == sorted(confidences)


def test_conflicting_detail_never_raises_confidence(matcher):
    clean = matcher.match("Toyota 86 GTS Auto")
    conflicted = matcher.match("Toyota 86 GTS Auto Diesel Front Wheel Drive")
    assert conflicted.confidence <= clean.confidence


def test_database_unchanged_after_hostile_batch(matcher, db_conn):
    for text in DEGENERATE:
        matcher.match(text)
    assert db_conn.execute("SELECT count(*) FROM vehicle").fetchone()[0] == 59
    assert db_conn.execute("SELECT count(*) FROM listing").fetchone()[0] == 1000

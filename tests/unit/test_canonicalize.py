"""Canonicalization of externally produced extractions. Every case here is a
real behaviour observed from the live LLM during the first shadow-audit run —
each one caused a spurious conflict and a false null before the fix."""

from vehicle_matcher.extractor import canonicalize
from vehicle_matcher.models import ExtractedVehicle


def test_unexpanded_make_abbreviation(vocab):
    # observed: {"make": "VW", "model": "Tiguan", ...} -> every candidate
    # conflicted on make and the match came back null@10
    ev = ExtractedVehicle(make="VW", model="Tiguan", badge_tokens=["162tsi", "allspace"])
    out = canonicalize(ev, vocab)
    assert out.make == "Volkswagen"
    assert out.model == "Tiguan"


def test_badge_word_promoted_to_model_is_demoted(vocab):
    # observed: {"model": "Ascent", "badge_tokens": ["sports", "hybrid"]}
    ev = ExtractedVehicle(make="Toyota", model="Ascent", badge_tokens=["sports"])
    out = canonicalize(ev, vocab)
    assert out.model is None
    assert out.badge_tokens == ["ascent", "sport"]  # alias applied too


def test_attribute_word_filed_under_badge_moves_home(vocab):
    ev = ExtractedVehicle(make="Toyota", badge_tokens=["hybrid", "gx", "4x4"])
    out = canonicalize(ev, vocab)
    assert out.badge_tokens == ["gx"]
    assert out.fuel == "Hybrid-Petrol"
    assert out.drive == "Four Wheel Drive"


def test_unknown_values_pass_through_for_absence_detection(vocab):
    # "Ford Ranger" must stay intact or null-confidence collapses
    ev = ExtractedVehicle(make="Ford", model="Ranger", badge_tokens=["xlt"])
    out = canonicalize(ev, vocab)
    assert out.make == "Ford"
    assert out.model == "Ranger"
    assert out.badge_tokens == ["xlt"]


def test_already_canonical_extraction_is_unchanged(vocab):
    ev = ExtractedVehicle(
        make="Volkswagen",
        model="Golf",
        badge_tokens=["110tsi", "comfortline"],
        transmission="Automatic",
        fuel="Petrol",
        drive="Front Wheel Drive",
    )
    assert canonicalize(ev, vocab) == ev


def test_original_extraction_is_not_mutated(vocab):
    ev = ExtractedVehicle(make="VW", badge_tokens=["sports"])
    canonicalize(ev, vocab)
    assert ev.make == "VW"
    assert ev.badge_tokens == ["sports"]

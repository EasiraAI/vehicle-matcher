import pytest

from vehicle_matcher.extractor import extract


def test_full_spec_description(vocab):
    ev = extract("Volkswagen Golf 110TSI Comfortline Petrol Automatic Front Wheel Drive", vocab)
    assert ev.make == "Volkswagen"
    assert ev.model == "Golf"
    assert ev.badge_tokens == ["110tsi", "comfortline"]
    assert ev.fuel == "Petrol"
    assert ev.transmission == "Automatic"
    assert ev.drive == "Front Wheel Drive"
    assert ev.weak_fuel is None  # the explicit "Petrol" supersedes the TSI hint


def test_engine_code_gives_badge_and_weak_fuel(vocab):
    ev = extract("Golf 132TSI", vocab)
    assert "132tsi" in ev.badge_tokens
    assert ev.fuel is None
    assert ev.weak_fuel == "Petrol"


def test_make_alias(vocab):
    assert extract("VW Amarok Ultimate", vocab).make == "Volkswagen"


def test_abbreviated_badge_and_drive(vocab):
    ev = extract("Amrok h/line 4x4", vocab)
    assert ev.make is None
    assert ev.model is None  # misspelling: resolved later by fuzzy retrieval/scoring
    assert ev.badge_tokens == ["highline"]
    assert ev.drive == "Four Wheel Drive"
    assert "amrok" in ev.unknown_tokens


def test_multiword_drive_alias(vocab):
    ev = extract("Toyota 86 GT Manual Petrol Rear Wheel Drive", vocab)
    assert ev.drive == "Rear Wheel Drive"
    assert ev.transmission == "Manual"


def test_correction_replaces_original_mention(vocab):
    ev = extract(
        "Toyota Kluger Sports Hybrid (It's actually a Toyota 86 GT"
        " but the website didn't let me select that, sorry)",
        vocab,
    )
    assert ev.flags.correction_applied
    assert ev.make == "Toyota"
    assert ev.model == "86"
    assert "gt" in ev.badge_tokens
    assert ev.fuel is None  # "Hybrid" belonged to the retracted mention


def test_distractor_keeps_only_the_vehicle_for_sale(vocab):
    ev = extract("Selling my tiguan r-line in exchange for a toyota camry hybrid", vocab)
    assert ev.flags.distractor_stripped
    assert ev.model == "Tiguan"
    assert ev.badge_tokens == ["r-line"]
    assert ev.make is None
    assert ev.fuel is None  # the Camry Hybrid is not the subject


def test_engine_swap_marks_modified_and_drops_donor(vocab):
    ev = extract("VW Golf R with engine swap from Toyota 86 GT", vocab)
    assert ev.flags.modified_vehicle
    assert ev.make == "Volkswagen"
    assert ev.model == "Golf"
    assert ev.badge_tokens == ["r"]


def test_non_vehicle_short_circuits(vocab):
    ev = extract("Golf cart", vocab)
    assert ev.flags.non_vehicle
    assert ev.model is None


def test_external_make_and_model_still_extracted(vocab):
    # "Ford Ranger" is a real vehicle that is not in the catalogue; extraction
    # must still recognise it so the null branch can be confident.
    ev = extract("Ford Ranger XLT Dual Cab", vocab)
    assert ev.make == "Ford"
    assert ev.model == "Ranger"


def test_sports_alias_normalises_to_sport(vocab):
    ev = extract("Toyota Ascent Sports Hybrid", vocab)
    assert ev.badge_tokens == ["ascent", "sport"]
    assert ev.fuel == "Hybrid-Petrol"
    assert ev.model is None


def test_gibberish_yields_empty_extraction(vocab):
    ev = extract("qwerty asdfgh 12345", vocab)
    assert ev.make is None and ev.model is None
    assert ev.badge_tokens == []


@pytest.mark.parametrize("text", ["", "   ", "!!!", "'; DROP TABLE vehicle; --", "🚗🚗🚗"])
def test_never_raises_on_degenerate_input(vocab, text):
    ev = extract(text, vocab)
    assert ev is not None

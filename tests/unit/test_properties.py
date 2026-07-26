"""Property-based invariants: laws that must hold for arbitrary input, not
just the examples we thought of."""

from hypothesis import given
from hypothesis import strategies as st

from vehicle_matcher.calibrator import match_confidence, null_confidence
from vehicle_matcher.extractor import extract
from vehicle_matcher.models import Candidate, ExtractedVehicle, Flags, ScoredCandidate
from vehicle_matcher.normalizer import normalize
from vehicle_matcher.scorer import score_candidate


@given(st.text(max_size=500))
def test_normalize_never_raises_and_yields_clean_tokens(text):
    tokens = normalize(text)
    assert all(tok == tok.lower() and " " not in tok for tok in tokens)


@given(st.text(max_size=500))
def test_extract_never_raises_on_arbitrary_text(vocab, text):
    ev = extract(text, vocab)
    assert isinstance(ev, ExtractedVehicle)


@given(st.text(max_size=200))
def test_extraction_is_deterministic(vocab, text):
    assert extract(text, vocab) == extract(text, vocab)


_scored = st.builds(
    ScoredCandidate,
    candidate=st.builds(
        Candidate,
        id=st.text(min_size=1, max_size=4),
        make=st.sampled_from(["Toyota", "Volkswagen"]),
        model=st.sampled_from(["Golf", "Camry"]),
        badge=st.sampled_from(["GTI", "Ascent Sport"]),
        transmission_type=st.sampled_from(["Automatic", "Manual"]),
        fuel_type=st.just("Petrol"),
        drive_type=st.just("Front Wheel Drive"),
        trgm_score=st.floats(0, 1),
        listing_count=st.integers(0, 500),
    ),
    score=st.floats(-20, 20),
    conflicts=st.integers(0, 5),
)
_extracted = st.builds(
    ExtractedVehicle,
    make=st.none() | st.sampled_from(["Toyota", "Volkswagen", "Ford"]),
    model=st.none() | st.sampled_from(["Golf", "Camry", "Ranger"]),
    badge_tokens=st.lists(st.sampled_from(["gti", "ascent", "sport"]), max_size=3),
    flags=st.builds(
        Flags,
        correction_applied=st.booleans(),
        distractor_stripped=st.booleans(),
        modified_vehicle=st.booleans(),
        non_vehicle=st.booleans(),
    ),
)


@given(_extracted, _scored, st.none() | _scored)
def test_match_confidence_always_zero_to_ten(extracted, top, runner_up):
    assert 0 <= match_confidence(extracted, top, runner_up) <= 10


@given(_extracted)
def test_null_confidence_always_zero_to_ten(extracted):
    makes = frozenset({"Toyota", "Volkswagen"})
    models = frozenset({"Golf", "Camry"})
    assert 0 <= null_confidence(extracted, makes, models) <= 10


@given(_extracted, _scored)
def test_scoring_is_deterministic(extracted, scored):
    a = score_candidate(extracted, scored.candidate)
    b = score_candidate(extracted, scored.candidate)
    assert a.score == b.score and a.conflicts == b.conflicts

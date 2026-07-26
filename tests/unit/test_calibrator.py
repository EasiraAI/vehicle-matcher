from vehicle_matcher.calibrator import match_confidence, null_confidence
from vehicle_matcher.models import Candidate, ExtractedVehicle, Flags, ScoredCandidate

MAKES = frozenset({"Toyota", "Volkswagen"})
MODELS = frozenset({"86", "Camry", "Kluger", "RAV4", "Amarok", "Golf", "Tiguan"})


def scored(score: float, conflicts: int = 0) -> ScoredCandidate:
    return ScoredCandidate(
        candidate=Candidate(
            id="x",
            make="Volkswagen",
            model="Golf",
            badge="GTI",
            transmission_type="Automatic",
            fuel_type="Petrol",
            drive_type="Front Wheel Drive",
            trgm_score=0.9,
            listing_count=10,
        ),
        score=score,
        conflicts=conflicts,
    )


FULL_SPEC = ExtractedVehicle(
    make="Volkswagen",
    model="Golf",
    badge_tokens=["110tsi", "comfortline"],
    transmission="Automatic",
    fuel="Petrol",
    drive="Front Wheel Drive",
)
SPARSE = ExtractedVehicle(make="Volkswagen", model="Amarok", badge_tokens=["ultimate"])


def test_full_spec_clear_winner_is_nine():
    assert match_confidence(FULL_SPEC, scored(13.0), scored(9.5)) == 9


def test_sparse_description_caps_lower():
    # make+model+badge only, clear margin: solid but not near-certain (anchor 2)
    assert match_confidence(SPARSE, scored(8.6), scored(4.8)) == 7


def test_modified_vehicle_caps_at_six():
    ev = SPARSE.model_copy(update={"flags": Flags(modified_vehicle=True)})
    assert match_confidence(ev, scored(8.6), scored(4.8)) == 6


def test_narrow_margin_reduces_confidence():
    wide = match_confidence(FULL_SPEC, scored(13.0), scored(9.0))
    narrow = match_confidence(FULL_SPEC, scored(13.0), scored(12.8))
    assert wide > narrow


def test_conflict_on_winner_reduces_confidence():
    clean = match_confidence(FULL_SPEC, scored(11.0), scored(6.0))
    conflicted = match_confidence(FULL_SPEC, scored(11.0, conflicts=1), scored(6.0))
    assert clean - conflicted == 2


def test_reinterpreted_text_costs_one():
    ev = SPARSE.model_copy(update={"flags": Flags(distractor_stripped=True)})
    assert (
        match_confidence(SPARSE, scored(8.6), scored(4.8))
        - match_confidence(ev, scored(8.6), scored(4.8))
        == 1
    )


def test_sole_candidate_gets_full_margin():
    assert match_confidence(FULL_SPEC, scored(13.0), None) == 9


def test_more_detail_never_lowers_confidence():
    # REQ: a description stating k+1 agreeing attributes must not score below
    # the same description with k attributes (margins held constant).
    ladder = [
        ExtractedVehicle(model="Golf"),
        ExtractedVehicle(make="Volkswagen", model="Golf"),
        ExtractedVehicle(make="Volkswagen", model="Golf", transmission="Automatic"),
        ExtractedVehicle(make="Volkswagen", model="Golf", transmission="Automatic", fuel="Petrol"),
        FULL_SPEC,
    ]
    confidences = [match_confidence(ev, scored(10.0), scored(6.0)) for ev in ladder]
    assert confidences == sorted(confidences)


def test_confidence_always_in_range():
    everything_wrong = ExtractedVehicle(
        flags=Flags(correction_applied=True, distractor_stripped=True, modified_vehicle=True)
    )
    assert 0 <= match_confidence(everything_wrong, scored(4.0, conflicts=3), scored(4.0)) <= 10


# --- null branch: confidence the vehicle is NOT in the catalogue ---


def test_non_vehicle_is_certain_absence():
    ev = ExtractedVehicle(flags=Flags(non_vehicle=True))
    assert null_confidence(ev, MAKES, MODELS) == 10


def test_foreign_make_is_certain_absence():
    ev = ExtractedVehicle(make="Ford", model="Ranger")
    assert null_confidence(ev, MAKES, MODELS) == 10


def test_known_make_foreign_model_is_near_certain():
    ev = ExtractedVehicle(make="Toyota", model="Corolla")
    assert null_confidence(ev, MAKES, MODELS) == 9


def test_catalogue_vehicle_that_scored_badly_is_uncertain_absence():
    ev = ExtractedVehicle(make="Toyota", model="Camry")
    assert null_confidence(ev, MAKES, MODELS) == 7


def test_garbage_is_low_confidence_absence():
    assert null_confidence(ExtractedVehicle(), MAKES, MODELS) == 3

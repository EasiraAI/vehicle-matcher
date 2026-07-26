from vehicle_matcher.models import Candidate, ExtractedVehicle
from vehicle_matcher.scorer import score_all, score_candidate


def make_candidate(**overrides) -> Candidate:
    base = dict(
        id="1",
        make="Volkswagen",
        model="Golf",
        badge="110TSI Comfortline",
        transmission_type="Automatic",
        fuel_type="Petrol",
        drive_type="Front Wheel Drive",
        trgm_score=0.9,
        listing_count=0,
    )
    base.update(overrides)
    return Candidate(**base)


FULL_SPEC = ExtractedVehicle(
    make="Volkswagen",
    model="Golf",
    badge_tokens=["110tsi", "comfortline"],
    transmission="Automatic",
    fuel="Petrol",
    drive="Front Wheel Drive",
)


def test_exact_full_match_scores_high():
    scored = score_candidate(FULL_SPEC, make_candidate())
    assert scored.score == 13.0  # 3+3 +2+2 +1+1+1
    assert scored.conflicts == 0


def test_unstated_attribute_is_not_a_conflict():
    ev = ExtractedVehicle(make="Volkswagen", model="Golf")
    scored = score_candidate(ev, make_candidate())
    assert scored.conflicts == 0
    assert scored.score < score_candidate(FULL_SPEC, make_candidate()).score


def test_conflict_outweighs_unstated():
    stated_wrong = ExtractedVehicle(make="Volkswagen", model="Golf", transmission="Manual")
    unstated = ExtractedVehicle(make="Volkswagen", model="Golf")
    candidate = make_candidate()  # Automatic
    assert (
        score_candidate(stated_wrong, candidate).score < score_candidate(unstated, candidate).score
    )
    assert score_candidate(stated_wrong, candidate).conflicts == 1


def test_model_conflict_is_heavy():
    ev = ExtractedVehicle(make="Toyota", model="Corolla", badge_tokens=["ascent", "sport"])
    camry = make_candidate(make="Toyota", model="Camry", badge="Ascent Sport")
    scored = score_candidate(ev, camry)
    assert scored.conflicts == 1
    assert scored.score < 4.0  # below the default match threshold: forces the null path


def test_badge_asymmetry_input_token_hurts_more_than_surplus():
    # user said a badge word the candidate lacks
    over_described = ExtractedVehicle(model="Golf", badge_tokens=["110tsi", "premium"])
    plain = make_candidate(badge="110TSI")
    # candidate has a badge word the user didn't say
    under_described = ExtractedVehicle(model="Golf", badge_tokens=["110tsi"])
    fancy = make_candidate(badge="110TSI Premium")
    penalty_over = (
        score_candidate(under_described, plain).score - score_candidate(over_described, plain).score
    )
    penalty_under = (
        score_candidate(under_described, plain).score
        - score_candidate(under_described, fancy).score
    )
    assert penalty_over > penalty_under > 0


def test_weak_fuel_signal_never_conflicts():
    ev = ExtractedVehicle(model="Golf", weak_fuel="Petrol")
    diesel = make_candidate(fuel_type="Diesel")
    scored = score_candidate(ev, diesel)
    assert scored.conflicts == 0
    petrol = make_candidate()
    assert score_candidate(ev, petrol).score > scored.score  # agreement still credited


def test_fuzzy_model_match_via_unknown_token():
    ev = ExtractedVehicle(badge_tokens=["highline"], unknown_tokens=["amrok"])
    amarok = make_candidate(model="Amarok", badge="TDI550 Highline", drive_type="Four Wheel Drive")
    tiguan = make_candidate(model="Tiguan", badge="162TSI Highline")
    assert score_candidate(ev, amarok).score > score_candidate(ev, tiguan).score


def test_adjacent_trim_codes_do_not_fuzzy_match():
    ev = ExtractedVehicle(make="Toyota", model="86", badge_tokens=["gt"])
    gts = make_candidate(make="Toyota", model="86", badge="GTS")
    gt = make_candidate(make="Toyota", model="86", badge="GT")
    # "gt" must not partially credit the GTS badge
    assert score_candidate(ev, gt).score - score_candidate(ev, gts).score >= 3.0


def test_tiebreak_by_listing_count():
    ev = ExtractedVehicle(make="Toyota", model="86", badge_tokens=["gt"])
    few = make_candidate(id="few", make="Toyota", model="86", badge="GT", listing_count=3)
    many = make_candidate(id="many", make="Toyota", model="86", badge="GT", listing_count=30)
    ranked = score_all(ev, [few, many])
    assert ranked[0].candidate.id == "many"


def test_listing_prior_breaks_near_ties_but_not_real_differences():
    ev = ExtractedVehicle(make="Toyota", model="86", badge_tokens=["gt"])
    right_unpopular = make_candidate(id="right", make="Toyota", model="86", badge="GT")
    wrong_popular = make_candidate(
        id="wrong", make="Toyota", model="86", badge="GTS", listing_count=100
    )
    ranked = score_all(ev, [right_unpopular, wrong_popular])
    assert ranked[0].candidate.id == "right"  # popularity never overrides evidence


def test_deterministic_ordering():
    ev = ExtractedVehicle(make="Toyota", model="86")
    candidates = [make_candidate(id=str(i), make="Toyota", model="86") for i in range(5)]
    assert [s.candidate.id for s in score_all(ev, candidates)] == [
        s.candidate.id for s in score_all(ev, list(reversed(candidates)))
    ]

"""End-to-end acceptance over the challenge data: every line of inputs.txt
produces a result, and the four known outputs from the challenge README (the
only ground truth provided) reproduce exactly."""

from pathlib import Path

import pytest

from vehicle_matcher.config import get_settings
from vehicle_matcher.matcher import Matcher

pytestmark = pytest.mark.integration

INPUTS = Path(__file__).parents[2] / "data" / "inputs.txt"

# The challenge README's example outputs — IDs must be exact; these three
# appear verbatim in inputs.txt.
ANCHORS = {
    "Volkswagen Golf 110TSI Comfortline Petrol Automatic Front Wheel Drive": (
        "4749339721203712",
        9,
    ),
    "VW Amarok Ultimate": ("4951649860714496", 7),
    "VW Golf R with engine swap from Toyota 86 GT": ("5824662093168640", 6),
}
# The fourth anchor is not in inputs.txt but is equally binding.
NULL_ANCHOR = ("Ford Ranger XLT Dual Cab", None, 10)


@pytest.fixture(scope="module")
def matcher(db_conn):
    return Matcher(db_conn, settings=get_settings())


@pytest.fixture(scope="module")
def descriptions():
    lines = [ln.strip() for ln in INPUTS.read_text(encoding="utf-8").splitlines()]
    return [ln for ln in lines if ln]


def test_every_description_produces_a_result(matcher, descriptions):
    assert len(descriptions) == 20
    for description in descriptions:
        result = matcher.match(description)
        assert result.vehicle_id is None or result.vehicle_id.isdigit()
        assert 0 <= result.confidence <= 10


def test_anchor_matches_exact(matcher):
    for description, (vehicle_id, confidence) in ANCHORS.items():
        result = matcher.match(description)
        assert result.vehicle_id == vehicle_id, description
        assert result.confidence == confidence, description


def test_anchor_null(matcher):
    description, vehicle_id, confidence = NULL_ANCHOR
    result = matcher.match(description)
    assert result.vehicle_id is vehicle_id
    assert result.confidence == confidence


def test_non_vehicle_is_confident_null(matcher):
    result = matcher.match("Golf cart")
    assert result.vehicle_id is None
    assert result.confidence == 10


def test_known_make_unknown_model_is_confident_null(matcher):
    result = matcher.match("Toyota Corolla Ascent Sport Auto")
    assert result.vehicle_id is None
    assert result.confidence >= 8


def test_misspelled_model_still_matches(matcher):
    # "Amrok h/line 4x4" -> Amarok TDI550 Highline (4WD): fuzzy retrieval +
    # alias expansion, at modest confidence.
    result = matcher.match("Amrok h/line 4x4")
    assert result.vehicle_id is not None
    assert result.debug.scored[0].candidate.model == "Amarok"
    assert "Highline" in result.debug.scored[0].candidate.badge
    assert result.debug.scored[0].candidate.drive_type == "Four Wheel Drive"
    assert result.confidence <= 6  # heavy reinterpretation must not read as certainty


def test_correction_overrides_original_text(matcher):
    result = matcher.match(
        "Toyota Kluger Sports Hybrid (It's actually a Toyota 86 GT"
        " but the website didn't let me select that, sorry)"
    )
    top = result.debug.scored[0].candidate
    assert top.model == "86"
    assert top.badge == "GT"


def test_tie_broken_by_listing_count(matcher, db_conn):
    # "Toyota 86 GT" with no transmission: two GT rows carry identical evidence
    # and differ only by transmission. The listing prior and the explicit
    # tie-break both point the same way: the most-listed GT must win.
    result = matcher.match("Toyota 86 GT")
    top_two = result.debug.scored[:2]
    assert {top_two[0].candidate.badge, top_two[1].candidate.badge} == {"GT"}
    assert top_two[0].candidate.listing_count >= top_two[1].candidate.listing_count
    row = db_conn.execute(
        """
        SELECT s.vehicle_id FROM vehicle_listing_stats s
        JOIN vehicle v ON v.id = s.vehicle_id
        WHERE v.model = '86' AND v.badge = 'GT'
        ORDER BY s.listing_count DESC LIMIT 1
        """
    ).fetchone()
    assert result.vehicle_id == row[0]


def test_snapshot_of_all_twenty(matcher, descriptions):
    """Full-run snapshot: any change to matcher behaviour on the challenge
    inputs must show up in review as a diff of this expectation."""
    snapshot_path = Path(__file__).parent / "snapshots" / "inputs_txt.txt"
    actual = "\n".join(
        f"{r.vehicle_id or 'null'}@{r.confidence}" for r in (matcher.match(d) for d in descriptions)
    )
    if not snapshot_path.exists():
        snapshot_path.parent.mkdir(exist_ok=True)
        snapshot_path.write_text(actual + "\n", encoding="utf-8")
        pytest.skip("snapshot created; rerun to verify")
    assert actual + "\n" == snapshot_path.read_text(encoding="utf-8")

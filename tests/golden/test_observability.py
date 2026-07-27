"""Decision provenance and the structured match log — the operational
contract, pinned. Every result must carry the version of the logic that made
it, and every match must emit one parseable JSON event with the fields the
drift/cost/latency dashboards are built from."""

import json
import logging

import pytest

from vehicle_matcher.config import get_settings
from vehicle_matcher.matcher import Matcher

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def matcher(db_conn):
    return Matcher(db_conn, settings=get_settings())


def test_every_result_carries_the_matcher_version(matcher):
    for text in ("Golf GTI", "Ford Ranger XLT Dual Cab", "Golf cart"):
        result = matcher.match(text)
        assert result.matcher_version == matcher.version
        assert result.matcher_version.startswith("0.")
        assert "+cfg." in result.matcher_version


def test_version_is_stable_for_identical_configuration(db_conn):
    settings = get_settings()
    assert (
        Matcher(db_conn, settings=settings).version == Matcher(db_conn, settings=settings).version
    )


def test_version_changes_when_a_decision_input_changes(db_conn):
    base = get_settings()
    retuned = base.model_copy(update={"min_match_score": base.min_match_score + 1.0})
    assert Matcher(db_conn, settings=base).version != Matcher(db_conn, settings=retuned).version


def test_match_emits_one_structured_log_event(matcher, caplog):
    with caplog.at_level(logging.INFO, logger="vehicle_matcher.match"):
        result = matcher.match("VW Amarok Ultimate")

    events = [json.loads(r.message) for r in caplog.records if r.name == "vehicle_matcher.match"]
    assert len(events) == 1
    event = events[0]
    assert event["event"] == "match"
    assert event["vehicle_id"] == result.vehicle_id
    assert event["confidence"] == result.confidence
    assert event["tier"] == "rules"
    assert event["matcher_version"] == result.matcher_version
    assert event["candidate_count"] > 0
    assert event["top_score"] is not None and event["margin"] is not None
    assert event["duration_ms"] >= 0
    assert len(event["input_hash"]) == 16
    # the raw description is deliberately NOT logged — only its hash and length
    assert "Amarok" not in json.dumps(event.get("input_text", ""))
    assert event["extracted"]["model"] == "Amarok"


def test_log_hash_is_stable_across_cosmetic_variation(matcher, caplog):
    with caplog.at_level(logging.INFO, logger="vehicle_matcher.match"):
        matcher.match("VW Amarok Ultimate")
        matcher.match("  vw amarok ULTIMATE ")
    events = [json.loads(r.message) for r in caplog.records if r.name == "vehicle_matcher.match"]
    assert events[0]["input_hash"] == events[1]["input_hash"]

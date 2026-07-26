"""Router contract for the optional LLM tier, with a stub extractor (no API):
escalation only below the gate, the better result wins, and the LLM can only
ever supply an extraction — the ID still comes from the deterministic pipeline.
"""

import pytest

from vehicle_matcher.config import Settings
from vehicle_matcher.matcher import Matcher
from vehicle_matcher.models import ExtractedVehicle

pytestmark = pytest.mark.integration


def settings(**overrides) -> Settings:
    base = dict(llm_enabled=True, llm_gate=5)
    base.update(overrides)
    return Settings(**base)


def test_confident_rules_result_never_escalates(db_conn):
    calls = []

    def fallback(text):
        calls.append(text)
        return None

    matcher = Matcher(db_conn, settings=settings(), fallback_extractor=fallback)
    result = matcher.match("Volkswagen Golf 110TSI Comfortline Petrol Automatic Front Wheel Drive")
    assert result.confidence == 9
    assert calls == []  # above the gate: no LLM spend


def test_low_confidence_escalates_and_better_extraction_wins(db_conn):
    # Rules can't read this phrasing; the stub "LLM" extracts it properly.
    def fallback(text):
        return ExtractedVehicle(
            make="Volkswagen", model="Golf", badge_tokens=["gti"], transmission="Automatic"
        )

    matcher = Matcher(db_conn, settings=settings(), fallback_extractor=fallback)
    garbled = "vdub hot hatch the three letter one"
    rules_only = Matcher(db_conn, settings=settings(llm_enabled=False)).match(garbled)
    escalated = matcher.match(garbled)

    assert escalated.confidence > rules_only.confidence
    assert escalated.debug.tier == "llm"
    assert escalated.debug.scored[0].candidate.badge == "GTI"  # ID chosen by scorer, not stub


def test_failed_llm_extraction_keeps_rules_result(db_conn):
    matcher = Matcher(db_conn, settings=settings(), fallback_extractor=lambda text: None)
    result = matcher.match("mystery hatchback thing")
    assert result.debug.tier == "rules"
    assert 0 <= result.confidence <= 10


def test_non_vehicle_never_escalates(db_conn):
    calls = []

    def fallback(text):
        calls.append(text)
        return None

    matcher = Matcher(db_conn, settings=settings(), fallback_extractor=fallback)
    result = matcher.match("Golf cart")
    assert result.vehicle_id is None and result.confidence == 10
    assert calls == []

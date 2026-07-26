"""Replay of a real recorded API response (captured from a live run against
claude-haiku, 2026-07-27) through the extractor's cache path — no network.
The stub-client tests prove our contract; this one pins the actual wire shape
the model returned, so an SDK or schema drift shows up as a test failure
rather than a production surprise."""

from pathlib import Path

from vehicle_matcher.config import Settings
from vehicle_matcher.llm_extractor import LLMExtractor

CASSETTE = Path(__file__).parents[1] / "fixtures" / "llm_cassette.json"

# The exact input the response was recorded for (cache key = sha256 of this,
# stripped and lowercased).
RECORDED_INPUT = (
    "Toyota Kluger Sports Hybrid (It's actually a Toyota 86 GT"
    " but the website didn't let me select that, sorry)"
)


class ExplodingClient:
    """The test fails loudly if the cassette misses and a network call starts."""

    def __getattr__(self, name: str):
        raise AssertionError("cassette miss: extractor attempted a live API call")


def test_recorded_response_parses_into_extraction():
    extractor = LLMExtractor(
        Settings(dsn="postgresql://unused", llm_enabled=True),
        client=ExplodingClient(),
        cache_path=CASSETTE,
    )
    ev = extractor(RECORDED_INPUT)

    assert ev is not None
    assert ev.make == "Toyota"
    assert ev.model == "86"
    assert ev.badge_tokens == ["gt"]
    assert ev.transmission is None and ev.fuel is None and ev.drive is None
    assert ev.flags.correction_applied
    assert not ev.flags.non_vehicle
    # The model read the retracted "Kluger Sports Hybrid" mention correctly:
    # nothing from it leaked into the extraction.
    assert "sport" not in ev.badge_tokens

"""LLM tier contract: offline only — a fake client, never a live API."""

from types import SimpleNamespace

from vehicle_matcher.config import Settings
from vehicle_matcher.llm_extractor import LLMExtractor


class FakeClient:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = 0
        self.messages = self

    def create(self, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        block = SimpleNamespace(type="tool_use", input=self.payload)
        return SimpleNamespace(content=[block])


PAYLOAD = {
    "make": "Volkswagen",
    "model": "Golf",
    "badge_tokens": ["GTI"],
    "transmission": None,
    "fuel": None,
    "drive": None,
    "non_vehicle": False,
}


def settings() -> Settings:
    return Settings(llm_enabled=True, dsn="postgresql://unused")


def test_parses_tool_use_into_extracted_vehicle():
    extractor = LLMExtractor(settings(), client=FakeClient(payload=PAYLOAD))
    ev = extractor("Golf GTI")
    assert ev is not None
    assert ev.make == "Volkswagen"
    assert ev.badge_tokens == ["gti"]  # normalised to lowercase
    assert ev.transmission is None  # unstated stays unstated


def test_api_failure_degrades_to_none_not_exception():
    extractor = LLMExtractor(settings(), client=FakeClient(error=TimeoutError("slow")))
    assert extractor("Golf GTI") is None


def test_repeat_calls_hit_cache(tmp_path):
    client = FakeClient(payload=PAYLOAD)
    extractor = LLMExtractor(settings(), client=client, cache_path=tmp_path / "cache.json")
    first = extractor("Golf GTI")
    second = extractor("golf gti")  # same content hash after normalisation
    assert client.calls == 1
    assert first == second


def test_cache_survives_process_restart(tmp_path):
    path = tmp_path / "cache.json"
    LLMExtractor(settings(), client=FakeClient(payload=PAYLOAD), cache_path=path)("Golf GTI")
    fresh_client = FakeClient(payload=PAYLOAD)
    ev = LLMExtractor(settings(), client=fresh_client, cache_path=path)("Golf GTI")
    assert fresh_client.calls == 0
    assert ev is not None and ev.model == "Golf"


def test_malformed_payload_degrades_to_none():
    extractor = LLMExtractor(settings(), client=FakeClient(payload={"badge_tokens": "not-a-list"}))
    assert extractor("Golf GTI") is None

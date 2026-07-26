"""Optional LLM extraction tier. Disabled by default (MATCHER_LLM_ENABLED).

Scope is deliberately narrow: the model reads ONE description and fills in the
same ExtractedVehicle record the rule extractor produces. It never sees
catalogue rows and never returns a vehicle ID — matching stays deterministic
and replayable. Responses are cached by content hash, so re-runs are free and
deterministic; any API failure degrades to the rules result instead of dying.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from .config import Settings
from .models import ExtractedVehicle

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You extract vehicle attributes from one marketplace car description.

Rules:
- Report only what the text states. Leave attributes null when unstated — never
  infer transmission, fuel, or drive from the kind of car it is.
- If the text corrects itself ("it's actually a ..."), extract the corrected vehicle.
- If the text mentions a second vehicle the seller wants or swapped parts from
  ("in exchange for ...", "engine swap from ..."), extract only the vehicle being
  sold and set the matching flag.
- If the text is not a road vehicle at all (golf cart, go kart), set non_vehicle.
- badge_tokens are trim/variant words (e.g. "highline", "gti", "110tsi"),
  lowercase, expanded from abbreviations ("h/line" -> "highline").
"""

_TOOL = {
    "name": "record_extraction",
    "description": "Record the attributes extracted from the description.",
    "input_schema": {
        "type": "object",
        "properties": {
            "make": {"type": ["string", "null"]},
            "model": {"type": ["string", "null"]},
            "badge_tokens": {"type": "array", "items": {"type": "string"}},
            "transmission": {"type": ["string", "null"], "enum": ["Automatic", "Manual", None]},
            "fuel": {
                "type": ["string", "null"],
                "enum": ["Petrol", "Diesel", "Hybrid-Petrol", None],
            },
            "drive": {
                "type": ["string", "null"],
                "enum": ["Front Wheel Drive", "Rear Wheel Drive", "Four Wheel Drive", None],
            },
            "correction_applied": {"type": "boolean"},
            "distractor_stripped": {"type": "boolean"},
            "modified_vehicle": {"type": "boolean"},
            "non_vehicle": {"type": "boolean"},
        },
        "required": ["badge_tokens"],
    },
}


class LLMExtractor:
    def __init__(self, settings: Settings, client: Any = None, cache_path: Path | None = None):
        self._settings = settings
        self._client = client  # injectable for tests; real client built lazily
        self._cache_path = cache_path
        self._cache: dict[str, dict[str, Any]] = {}
        if cache_path is not None and cache_path.exists():
            self._cache = json.loads(cache_path.read_text(encoding="utf-8"))

    def __call__(self, text: str) -> ExtractedVehicle | None:
        key = hashlib.sha256(text.strip().lower().encode()).hexdigest()
        try:
            if key in self._cache:
                return self._to_extracted(self._cache[key])
            payload = self._call_api(text)
            extracted = self._to_extracted(payload)  # validate BEFORE caching
        except Exception:
            logger.warning("LLM extraction failed; keeping rules result", exc_info=True)
            return None
        self._cache[key] = payload
        if self._cache_path is not None:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(json.dumps(self._cache, indent=1), encoding="utf-8")
        return extracted

    def _call_api(self, text: str) -> dict[str, Any]:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(
                api_key=self._settings.anthropic_api_key,  # None -> SDK env fallback
                timeout=self._settings.llm_timeout_s,
            )
        response = self._client.messages.create(
            model=self._settings.llm_model,
            max_tokens=500,
            temperature=0,
            system=_SYSTEM_PROMPT,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "record_extraction"},
            messages=[{"role": "user", "content": text}],
        )
        for block in response.content:
            if block.type == "tool_use":
                return dict(block.input)
        raise ValueError("no tool_use block in LLM response")

    @staticmethod
    def _to_extracted(payload: dict[str, Any]) -> ExtractedVehicle:
        badge_tokens = payload.get("badge_tokens", [])
        if not isinstance(badge_tokens, list):
            raise TypeError(f"badge_tokens must be a list, got {type(badge_tokens).__name__}")
        flag_names = (
            "correction_applied",
            "distractor_stripped",
            "modified_vehicle",
            "non_vehicle",
        )
        return ExtractedVehicle(
            make=payload.get("make"),
            model=payload.get("model"),
            badge_tokens=[str(t).lower() for t in badge_tokens],
            transmission=payload.get("transmission"),
            fuel=payload.get("fuel"),
            drive=payload.get("drive"),
            flags={name: bool(payload.get(name)) for name in flag_names},  # type: ignore[arg-type]
        )

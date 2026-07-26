from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import psycopg

from .calibrator import match_confidence, null_confidence
from .config import Settings, get_settings
from .extractor import extract
from .models import ExtractedVehicle, MatchDebug, MatchResult
from .retrieval import configure_session, fetch_candidates
from .scorer import score_all
from .vocabulary import Vocabulary, load_vocabulary

# Any callable text -> ExtractedVehicle | None fits here; the LLM extractor is
# one implementation. None means "extraction unavailable" (error, timeout) and
# the rules result stands.
FallbackExtractor = Callable[[str], ExtractedVehicle | None]


class Matcher:
    def __init__(
        self,
        conn: psycopg.Connection,
        settings: Settings | None = None,
        vocabulary: Vocabulary | None = None,
        fallback_extractor: FallbackExtractor | None = None,
    ) -> None:
        self._conn = conn
        self._settings = settings or get_settings()
        self._vocab = vocabulary or load_vocabulary(conn)
        self._fallback = fallback_extractor
        configure_session(conn, self._settings)

    def match(self, text: str) -> MatchResult:
        extracted = extract(text, self._vocab)
        result = self._run(extracted, tier="rules")

        # Escalate only when rules are unsure. The fallback re-extracts the
        # text; matching itself always runs through the same deterministic
        # retrieve/score/calibrate pipeline — no extractor ever picks an ID.
        if (
            self._fallback is not None
            and self._settings.llm_enabled
            and result.confidence < self._settings.llm_gate
            and not extracted.flags.non_vehicle
        ):
            fallback_extracted = self._fallback(text)
            if fallback_extracted is not None:
                fallback_result = self._run(fallback_extracted, tier="llm")
                if fallback_result.confidence > result.confidence:
                    result = fallback_result

        return result

    def _run(self, extracted: ExtractedVehicle, tier: Literal["rules", "llm"]) -> MatchResult:
        debug = MatchDebug(extracted=extracted, tier=tier)

        if extracted.flags.non_vehicle:
            return MatchResult(vehicle_id=None, confidence=10, debug=debug)

        candidates = fetch_candidates(self._conn, extracted, self._settings)
        scored = score_all(extracted, candidates)

        debug.candidate_count = len(scored)
        debug.scored = scored[:5]
        if scored:
            debug.top_score = scored[0].score
        if len(scored) > 1:
            debug.runner_up_score = scored[1].score

        if scored and scored[0].score >= self._settings.min_match_score:
            confidence = match_confidence(
                extracted, scored[0], scored[1] if len(scored) > 1 else None
            )
            return MatchResult(
                vehicle_id=scored[0].candidate.id, confidence=confidence, debug=debug
            )

        confidence = null_confidence(
            extracted, self._vocab.catalogue_makes, self._vocab.catalogue_models
        )
        return MatchResult(vehicle_id=None, confidence=confidence, debug=debug)

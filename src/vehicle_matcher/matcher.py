from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import time
from collections.abc import Callable
from typing import Literal

import psycopg

from . import __version__
from .calibrator import match_confidence, null_confidence
from .config import Settings, get_settings
from .extractor import canonicalize, extract
from .models import ExtractedVehicle, MatchDebug, MatchResult
from .retrieval import configure_session, fetch_candidates
from .scorer import DEFAULT_WEIGHTS, score_all
from .vocabulary import Vocabulary, load_vocabulary

# One JSON line per match at INFO. The library attaches no handler (standard
# library etiquette); the CLI's --log flag or any host application's logging
# config makes the stream visible. These fields are the operational contract:
# match rate, null rate, low-confidence rate (drift alarm), escalation rate
# (cost alarm), and latency percentiles are all derivable from them.
logger = logging.getLogger("vehicle_matcher.match")

# Any callable text -> ExtractedVehicle | None fits here; the LLM extractor is
# one implementation. None means "extraction unavailable" (error, timeout) and
# the rules result stands.
FallbackExtractor = Callable[[str], ExtractedVehicle | None]


def _config_fingerprint(settings: Settings, vocab: Vocabulary) -> str:
    """Hash of everything that can change a decision without a code change."""
    payload = json.dumps(
        {
            "weights": dataclasses.asdict(DEFAULT_WEIGHTS),
            "aliases": sorted(
                (text, e.attribute, e.canonical, e.weak) for text, e in vocab.aliases.items()
            ),
            "makes": sorted(vocab.catalogue_makes),
            "models": sorted(vocab.catalogue_models),
            "badge_tokens": sorted(vocab.badge_tokens),
            "candidate_k": settings.candidate_k,
            "min_match_score": settings.min_match_score,
            "model_sim_threshold": settings.model_sim_threshold,
            "token_sim_threshold": settings.token_sim_threshold,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


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
        self.version = f"{__version__}+cfg.{_config_fingerprint(self._settings, self._vocab)}"
        configure_session(conn, self._settings)

    def match(self, text: str) -> MatchResult:
        started = time.perf_counter()
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
                fallback_result = self._run(
                    canonicalize(fallback_extracted, self._vocab), tier="llm"
                )
                if fallback_result.confidence > result.confidence:
                    result = fallback_result

        self._log(text, result, started)
        return result

    def match_extracted(
        self, extracted: ExtractedVehicle, tier: Literal["rules", "llm"] = "llm"
    ) -> MatchResult:
        """Run the deterministic pipeline over an externally produced
        extraction (canonicalized first, like any fallback extraction). Used
        by the shadow audit to compare an independent extraction against the
        rules path on the same text."""
        return self._run(canonicalize(extracted, self._vocab), tier=tier)

    def _run(self, extracted: ExtractedVehicle, tier: Literal["rules", "llm"]) -> MatchResult:
        debug = MatchDebug(extracted=extracted, tier=tier)

        if extracted.flags.non_vehicle:
            return MatchResult(
                vehicle_id=None, confidence=10, matcher_version=self.version, debug=debug
            )

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
                vehicle_id=scored[0].candidate.id,
                confidence=confidence,
                matcher_version=self.version,
                debug=debug,
            )

        confidence = null_confidence(
            extracted, self._vocab.catalogue_makes, self._vocab.catalogue_models
        )
        return MatchResult(
            vehicle_id=None, confidence=confidence, matcher_version=self.version, debug=debug
        )

    def _log(self, text: str, result: MatchResult, started: float) -> None:
        if not logger.isEnabledFor(logging.INFO):
            return
        d = result.debug
        logger.info(
            json.dumps(
                {
                    "event": "match",
                    "input_hash": hashlib.sha256(text.strip().lower().encode()).hexdigest()[:16],
                    "input_chars": len(text),
                    "extracted": d.extracted.model_dump(exclude_none=True, exclude_defaults=True),
                    "candidate_count": d.candidate_count,
                    "top_score": d.top_score,
                    "margin": (
                        round(d.top_score - d.runner_up_score, 4)
                        if d.top_score is not None and d.runner_up_score is not None
                        else None
                    ),
                    "vehicle_id": result.vehicle_id,
                    "confidence": result.confidence,
                    "tier": d.tier,
                    "matcher_version": result.matcher_version,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
                default=str,
            )
        )

from __future__ import annotations

import math
from dataclasses import dataclass
from difflib import SequenceMatcher

from .models import Candidate, ExtractedVehicle, ScoredCandidate


@dataclass(frozen=True)
class Weights:
    """Score contributions per attribute outcome.

    Asymmetries are deliberate:
    - A stated attribute the candidate contradicts is punished far harder than
      an unstated one (unstated != conflict).
    - A badge token the user stated but the candidate lacks (-1.0) hurts more
      than surplus candidate tokens the user didn't mention (-0.4): people
      under-describe their car far more often than they over-describe it.
    - Weak signals (TSI => Petrol) earn half credit and never conflict.
    """

    make_match: float = 3.0
    make_fuzzy: float = 2.0
    make_conflict: float = -6.0
    model_match: float = 3.0
    model_fuzzy: float = 2.2
    model_conflict: float = -6.0
    badge_match: float = 2.0
    badge_fuzzy: float = 1.2
    badge_input_unmatched: float = -1.0
    badge_candidate_surplus: float = -0.4
    attr_match: float = 1.0  # transmission / fuel / drive
    attr_conflict: float = -2.5
    weak_attr_match: float = 0.5
    listing_prior: float = 0.3
    fuzzy_floor: float = 0.75  # SequenceMatcher ratio to accept a fuzzy model/make
    # 0.85, not 0.8: adjacent trim codes are exactly 0.8 apart ("gt"/"gts",
    # "gx"/"gxl") and are different vehicles, not typos of each other.
    badge_fuzzy_floor: float = 0.85


DEFAULT_WEIGHTS = Weights()


@dataclass
class _Tally:
    score: float = 0.0
    conflicts: int = 0

    def add(self, points: float, conflict: bool = False) -> None:
        self.score += points
        if conflict:
            self.conflicts += 1


def _fuzzy(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def score_candidate(
    extracted: ExtractedVehicle, candidate: Candidate, weights: Weights = DEFAULT_WEIGHTS
) -> ScoredCandidate:
    t = _Tally()

    # make / model: matched, contradicted, or (via unknown tokens) fuzzy-matched
    _score_name(
        t,
        extracted.make,
        candidate.make,
        extracted,
        weights.make_match,
        weights.make_fuzzy,
        weights.make_conflict,
        weights,
    )
    _score_name(
        t,
        extracted.model,
        candidate.model,
        extracted,
        weights.model_match,
        weights.model_fuzzy,
        weights.model_conflict,
        weights,
    )

    _score_badges(t, extracted, candidate, weights)

    for stated, actual, weak in (
        (extracted.transmission, candidate.transmission_type, extracted.weak_transmission),
        (extracted.fuel, candidate.fuel_type, extracted.weak_fuel),
        (extracted.drive, candidate.drive_type, None),
    ):
        if stated is not None:
            if stated == actual:
                t.add(weights.attr_match)
            else:
                t.add(weights.attr_conflict, conflict=True)
        elif weak is not None and weak == actual:
            t.add(weights.weak_attr_match)

    t.add(weights.listing_prior * math.log1p(candidate.listing_count))

    return ScoredCandidate(candidate=candidate, score=round(t.score, 4), conflicts=t.conflicts)


def _score_name(
    t: _Tally,
    stated: str | None,
    actual: str,
    extracted: ExtractedVehicle,
    match_w: float,
    fuzzy_w: float,
    conflict_w: float,
    weights: Weights,
) -> None:
    if stated is not None:
        if stated.lower() == actual.lower():
            t.add(match_w)
        else:
            t.add(conflict_w, conflict=True)
    else:
        # Not recognised as a make/model — but an unknown token may be a
        # misspelling of this candidate's name ("Amrok" ~ "Amarok").
        best = max((_fuzzy(tok, actual) for tok in extracted.unknown_tokens), default=0.0)
        if best >= weights.fuzzy_floor:
            t.add(fuzzy_w)


def _score_badges(
    t: _Tally, extracted: ExtractedVehicle, candidate: Candidate, weights: Weights
) -> None:
    candidate_tokens = candidate.badge.lower().split()
    remaining = list(candidate_tokens)
    for token in extracted.badge_tokens:
        if token in remaining:
            remaining.remove(token)
            t.add(weights.badge_match)
            continue
        fuzzy_hit = next(
            (c for c in remaining if _fuzzy(token, c) >= weights.badge_fuzzy_floor), None
        )
        if fuzzy_hit is not None:
            remaining.remove(fuzzy_hit)
            t.add(weights.badge_fuzzy)
        else:
            t.add(weights.badge_input_unmatched)
    t.add(weights.badge_candidate_surplus * len(remaining))


def score_all(
    extracted: ExtractedVehicle,
    candidates: list[Candidate],
    weights: Weights = DEFAULT_WEIGHTS,
) -> list[ScoredCandidate]:
    """Score every candidate, best first.

    Sort key is (score, listing_count, id): the listing count implements the
    challenge's tie-break rule — equally likely vehicles resolve to the one
    with the most listings — and the id makes ordering fully deterministic.
    """
    scored = [score_candidate(extracted, c, weights) for c in candidates]
    scored.sort(key=lambda s: (s.score, s.candidate.listing_count, s.candidate.id), reverse=True)
    return scored

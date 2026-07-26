"""Accuracy scorecard against a labeled evaluation set.

A label is the set of acceptable vehicle IDs for a description (more than one
where the description is genuinely ambiguous, e.g. "Toyota Camry Hybrid"), or
null when the vehicle is absent from the catalogue. The report covers the
metrics that matter for this use case: top-1 accuracy, match/null precision
and recall, mean reciprocal rank, and a reliability table showing whether
higher confidence actually means higher accuracy.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .matcher import Matcher
from .models import MatchResult


@dataclass(frozen=True)
class EvalCase:
    description: str
    acceptable: frozenset[str]  # empty set means the truth is null


@dataclass(frozen=True)
class BucketRow:
    bucket: str
    n: int
    correct: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.n if self.n else 0.0


@dataclass(frozen=True)
class EvalReport:
    n: int
    accuracy: float
    match_precision: float
    match_recall: float
    null_precision: float
    null_recall: float
    mrr: float
    reliability: list[BucketRow]
    failures: list[tuple[str, str | None, int]]  # description, got, confidence


# Coarse confidence buckets: with a small labeled set, ten buckets would be
# noise; three is enough to catch an inverted calibration.
_BUCKETS = (("low 0-4", 0, 4), ("mid 5-7", 5, 7), ("high 8-10", 8, 10))


def load_cases(path: Path) -> list[EvalCase]:
    cases = []
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            label = row["label"].strip()
            acceptable = frozenset() if label == "null" else frozenset(label.split("|"))
            cases.append(EvalCase(row["description"], acceptable))
    return cases


def _is_correct(case: EvalCase, result: MatchResult) -> bool:
    if not case.acceptable:
        return result.vehicle_id is None
    return result.vehicle_id in case.acceptable


def _reciprocal_rank(case: EvalCase, result: MatchResult) -> float:
    for rank, scored in enumerate(result.debug.scored, start=1):
        if scored.candidate.id in case.acceptable:
            return 1.0 / rank
    return 0.0


def evaluate(matcher: Matcher, cases: list[EvalCase]) -> EvalReport:
    results = [(case, matcher.match(case.description)) for case in cases]

    correct = sum(_is_correct(c, r) for c, r in results)
    predicted_match = [(c, r) for c, r in results if r.vehicle_id is not None]
    predicted_null = [(c, r) for c, r in results if r.vehicle_id is None]
    should_match = [(c, r) for c, r in results if c.acceptable]
    should_null = [(c, r) for c, r in results if not c.acceptable]

    def ratio(pairs: list[tuple[EvalCase, MatchResult]]) -> float:
        return sum(_is_correct(c, r) for c, r in pairs) / len(pairs) if pairs else 1.0

    buckets = []
    for name, lo, hi in _BUCKETS:
        rows = [(c, r) for c, r in results if lo <= r.confidence <= hi]
        buckets.append(BucketRow(name, len(rows), sum(_is_correct(c, r) for c, r in rows)))

    return EvalReport(
        n=len(results),
        accuracy=correct / len(results) if results else 0.0,
        match_precision=ratio(predicted_match),
        match_recall=ratio(should_match),
        null_precision=ratio(predicted_null),
        null_recall=ratio(should_null),
        mrr=(
            sum(_reciprocal_rank(c, r) for c, r in should_match) / len(should_match)
            if should_match
            else 1.0
        ),
        reliability=buckets,
        failures=[
            (c.description, r.vehicle_id, r.confidence) for c, r in results if not _is_correct(c, r)
        ],
    )


def format_report(report: EvalReport) -> str:
    lines = [
        f"cases:            {report.n}",
        f"top-1 accuracy:   {report.accuracy:.1%}",
        f"match precision:  {report.match_precision:.1%}   (of returned IDs, how many right)",
        f"match recall:     {report.match_recall:.1%}   (of matchable cases, how many matched)",
        f"null precision:   {report.null_precision:.1%}   (of returned nulls, truly absent)",
        f"null recall:      {report.null_recall:.1%}   (of absent vehicles, how many caught)",
        f"MRR:              {report.mrr:.3f}",
        "",
        "reliability (does confidence track accuracy?):",
    ]
    for row in report.reliability:
        pct = f"{row.accuracy:.0%}" if row.n else "-"
        lines.append(f"  {row.bucket:<10}  n={row.n:<3}  accuracy={pct}")
    if report.failures:
        lines.append("")
        lines.append("failures:")
        lines.extend(f"  {d!r} -> {got}@{conf}" for d, got, conf in report.failures)
    return "\n".join(lines)

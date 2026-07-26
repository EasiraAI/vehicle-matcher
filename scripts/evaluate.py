"""Run the accuracy scorecard against a labeled CSV.

Usage:
    python scripts/evaluate.py                          # bundled labels
    python scripts/evaluate.py path/to/labels.csv --min-accuracy 0.9

CSV columns: description,label — where label is one or more acceptable
vehicle IDs separated by "|", or the word "null" for a vehicle that is
absent from the catalogue.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vehicle_matcher.config import get_settings  # noqa: E402
from vehicle_matcher.evaluation import evaluate, format_report, load_cases  # noqa: E402
from vehicle_matcher.matcher import Matcher  # noqa: E402

DEFAULT_LABELS = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "eval_labels.csv"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labels", nargs="?", type=Path, default=DEFAULT_LABELS)
    parser.add_argument(
        "--min-accuracy",
        type=float,
        default=None,
        help="exit non-zero if top-1 accuracy falls below this",
    )
    args = parser.parse_args()

    settings = get_settings()
    cases = load_cases(args.labels)
    with psycopg.connect(settings.dsn) as conn:
        report = evaluate(Matcher(conn, settings=settings), cases)

    print(format_report(report))
    if args.min_accuracy is not None and report.accuracy < args.min_accuracy:
        print(f"\nFAIL: accuracy {report.accuracy:.1%} < floor {args.min_accuracy:.1%}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

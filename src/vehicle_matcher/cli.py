from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import psycopg

from .config import get_settings
from .llm_extractor import LLMExtractor
from .matcher import Matcher


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vehicle_matcher", description="Match car descriptions to catalogue vehicles."
    )
    parser.add_argument("inputs", type=Path, help="text file, one description per line")
    parser.add_argument("--debug", action="store_true", help="show score breakdown per input")
    parser.add_argument(
        "--log", action="store_true", help="emit the structured JSON match log to stderr"
    )
    args = parser.parse_args(argv)

    if args.log:
        handler = logging.StreamHandler(sys.stderr)
        match_logger = logging.getLogger("vehicle_matcher")
        match_logger.addHandler(handler)
        match_logger.setLevel(logging.INFO)

    settings = get_settings()
    fallback = None
    if settings.llm_enabled:
        fallback = LLMExtractor(settings, cache_path=Path(".cache/llm_extractions.json"))

    lines = [ln.strip() for ln in args.inputs.read_text(encoding="utf-8").splitlines()]
    descriptions = [ln for ln in lines if ln]

    with psycopg.connect(settings.dsn) as conn:
        matcher = Matcher(conn, settings=settings, fallback_extractor=fallback)
        for description in descriptions:
            result = matcher.match(description)
            print(f"Input: {description}")
            print(f"Vehicle ID: {result.vehicle_id if result.vehicle_id else 'null'}")
            print(f"Confidence: {result.confidence}")
            if args.debug:
                _print_debug(result)
            print()
    return 0


def _print_debug(result) -> None:  # type: ignore[no-untyped-def]
    d = result.debug
    print(f"  tier={d.tier} candidates={d.candidate_count} extracted={d.extracted!r}")
    for s in d.scored:
        c = s.candidate
        print(
            f"    {s.score:7.2f}  conflicts={s.conflicts}  listings={c.listing_count:3d}"
            f"  {c.make} {c.model} {c.badge} | {c.transmission_type}, {c.fuel_type}, {c.drive_type}"
        )


if __name__ == "__main__":
    sys.exit(main())

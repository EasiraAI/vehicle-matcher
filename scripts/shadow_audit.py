"""Shadow audit: a second opinion on HIGH-confidence matches.

The routing gate only escalates low-confidence results, so a confidently
wrong extraction never gets re-examined — the one failure mode the drift
alarms cannot see. This audit closes that blind spot by sampling: it takes
matches at or above a confidence threshold, re-extracts the text with the
LLM, re-runs the same deterministic pipeline on that extraction, and reports
every case where the two paths land on different vehicles.

A disagreement does not mean the rules were wrong — it means the case earned
a human look. The disagreement RATE is the alarm metric: tracked over time,
a rise means marketplace language is drifting away from the rule extractor.

Usage:
    python scripts/shadow_audit.py                       # data/inputs.txt
    python scripts/shadow_audit.py my.txt --min-confidence 8 --limit 50
Requires MATCHER_LLM credentials (.env); responses are cached, so re-runs
only pay for new descriptions.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vehicle_matcher.config import get_settings  # noqa: E402
from vehicle_matcher.llm_extractor import LLMExtractor  # noqa: E402
from vehicle_matcher.matcher import Matcher  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inputs",
        nargs="?",
        type=Path,
        default=Path("data/inputs.txt"),
        help="text file, one description per line",
    )
    parser.add_argument(
        "--min-confidence", type=int, default=8, help="audit matches at or above this confidence"
    )
    parser.add_argument("--limit", type=int, default=None, help="max descriptions to audit")
    args = parser.parse_args()

    settings = get_settings()
    llm = LLMExtractor(settings, cache_path=Path(".cache/llm_extractions.json"))
    lines = [ln.strip() for ln in args.inputs.read_text(encoding="utf-8").splitlines()]
    descriptions = [ln for ln in lines if ln]

    audited = 0
    disagreements: list[tuple[str, str, int, str | None, int]] = []
    llm_unavailable = 0

    with psycopg.connect(settings.dsn) as conn:
        matcher = Matcher(conn, settings=settings)  # rules only: no fallback wired
        for text in descriptions:
            rules = matcher.match(text)
            if rules.vehicle_id is None or rules.confidence < args.min_confidence:
                continue
            if args.limit is not None and audited >= args.limit:
                break

            shadow_extracted = llm(text)
            if shadow_extracted is None:
                llm_unavailable += 1
                continue
            shadow = matcher.match_extracted(shadow_extracted)
            audited += 1
            if shadow.vehicle_id != rules.vehicle_id:
                disagreements.append(
                    (text, rules.vehicle_id, rules.confidence, shadow.vehicle_id, shadow.confidence)
                )

    print(f"descriptions:        {len(descriptions)}")
    print(f"high-confidence:     {audited + llm_unavailable} (>= {args.min_confidence})")
    print(f"audited:             {audited}")
    print(f"llm unavailable:     {llm_unavailable}")
    print(f"disagreements:       {len(disagreements)}")
    if audited:
        print(f"disagreement rate:   {len(disagreements) / audited:.1%}")
    for text, rid, rconf, sid, sconf in disagreements:
        print(f"\n  {text!r}")
        print(f"    rules:  {rid}@{rconf}")
        print(f"    shadow: {sid or 'null'}@{sconf}")
    if disagreements:
        print("\nreview the cases above — disagreement flags, it does not convict.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Scale evidence for the 10k-vehicle / 100k-listing requirement.

Generates a synthetic catalogue in a SEPARATE database (vehicles_synth), runs
the real matcher over a query mix, and reports p50/p95 latency plus the EXPLAIN
plan of the candidate query. Deliberately not part of the PR test gate — this
is an evidence artifact, not a regression test.

Usage: python scripts/synth_scale.py [admin-dsn]
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
import time
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vehicle_matcher.config import Settings  # noqa: E402
from vehicle_matcher.matcher import Matcher  # noqa: E402

SYNTH_DB = "vehicles_synth"
N_VEHICLES = 10_000
N_LISTINGS = 100_000

MAKES_MODELS = {
    "Toyota": ["86", "Camry", "Kluger", "RAV4", "Supra", "Yarion", "Corvus"],
    "Volkswagen": ["Amarok", "Golf", "Tiguan", "Polaris", "Vento"],
    "Mazda": ["3", "6", "CX-3", "CX-30", "BT-50"],
    "Hyundai": ["i20", "i30", "Kona", "Tucson", "Santa Fe"],
    "Kia": ["Cerato", "Sportage", "Sorento", "Picanto"],
    "Nissan": ["Navara", "X-Trail", "Qashqai", "Patrol"],
    "Ford": ["Ranger", "Everest", "Focus", "Escape"],
    "Subaru": ["Impreza", "Forester", "Outback", "WRX"],
}
BADGE_PARTS = [
    "GX",
    "GXL",
    "GT",
    "GTS",
    "Sport",
    "Premium",
    "Highline",
    "Trendline",
    "Comfortline",
    "Core",
    "Canyon",
    "Ultimate",
    "Grande",
    "Cruiser",
    "Ascent",
    "Edge",
    "ST",
    "ST-X",
    "N-Line",
    "Black Edition",
    "110TSI",
    "132TSI",
    "162TSI",
    "TDI420",
    "TDI550",
    "TDI580",
]
TRANS = ["Automatic", "Manual"]
FUELS = ["Petrol", "Diesel", "Hybrid-Petrol"]
DRIVES = ["Front Wheel Drive", "Rear Wheel Drive", "Four Wheel Drive"]


def build_synth(admin_dsn: str) -> str:
    rng = random.Random(42)
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {SYNTH_DB}")
        admin.execute(f"CREATE DATABASE {SYNTH_DB}")
    dsn = admin_dsn.rsplit("/", 1)[0] + "/" + SYNTH_DB

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("""
            CREATE TABLE vehicle (
              id TEXT NOT NULL PRIMARY KEY, make TEXT NOT NULL, model TEXT NOT NULL,
              badge TEXT NOT NULL, transmission_type TEXT NOT NULL,
              fuel_type TEXT NOT NULL, drive_type TEXT NOT NULL)
        """)
        conn.execute("""
            CREATE TABLE listing (
              id TEXT NOT NULL PRIMARY KEY,
              vehicle_id TEXT NOT NULL REFERENCES vehicle(id),
              url TEXT NOT NULL, price INT NOT NULL, kms INT NOT NULL)
        """)
        vehicles = []
        for i in range(N_VEHICLES):
            make = rng.choice(list(MAKES_MODELS))
            model = rng.choice(MAKES_MODELS[make])
            badge = " ".join(rng.sample(BADGE_PARTS, rng.randint(1, 3)))
            vehicles.append(
                (
                    str(4_000_000_000_000_000 + i),
                    make,
                    model,
                    badge,
                    rng.choice(TRANS),
                    rng.choice(FUELS),
                    rng.choice(DRIVES),
                )
            )
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO vehicle VALUES (%s, %s, %s, %s, %s, %s, %s)", vehicles)
            listings = [
                (
                    f"L{j}",
                    vehicles[rng.randrange(N_VEHICLES)][0],
                    "https://example.test",
                    rng.randint(5_000, 90_000),
                    rng.randint(0, 250_000),
                )
                for j in range(N_LISTINGS)
            ]
            cur.executemany("INSERT INTO listing VALUES (%s, %s, %s, %s, %s)", listings)

        for path in sorted((Path(__file__).resolve().parents[1] / "migrations").glob("*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))
        conn.execute("REFRESH MATERIALIZED VIEW vehicle_listing_stats")
        conn.execute("ANALYZE vehicle")
    return dsn


def run_benchmark(dsn: str, p95_budget_ms: float | None = None) -> int:
    rng = random.Random(7)
    settings = Settings(dsn=dsn)
    with psycopg.connect(dsn) as conn:
        matcher = Matcher(conn, settings=settings)

        rows = conn.execute("SELECT make, model, badge, transmission_type FROM vehicle").fetchall()
        queries = []
        for make, model, badge, trans in rng.sample(rows, 1000):
            style = rng.random()
            if style < 0.4:
                queries.append(f"{make} {model} {badge} {trans}")
            elif style < 0.7:
                queries.append(f"{model} {badge.split()[0]}")
            elif style < 0.9:
                queries.append(f"{make.lower()} {model.lower()}")
            else:
                queries.append(f"{model[:-1]}o {badge.split()[0]}")  # misspelling-ish

        matcher.match(queries[0])  # warm
        timings = []
        matched = 0
        for q in queries:
            t0 = time.perf_counter()
            result = matcher.match(q)
            timings.append((time.perf_counter() - t0) * 1000)
            matched += result.vehicle_id is not None

        timings.sort()
        p95 = timings[int(len(timings) * 0.95)]
        print(f"\nvehicles={N_VEHICLES} listings={N_LISTINGS} queries={len(queries)}")
        print(f"matched: {matched}/{len(queries)}")
        print(
            f"p50 {statistics.median(timings):.2f} ms   p95 {p95:.2f} ms   max {timings[-1]:.2f} ms"
        )

        for label, sql, args in (
            (
                "model arm",
                "EXPLAIN (ANALYZE, BUFFERS) SELECT v.id FROM vehicle v"
                " WHERE lower(v.model) = %s OR lower(v.model) %% %s",
                ("golf", "golf"),
            ),
            (
                "token arm",
                "EXPLAIN (ANALYZE, BUFFERS) SELECT v.id FROM vehicle v WHERE %s <<%% v.search_text",
                ("highline",),
            ),
        ):
            print(f"\nEXPLAIN ({label}):")
            for row in conn.execute(sql, args).fetchall():
                print("  " + row[0])

    if p95_budget_ms is not None and p95 > p95_budget_ms:
        print(f"\nFAIL: p95 {p95:.2f} ms exceeds budget {p95_budget_ms:.0f} ms")
        return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "admin_dsn",
        nargs="?",
        default="postgresql://postgres:postgres@localhost:5433/postgres",
    )
    parser.add_argument(
        "--p95-budget-ms",
        type=float,
        default=None,
        help="exit non-zero if p95 latency exceeds this (regression gate)",
    )
    cli_args = parser.parse_args()
    print("building synthetic catalogue...")
    synth_dsn = build_synth(cli_args.admin_dsn)
    sys.exit(run_benchmark(synth_dsn, cli_args.p95_budget_ms))

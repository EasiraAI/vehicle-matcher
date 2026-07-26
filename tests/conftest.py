from __future__ import annotations

import os

import psycopg
import pytest

from vehicle_matcher.vocabulary import AliasEntry, Vocabulary

DSN = os.environ.get("MATCHER_DSN", "postgresql://postgres:postgres@localhost:5433/vehicles")


@pytest.fixture(scope="session")
def db_conn():
    """Real Postgres connection; integration/golden tests skip cleanly when the
    compose stack isn't running."""
    try:
        conn = psycopg.connect(DSN, autocommit=True)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not available at {DSN}: {exc}")
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def vocab() -> Vocabulary:
    """A DB-free vocabulary mirroring the seeded aliases and catalogue shape,
    so unit tests run in milliseconds with no services."""
    aliases = {
        "vw": AliasEntry("make", "Volkswagen"),
        "volkswagon": AliasEntry("make", "Volkswagen"),
        "ford": AliasEntry("make", "Ford"),
        "mazda": AliasEntry("make", "Mazda"),
        "ranger": AliasEntry("model", "Ranger"),
        "corolla": AliasEntry("model", "Corolla"),
        "rav 4": AliasEntry("model", "RAV4"),
        "auto": AliasEntry("transmission", "Automatic"),
        "automatic": AliasEntry("transmission", "Automatic"),
        "manual": AliasEntry("transmission", "Manual"),
        "man": AliasEntry("transmission", "Manual", weak=True),
        "petrol": AliasEntry("fuel", "Petrol"),
        "diesel": AliasEntry("fuel", "Diesel"),
        "hybrid": AliasEntry("fuel", "Hybrid-Petrol"),
        "4x4": AliasEntry("drive", "Four Wheel Drive"),
        "4wd": AliasEntry("drive", "Four Wheel Drive"),
        "awd": AliasEntry("drive", "Four Wheel Drive"),
        "rwd": AliasEntry("drive", "Rear Wheel Drive"),
        "fwd": AliasEntry("drive", "Front Wheel Drive"),
        "front wheel drive": AliasEntry("drive", "Front Wheel Drive"),
        "rear wheel drive": AliasEntry("drive", "Rear Wheel Drive"),
        "four wheel drive": AliasEntry("drive", "Four Wheel Drive"),
        "h/line": AliasEntry("badge", "highline"),
        "hline": AliasEntry("badge", "highline"),
        "e/d": AliasEntry("badge", "edition"),
        "sports": AliasEntry("badge", "sport"),
        "r line": AliasEntry("badge", "r-line"),
    }
    return Vocabulary(
        aliases=aliases,
        catalogue_makes=frozenset({"Toyota", "Volkswagen"}),
        catalogue_models=frozenset({"86", "Camry", "Kluger", "RAV4", "Amarok", "Golf", "Tiguan"}),
        badge_tokens=frozenset(
            """gt gts apollo blue ascent sport sl sx black edition gx gxl grande cruiser
            edge core plus canyon highline sportline ultimate comfortline trendline
            alltrack premium gti r allspace r-line 110tsi 132tsi 162tsi tdi400 tdi420
            tdi500 tdi550 tdi580""".split()
        ),
        max_alias_words=3,
    )

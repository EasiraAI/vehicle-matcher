"""Load the challenge data and apply search/vocabulary migrations. Idempotent.

The vendor file data/data.sql is applied verbatim except for one repair: it
creates listing with primary key column "it" but the INSERT that follows
targets "id", so the raw script cannot run. Renaming the column between the
CREATE and the INSERT lets the vendor file execute unmodified (we never edit
data.sql itself).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
DATA_SQL = ROOT / "data" / "data.sql"
MIGRATIONS = ROOT / "migrations"

EXPECTED_VEHICLES = 59
EXPECTED_LISTINGS = 1000


def split_statements(sql: str) -> list[str]:
    # data.sql is two CREATE TABLEs and two INSERTs with no semicolons inside
    # string literals, so a statement-boundary split is safe here. This is not
    # a general SQL parser and doesn't try to be.
    statements = [s.strip() for s in re.split(r";\s*\n", sql) if s.strip()]
    if len(statements) != 4:
        raise SystemExit(
            f"data.sql: expected 4 statements (2 CREATE, 2 INSERT), got {len(statements)}"
        )
    return statements


def table_exists(conn: psycopg.Connection, name: str) -> bool:
    row = conn.execute("SELECT to_regclass(%s)", (name,)).fetchone()
    return row is not None and row[0] is not None


def load_data(conn: psycopg.Connection) -> None:
    if table_exists(conn, "vehicle"):
        print("data already loaded, skipping")
        return
    create_vehicle, create_listing, insert_vehicle, insert_listing = split_statements(
        DATA_SQL.read_text(encoding="utf-8")
    )
    conn.execute(create_vehicle)
    conn.execute(create_listing)
    # The repair described in the module docstring.
    conn.execute("ALTER TABLE listing RENAME COLUMN it TO id")
    conn.execute(insert_vehicle)
    conn.execute(insert_listing)


def verify_counts(conn: psycopg.Connection) -> None:
    for table, expected in (("vehicle", EXPECTED_VEHICLES), ("listing", EXPECTED_LISTINGS)):
        row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
        count = row[0] if row else 0
        if count != expected:
            raise SystemExit(f"{table}: expected {expected} rows, found {count}")
        print(f"{table}: {count} rows ok")


def apply_migrations(conn: psycopg.Connection) -> None:
    for path in sorted(MIGRATIONS.glob("*.sql")):
        print(f"applying {path.name}")
        conn.execute(path.read_text(encoding="utf-8"))


def main(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        load_data(conn)
        verify_counts(conn)
        apply_migrations(conn)
        conn.execute("REFRESH MATERIALIZED VIEW vehicle_listing_stats")
    print("done")


if __name__ == "__main__":
    import os

    default_dsn = os.environ.get(
        "MATCHER_DSN", "postgresql://postgres:postgres@localhost:5433/vehicles"
    )
    main(sys.argv[1] if len(sys.argv) > 1 else default_dsn)

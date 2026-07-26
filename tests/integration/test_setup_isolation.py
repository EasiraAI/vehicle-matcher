"""Destructive loader tests against a scratch database (created and dropped
per module), so nothing here can corrupt the shared dev database. Covers the
paths the read-only integration tests can't: the abort-on-bad-counts guard
and materialized-view refresh."""

import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.integration

DSN = os.environ.get("MATCHER_DSN", "postgresql://postgres:postgres@localhost:5433/vehicles")
SCRATCH = "vehicles_test_scratch"
SETUP = Path(__file__).parents[2] / "scripts" / "setup_db.py"


@pytest.fixture(scope="module")
def scratch_dsn(db_conn):
    admin_dsn = DSN.rsplit("/", 1)[0] + "/postgres"
    try:
        admin = psycopg.connect(admin_dsn, autocommit=True)
    except psycopg.OperationalError as exc:
        pytest.skip(f"admin database not reachable: {exc}")
    admin.execute(f"DROP DATABASE IF EXISTS {SCRATCH}")
    admin.execute(f"CREATE DATABASE {SCRATCH}")
    yield DSN.rsplit("/", 1)[0] + f"/{SCRATCH}"
    admin.execute(f"DROP DATABASE IF EXISTS {SCRATCH} WITH (FORCE)")
    admin.close()


def run_setup(dsn: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SETUP), dsn], capture_output=True, text=True, timeout=120
    )


def test_fresh_load_succeeds_and_is_idempotent(scratch_dsn):
    first = run_setup(scratch_dsn)
    assert first.returncode == 0, first.stderr
    assert "vehicle: 59 rows ok" in first.stdout

    second = run_setup(scratch_dsn)
    assert second.returncode == 0, second.stderr
    assert "already loaded" in second.stdout


def test_loader_aborts_loudly_on_row_count_mismatch(scratch_dsn):
    with psycopg.connect(scratch_dsn, autocommit=True) as conn:
        conn.execute("DELETE FROM listing WHERE vehicle_id = (SELECT id FROM vehicle LIMIT 1)")
    result = run_setup(scratch_dsn)
    assert result.returncode != 0
    assert "expected 1000 rows" in (result.stdout + result.stderr)


def test_mv_refresh_reflects_new_listings(scratch_dsn):
    # Recover the scratch DB to a clean state first.
    with psycopg.connect(scratch_dsn, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS listing, vehicle CASCADE")
        conn.execute("DROP MATERIALIZED VIEW IF EXISTS vehicle_listing_stats")
    assert run_setup(scratch_dsn).returncode == 0

    with psycopg.connect(scratch_dsn, autocommit=True) as conn:
        vehicle_id = conn.execute("SELECT id FROM vehicle LIMIT 1").fetchone()[0]
        before = conn.execute(
            "SELECT listing_count FROM vehicle_listing_stats WHERE vehicle_id = %s",
            (vehicle_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO listing (id, vehicle_id, url, price, kms)"
            " VALUES ('test-listing', %s, 'https://example.test', 10000, 50000)",
            (vehicle_id,),
        )
        # Stale until refreshed — by design (popularity is a prior).
        stale = conn.execute(
            "SELECT listing_count FROM vehicle_listing_stats WHERE vehicle_id = %s",
            (vehicle_id,),
        ).fetchone()[0]
        assert stale == before
        conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY vehicle_listing_stats")
        after = conn.execute(
            "SELECT listing_count FROM vehicle_listing_stats WHERE vehicle_id = %s",
            (vehicle_id,),
        ).fetchone()[0]
        assert after == before + 1

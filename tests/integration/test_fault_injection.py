"""Failure-mode contracts.

An unreachable database must RAISE, never return a match result: a null
answer means "this vehicle is not in the catalogue", and an outage must never
be allowed to impersonate that. Concurrency: one Matcher (one psycopg
connection, which serialises access) shared across threads must return the
same answers as the single-threaded baseline.
"""

import os
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from vehicle_matcher.config import get_settings
from vehicle_matcher.matcher import Matcher

pytestmark = pytest.mark.integration

DSN = os.environ.get("MATCHER_DSN", "postgresql://postgres:postgres@localhost:5433/vehicles")


def test_dead_connection_raises_instead_of_returning_a_result():
    conn = psycopg.connect(DSN)
    matcher = Matcher(conn, settings=get_settings())
    conn.close()
    with pytest.raises(psycopg.Error):
        matcher.match("Golf GTI")


def test_failure_mid_session_raises_not_null(db_conn):
    # A fresh connection whose session dies after warm-up: the vocabulary is
    # already cached, so the failure surfaces at retrieval time.
    with psycopg.connect(DSN) as conn:
        matcher = Matcher(conn, settings=get_settings())
        assert matcher.match("Golf GTI").vehicle_id is not None  # warm
        conn.close()
        with pytest.raises(psycopg.Error):
            matcher.match("Golf GTI")


QUERIES = [
    "Golf GTI",
    "VW Amarok Ultimate",
    "Toyota Camry Hybrid",
    "Amrok h/line 4x4",
    "Ford Ranger XLT Dual Cab",
    "Golf cart",
]


def test_shared_matcher_is_thread_consistent(db_conn):
    matcher = Matcher(db_conn, settings=get_settings())
    baseline = {q: (r.vehicle_id, r.confidence) for q in QUERIES for r in [matcher.match(q)]}

    def run(q: str):
        r = matcher.match(q)
        return q, (r.vehicle_id, r.confidence)

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(run, QUERIES * 10))

    assert all(baseline[q] == outcome for q, outcome in outcomes)

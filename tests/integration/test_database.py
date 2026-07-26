import pytest

pytestmark = pytest.mark.integration


def test_row_counts(db_conn):
    assert db_conn.execute("SELECT count(*) FROM vehicle").fetchone()[0] == 59
    assert db_conn.execute("SELECT count(*) FROM listing").fetchone()[0] == 1000


def test_listing_pk_repaired(db_conn):
    cols = [
        r[0]
        for r in db_conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'listing'"
        )
    ]
    assert "id" in cols and "it" not in cols


def test_search_infrastructure_exists(db_conn):
    indexes = [
        r[0]
        for r in db_conn.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'vehicle'")
    ]
    assert "idx_vehicle_search_trgm" in indexes
    assert "idx_vehicle_model_trgm" in indexes
    mv_rows = db_conn.execute("SELECT count(*) FROM vehicle_listing_stats").fetchone()[0]
    assert mv_rows == 59
    total = db_conn.execute("SELECT sum(listing_count) FROM vehicle_listing_stats").fetchone()[0]
    assert total == 1000


def test_alias_seed_loaded(db_conn):
    count = db_conn.execute("SELECT count(*) FROM alias").fetchone()[0]
    assert count >= 50

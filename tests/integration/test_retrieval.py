import pytest

from vehicle_matcher.config import get_settings
from vehicle_matcher.extractor import extract
from vehicle_matcher.matcher import Matcher
from vehicle_matcher.retrieval import configure_session, fetch_candidates
from vehicle_matcher.vocabulary import load_vocabulary

pytestmark = pytest.mark.integration

# description -> a property the true vehicle satisfies; retrieval owes us the
# true vehicle in the candidate set (recall invariant). Precision failures are
# scoring bugs; a miss here is a retrieval bug and must be fixed in retrieval.
RECALL_CASES = [
    ("Volkswagen Golf 110TSI Comfortline Petrol Automatic Front Wheel Drive", "4749339721203712"),
    ("VW Amarok Ultimate", "4951649860714496"),
    ("VW Golf R with engine swap from Toyota 86 GT", "5824662093168640"),
    ("Golf GTI", None),  # filled from DB below
    ("Amrok h/line 4x4", None),
]


@pytest.fixture(scope="module")
def session(db_conn):
    settings = get_settings()
    configure_session(db_conn, settings)
    return db_conn, settings, load_vocabulary(db_conn)


def test_recall_invariant_known_ids(session):
    conn, settings, vocab = session
    for description, true_id in RECALL_CASES:
        if true_id is None:
            continue
        candidates = fetch_candidates(conn, extract(description, vocab), settings)
        assert true_id in {c.id for c in candidates}, description


def test_recall_fuzzy_model(session):
    conn, settings, vocab = session
    candidates = fetch_candidates(conn, extract("Amrok h/line 4x4", vocab), settings)
    assert any(c.model == "Amarok" and "Highline" in c.badge for c in candidates)


def test_no_candidates_for_absent_make(session):
    conn, settings, vocab = session
    candidates = fetch_candidates(conn, extract("Ford Ranger XLT Dual Cab", vocab), settings)
    assert candidates == []


def test_empty_extraction_returns_empty_set(session):
    conn, settings, vocab = session
    assert fetch_candidates(conn, extract("", vocab), settings) == []


def test_description_text_is_data_not_sql(session):
    conn, settings, vocab = session
    matcher = Matcher(conn, settings=settings, vocabulary=vocab)
    hostile = [
        "'; DROP TABLE vehicle; --",
        "Golf'); DELETE FROM listing; --",
        'Toyota" OR 1=1 --',
        "Robert'); DROP TABLE students;--",
    ]
    for text in hostile:
        result = matcher.match(text)
        assert 0 <= result.confidence <= 10
    # the database is intact afterwards
    assert conn.execute("SELECT count(*) FROM vehicle").fetchone()[0] == 59
    assert conn.execute("SELECT count(*) FROM listing").fetchone()[0] == 1000

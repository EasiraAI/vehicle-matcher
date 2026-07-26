"""Accuracy as a regression gate: the scorecard over the labeled set must not
silently degrade, and confidence must remain informative (higher-confidence
buckets can never be LESS accurate than lower ones)."""

from pathlib import Path

import pytest

from vehicle_matcher.config import get_settings
from vehicle_matcher.evaluation import evaluate, load_cases
from vehicle_matcher.matcher import Matcher

pytestmark = pytest.mark.integration

LABELS = Path(__file__).parents[1] / "fixtures" / "eval_labels.csv"


@pytest.fixture(scope="module")
def report(db_conn):
    cases = load_cases(LABELS)
    assert len(cases) == 21
    return evaluate(Matcher(db_conn, settings=get_settings()), cases)


def test_accuracy_floor(report):
    assert report.accuracy >= 0.90, report.failures


def test_absence_detection_is_reliable(report):
    # Wrong IDs poison downstream consumers; absent vehicles must be caught.
    assert report.null_precision == 1.0
    assert report.null_recall == 1.0


def test_true_vehicle_ranks_near_the_top(report):
    assert report.mrr >= 0.90


def test_calibration_is_monotone(report):
    # With a small labeled set we use three coarse buckets and require weak
    # monotonicity over occupied ones: confidence 8 claiming more certainty
    # than confidence 4 must never come with LOWER accuracy.
    occupied = [row for row in report.reliability if row.n >= 3]
    accuracies = [row.accuracy for row in occupied]
    assert accuracies == sorted(accuracies), report.reliability


def test_high_confidence_bucket_is_trustworthy(report):
    high = report.reliability[-1]
    assert high.n > 0
    assert high.accuracy == 1.0, report.failures

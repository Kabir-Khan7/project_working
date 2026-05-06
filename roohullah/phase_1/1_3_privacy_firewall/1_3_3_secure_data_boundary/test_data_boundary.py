"""
Tests for 1.3.3 Secure Data Boundary
---------------------------------------
Run: python -m pytest test_data_boundary.py -v
"""

import pandas as pd
import pytest
from data_boundary import DataBoundary, BoundaryViolation, ClassificationReport


@pytest.fixture
def boundary():
    return DataBoundary()


# ── Classification ────────────────────────────────────────────────────────────
def test_aggregates_are_safe(boundary):
    payload = {"totals": {}, "averages": {}, "transaction_count": 5}
    report = boundary.classify(payload)
    assert report.is_safe is True
    assert len(report.blocked) == 0


def test_raw_description_is_blocked(boundary):
    payload = {"description": "Payment to Ali Khan"}
    report = boundary.classify(payload)
    assert report.is_safe is False
    assert "description" in report.blocked


def test_party_name_is_blocked(boundary):
    payload = {"party_name": "Ahmed Enterprises"}
    report = boundary.classify(payload)
    assert "party_name" in report.blocked


def test_reference_is_blocked(boundary):
    payload = {"reference": "INV-2026-001"}
    report = boundary.classify(payload)
    assert "reference" in report.blocked


def test_mixed_payload(boundary):
    payload = {
        "totals": {"income": 100000},
        "description": "Raw transaction text",
        "transaction_count": 5,
    }
    report = boundary.classify(payload)
    assert report.is_safe is False
    assert "description" in report.blocked
    assert "totals" in report.allowed


# ── Validation (strict mode) ─────────────────────────────────────────────────
def test_validate_safe_payload(boundary):
    safe = {"totals": {}, "averages": {}}
    boundary.validate_for_cloud(safe)  # should not raise


def test_validate_blocks_raw_data(boundary):
    unsafe = {"description": "Payment details", "amount": 5000}
    with pytest.raises(BoundaryViolation) as exc_info:
        boundary.validate_for_cloud(unsafe)
    assert "description" in exc_info.value.blocked_fields


# ── Filtering ─────────────────────────────────────────────────────────────────
def test_filter_removes_raw_fields(boundary):
    payload = {
        "totals": {"income": 100000},
        "description": "Raw data — should be stripped",
        "party_name": "Ali Khan",
        "transaction_count": 5,
    }
    safe = boundary.filter_for_cloud(payload)
    assert "totals" in safe
    assert "transaction_count" in safe
    assert "description" not in safe
    assert "party_name" not in safe


def test_filter_keeps_all_safe_fields(boundary):
    payload = {"totals": {}, "averages": {}, "trends": []}
    safe = boundary.filter_for_cloud(payload)
    assert safe == payload  # nothing stripped


# ── DataFrame classification ─────────────────────────────────────────────────
def test_classify_dataframe_columns(boundary):
    df = pd.DataFrame({
        "txn_date": ["2026-01-01"],
        "description": ["Rent"],
        "party_name": ["Landlord"],
        "amount": [50000],
    })
    report = boundary.classify_dataframe(df)
    assert "description" in report.blocked
    assert "party_name" in report.blocked


# ── Report summary ───────────────────────────────────────────────────────────
def test_safe_report_summary(boundary):
    payload = {"totals": {}}
    report = boundary.classify(payload)
    assert "SAFE" in report.summary()


def test_blocked_report_summary(boundary):
    payload = {"description": "Raw"}
    report = boundary.classify(payload)
    assert "BLOCKED" in report.summary()


# ── Security: unknown fields default to blocked ──────────────────────────────
def test_unknown_fields_listed(boundary):
    payload = {"some_random_field": "value"}
    report = boundary.classify(payload)
    assert "some_random_field" in report.unknown

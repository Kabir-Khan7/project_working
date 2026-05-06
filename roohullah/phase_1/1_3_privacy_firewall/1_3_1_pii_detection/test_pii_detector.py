"""
test_pii_detector.py
--------------------
Unit tests for M13 — Privacy Firewall (pii_detector.py).

These tests run WITHOUT a database — they test the detector logic in isolation.
This is called "unit testing" — test one piece of code at a time,
completely separate from everything else.

Why unit tests?
  - Fast: no Docker, no DB, runs in milliseconds
  - Precise: if a test fails, you know EXACTLY which pattern broke
  - Safe: you can change the regex patterns and instantly see if anything broke
"""

import pandas as pd
import pytest

from app.services.pii_detector import (
    mask_row,
    scan_dataframe,
    scan_row,
)


# ── CNIC Tests ────────────────────────────────────────────────────────────────

def test_cnic_detected_in_description():
    """Pakistani CNIC format: 42101-1234567-9"""
    result = scan_row({"description": "Payment from 42101-1234567-9 received"})
    assert result.has_pii is True
    assert any(m.pii_type == "CNIC" for m in result.matches)


def test_cnic_not_false_positive():
    """Random numbers should NOT trigger CNIC detection."""
    result = scan_row({"description": "Invoice 12345 for office supplies"})
    pii_types = [m.pii_type for m in result.matches]
    assert "CNIC" not in pii_types


# ── Phone Tests ───────────────────────────────────────────────────────────────

def test_phone_standard_format():
    result = scan_row({"description": "Call 0300-1234567 for delivery"})
    assert result.has_pii is True
    assert any(m.pii_type == "PHONE" for m in result.matches)


def test_phone_with_country_code():
    result = scan_row({"party_name": "+923001234567"})
    assert result.has_pii is True
    assert any(m.pii_type == "PHONE" for m in result.matches)


def test_phone_no_space_format():
    result = scan_row({"description": "Contact: 03451234567"})
    assert result.has_pii is True
    assert any(m.pii_type == "PHONE" for m in result.matches)


# ── Email Tests ───────────────────────────────────────────────────────────────

def test_email_detected():
    result = scan_row({"description": "Receipt sent to ahmed@company.pk"})
    assert result.has_pii is True
    assert any(m.pii_type == "EMAIL" for m in result.matches)


def test_email_in_party_name():
    result = scan_row({"party_name": "vendor@gmail.com"})
    assert result.has_pii is True


# ── IBAN Tests ────────────────────────────────────────────────────────────────

def test_iban_detected():
    result = scan_row({"reference": "Transfer to PK36SCBL0000001123456702"})
    assert result.has_pii is True
    assert any(m.pii_type == "IBAN" for m in result.matches)


# ── Address Tests ─────────────────────────────────────────────────────────────

def test_address_keyword_house():
    result = scan_row({"description": "Delivery to House #5 Model Town"})
    assert result.has_pii is True
    assert any(m.pii_type == "ADDRESS" for m in result.matches)


def test_address_keyword_block():
    result = scan_row({"description": "Street 3, Block B, Phase 2 DHA"})
    assert result.has_pii is True


# ── Clean Data (No PII) ───────────────────────────────────────────────────────

def test_clean_row_no_pii():
    """Normal financial transaction should have no PII."""
    result = scan_row({
        "description": "Office Rent January 2026",
        "party_name":  "Malik Properties",
        "reference":   "JAN-2026-RENT",
    })
    assert result.has_pii is False
    assert result.matches == []
    assert result.flagged_fields == []


def test_none_values_handled():
    """Rows with None fields should not crash."""
    result = scan_row({"description": None, "party_name": None})
    assert result.has_pii is False


def test_empty_dict_handled():
    result = scan_row({})
    assert result.has_pii is False


# ── Masking Tests ─────────────────────────────────────────────────────────────

def test_mask_row_replaces_phone():
    row = {"description": "Paid 0300-1234567 for goods", "party_name": "Ali"}
    scan = scan_row(row)
    masked = mask_row(row, scan)

    # Phone should be gone from masked version
    assert "0300-1234567" not in masked["description"]
    # Token should be present
    assert "[PHONE_" in masked["description"]
    # Original should be unchanged
    assert "0300-1234567" in row["description"]


def test_mask_row_does_not_modify_original():
    """mask_row must never change the original dict (immutable)."""
    row = {"description": "CNIC: 42101-1234567-9"}
    scan = scan_row(row)
    original_desc = row["description"]
    mask_row(row, scan)
    assert row["description"] == original_desc  # unchanged!


def test_mask_row_cleans_row_no_pii():
    """Masking a row with no PII should return it unchanged."""
    row = {"description": "Monthly salary credit", "party_name": "Ahmed"}
    scan = scan_row(row)
    masked = mask_row(row, scan)
    assert masked == row


# ── Multiple PII types in one row ─────────────────────────────────────────────

def test_multiple_pii_types_in_one_row():
    row = {
        "description": "Payment from 42101-1234567-9 via 0300-9876543",
        "party_name": "sender@example.com",
    }
    scan = scan_row(row)
    assert scan.has_pii is True

    pii_types = {m.pii_type for m in scan.matches}
    assert "CNIC" in pii_types
    assert "PHONE" in pii_types
    assert "EMAIL" in pii_types
    assert len(scan.flagged_fields) >= 2


# ── Summary field ─────────────────────────────────────────────────────────────

def test_scan_result_summary_structure():
    row = {"description": "Contact 0300-1234567 for refund"}
    scan = scan_row(row)
    summary = scan.summary()

    assert isinstance(summary, dict)
    assert "has_pii" in summary
    assert "flagged_fields" in summary
    assert "pii_types_found" in summary
    assert "total_redactions" in summary
    assert summary["has_pii"] is True
    assert summary["total_redactions"] >= 1


# ── DataFrame scan ────────────────────────────────────────────────────────────

def test_scan_dataframe_summary():
    df = pd.DataFrame({
        "description": [
            "Office rent Jan 2026",          # clean
            "Call 0300-1234567 for delivery", # phone
            "CNIC 42101-1234567-9 verified",  # CNIC
        ],
        "party_name": ["Landlord", "Courier", "Customer"],
        "reference":  [None, None, None],
    })

    summary = scan_dataframe(df)

    assert summary["total_rows_scanned"] == 3
    assert summary["rows_with_pii"] == 2
    assert summary["pii_percentage"] == pytest.approx(66.7, abs=0.1)
    assert "PHONE" in summary["pii_types_detected"]
    assert "CNIC" in summary["pii_types_detected"]
    assert "description" in summary["flagged_columns"]


def test_scan_dataframe_all_clean():
    df = pd.DataFrame({
        "description": ["Salary", "Rent", "Utilities"],
        "party_name":  ["Self", "Landlord", "WAPDA"],
        "reference":   [None, None, None],
    })
    summary = scan_dataframe(df)
    assert summary["rows_with_pii"] == 0
    assert summary["pii_percentage"] == 0.0
    assert summary["pii_types_detected"] == []

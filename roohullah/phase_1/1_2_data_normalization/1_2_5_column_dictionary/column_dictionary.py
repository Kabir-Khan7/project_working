"""
1.2.5 — Column Dictionary & Fuzzy Mapper (Standalone Module)
--------------------------------------------------------------
Comprehensive column name knowledge base for Pakistani accounting software.

Covers:
    - 100+ column name variations across all software
    - Urdu script (Unicode): تاریخ، رقم، تفصیل
    - Roman Urdu: Taareekh, Raqam, Tafseelat
    - Software-specific: Tally, QuickBooks, LedgerMax, Xero, Banks
    - Abbreviations: Dr, Cr, Dt, Amt, Ref
    - Fuzzy matching: N-gram similarity for unknown columns

Dependencies:
    None (pure Python)

Usage:
    from column_dictionary import ColumnMapper

    mapper = ColumnMapper()

    # Direct lookup
    result = mapper.lookup("Taareekh")
    # ("transaction_date", 0.90)

    # Fuzzy match
    result = mapper.fuzzy_match("Transacton Date")
    # ("transaction_date", 0.82)

    # Software-specific
    result = mapper.lookup("Vch Type", software="tally")
    # ("voucher_type", 0.95)
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional


# ── Neural Ledger Standard Schema ─────────��──────────────────────────────────
# These are the canonical field names that Silver layer uses.

STANDARD_FIELDS = frozenset({
    "transaction_date",
    "description",
    "vendor",
    "amount",
    "amount_debit",
    "amount_credit",
    "net_amount",
    "currency",
    "reference",
    "voucher_type",
    "voucher_number",
    "category",
    "account_code",
    "account_name",
    "balance",
})


# ── Software-Specific Mappings (Confidence: 0.95) ───────────────────────────

SOFTWARE_MAPPINGS: dict[str, dict[str, str]] = {
    "tally": {
        "date": "transaction_date",
        "particulars": "description",
        "vch type": "voucher_type",
        "vch no.": "voucher_number",
        "vch no": "voucher_number",
        "debit": "amount_debit",
        "credit": "amount_credit",
        "ledger name": "account_name",
    },
    "quickbooks_desktop": {
        "date": "transaction_date",
        "txn date": "transaction_date",
        "name": "vendor",
        "memo": "description",
        "memo/description": "description",
        "num": "reference",
        "type": "voucher_type",
        "amount": "net_amount",
        "debit": "amount_debit",
        "credit": "amount_credit",
        "account": "account_name",
        "class": "category",
    },
    "quickbooks_online": {
        "date": "transaction_date",
        "transaction date": "transaction_date",
        "payee": "vendor",
        "description": "description",
        "ref no.": "reference",
        "transaction type": "voucher_type",
        "amount": "net_amount",
        "debit (pkr)": "amount_debit",
        "credit (pkr)": "amount_credit",
        "account": "account_name",
        "category": "category",
    },
    "ledgermax": {
        "transaction date": "transaction_date",
        "date": "transaction_date",
        "description": "description",
        "party name": "vendor",
        "reference": "reference",
        "dr amount": "amount_debit",
        "cr amount": "amount_credit",
        "net amount": "net_amount",
        "account": "account_name",
    },
    "xero": {
        "date": "transaction_date",
        "description": "description",
        "reference": "reference",
        "contact": "vendor",
        "debit": "amount_debit",
        "credit": "amount_credit",
        "account": "account_name",
        "tax rate": "category",
    },
    "bank_pdf_hbl": {
        "date": "transaction_date",
        "value date": "transaction_date",
        "description": "description",
        "narration": "description",
        "debit": "amount_debit",
        "credit": "amount_credit",
        "balance": "balance",
        "dr": "amount_debit",
        "cr": "amount_credit",
    },
    "bank_pdf_ubl": {
        "posting date": "transaction_date",
        "description": "description",
        "debit": "amount_debit",
        "credit": "amount_credit",
        "running balance": "balance",
    },
    "bank_pdf_meezan": {
        "date": "transaction_date",
        "description": "description",
        "withdrawal": "amount_debit",
        "deposit": "amount_credit",
        "balance": "balance",
    },
}

# ── Urdu Script Mappings (Confidence: 0.90) ──────────────────────────────────

URDU_MAPPINGS: dict[str, str] = {
    # Unicode Urdu
    "تاریخ": "transaction_date",
    "رقم": "net_amount",
    "تفصیل": "description",
    "بیان": "description",
    "نام": "vendor",
    "فروش": "vendor",
    "خریدار": "vendor",
    "حوالہ": "reference",
    "نمبر": "reference",
    "آمد": "amount_credit",
    "خرچ": "amount_debit",
    "جمع": "amount_credit",
    "نکاسی": "amount_debit",
    "بقایا": "balance",
    "قسم": "voucher_type",
    "زمرہ": "category",
    "کھاتہ": "account_name",
}

# ── Roman Urdu Mappings (Confidence: 0.85) ──────��────────────────────────────

ROMAN_URDU_MAPPINGS: dict[str, str] = {
    "taareekh": "transaction_date",
    "tareekh": "transaction_date",
    "tarikh": "transaction_date",
    "raqam": "net_amount",
    "raqm": "net_amount",
    "tafseelat": "description",
    "tafsilat": "description",
    "bayaan": "description",
    "bayan": "description",
    "naam": "vendor",
    "hawala": "reference",
    "number": "reference",
    "aamad": "amount_credit",
    "kharcha": "amount_debit",
    "kharch": "amount_debit",
    "jama": "amount_credit",
    "nikaasi": "amount_debit",
    "baqaya": "balance",
    "qisam": "voucher_type",
    "zamra": "category",
    "khaata": "account_name",
}

# ── General Mappings (Confidence: 0.80) ────���─────────────────────────────────

GENERAL_MAPPINGS: dict[str, str] = {
    # Date variants
    "date": "transaction_date",
    "txn_date": "transaction_date",
    "txn date": "transaction_date",
    "transaction_date": "transaction_date",
    "transaction date": "transaction_date",
    "posting_date": "transaction_date",
    "posting date": "transaction_date",
    "post_date": "transaction_date",
    "value_date": "transaction_date",
    "value date": "transaction_date",
    "trans_date": "transaction_date",
    "trans date": "transaction_date",
    "dated": "transaction_date",
    "dt": "transaction_date",

    # Description variants
    "description": "description",
    "desc": "description",
    "narration": "description",
    "memo": "description",
    "details": "description",
    "particulars": "description",
    "remarks": "description",
    "note": "description",
    "notes": "description",
    "transaction_details": "description",
    "transaction details": "description",

    # Vendor / Party variants
    "vendor": "vendor",
    "party": "vendor",
    "party_name": "vendor",
    "party name": "vendor",
    "customer": "vendor",
    "payee": "vendor",
    "payer": "vendor",
    "name": "vendor",
    "supplier": "vendor",
    "client": "vendor",
    "beneficiary": "vendor",
    "contact": "vendor",

    # Amount variants
    "amount": "net_amount",
    "amt": "net_amount",
    "total": "net_amount",
    "value": "net_amount",
    "transaction_amount": "net_amount",
    "transaction amount": "net_amount",
    "net_amount": "net_amount",
    "net amount": "net_amount",
    "net": "net_amount",

    # Debit variants
    "debit": "amount_debit",
    "dr": "amount_debit",
    "dr.": "amount_debit",
    "dr_amount": "amount_debit",
    "dr amount": "amount_debit",
    "debit amount": "amount_debit",
    "debit_amount": "amount_debit",
    "withdrawal": "amount_debit",
    "out": "amount_debit",
    "paid": "amount_debit",
    "payment": "amount_debit",
    "expense": "amount_debit",

    # Credit variants
    "credit": "amount_credit",
    "cr": "amount_credit",
    "cr.": "amount_credit",
    "cr_amount": "amount_credit",
    "cr amount": "amount_credit",
    "credit amount": "amount_credit",
    "credit_amount": "amount_credit",
    "deposit": "amount_credit",
    "in": "amount_credit",
    "received": "amount_credit",
    "receipt": "amount_credit",
    "income": "amount_credit",

    # Reference variants
    "reference": "reference",
    "ref": "reference",
    "ref_no": "reference",
    "ref no": "reference",
    "ref no.": "reference",
    "voucher": "voucher_number",
    "voucher_no": "voucher_number",
    "voucher no": "voucher_number",
    "voucher no.": "voucher_number",
    "invoice": "reference",
    "invoice_no": "reference",
    "invoice no": "reference",
    "bill_no": "reference",
    "bill no": "reference",
    "doc_no": "reference",
    "check_no": "reference",
    "cheque_no": "reference",
    "cheque no": "reference",
    "chq no": "reference",

    # Type variants
    "type": "voucher_type",
    "txn_type": "voucher_type",
    "transaction_type": "voucher_type",
    "transaction type": "voucher_type",
    "vch type": "voucher_type",
    "voucher type": "voucher_type",

    # Account variants
    "account": "account_name",
    "account_name": "account_name",
    "account name": "account_name",
    "account_code": "account_code",
    "account code": "account_code",
    "ledger": "account_name",
    "ledger_name": "account_name",
    "ledger name": "account_name",
    "gl_code": "account_code",

    # Category variants
    "category": "category",
    "class": "category",
    "head": "category",
    "expense_head": "category",
    "expense head": "category",

    # Currency variants
    "currency": "currency",
    "ccy": "currency",
    "curr": "currency",

    # Balance
    "balance": "balance",
    "running_balance": "balance",
    "running balance": "balance",
    "closing_balance": "balance",
    "closing balance": "balance",
}


# ── Mapper Result ─────��──────────────────────────────────────────────────────

@dataclass
class MappingResult:
    """Result of a column name lookup."""
    original: str
    mapped_to: Optional[str]
    confidence: float
    source: str  # "software", "urdu", "roman_urdu", "general", "fuzzy", "none"


# ── Column Mapper ────────────────────────────────────────────────────────────

class ColumnMapper:
    """
    Maps column names to Neural Ledger standard schema.

    Strategy (in priority order):
        1. Software-specific exact match (confidence 0.95)
        2. Urdu script exact match (confidence 0.90)
        3. Roman Urdu exact match (confidence 0.85)
        4. General exact match (confidence 0.80)
        5. Normalized match (strip spaces/punctuation) (confidence 0.75)
        6. Fuzzy N-gram match (confidence proportional to similarity)
    """

    def lookup(
        self,
        column_name: str,
        software: Optional[str] = None,
    ) -> MappingResult:
        """
        Look up a column name and return the best mapping.

        Args:
            column_name: Original column name from the file
            software:    Source software (e.g., "tally", "quickbooks_desktop")

        Returns:
            MappingResult with mapped_to field and confidence
        """
        original = column_name
        lower = column_name.lower().strip()

        # Layer 1: Software-specific match
        if software and software in SOFTWARE_MAPPINGS:
            sw_map = SOFTWARE_MAPPINGS[software]
            if lower in sw_map:
                return MappingResult(original, sw_map[lower], 0.95, "software")

        # Layer 2: Urdu script match
        stripped = column_name.strip()
        if stripped in URDU_MAPPINGS:
            return MappingResult(original, URDU_MAPPINGS[stripped], 0.90, "urdu")

        # Layer 3: Roman Urdu match
        if lower in ROMAN_URDU_MAPPINGS:
            return MappingResult(original, ROMAN_URDU_MAPPINGS[lower], 0.85, "roman_urdu")

        # Layer 4: General match
        if lower in GENERAL_MAPPINGS:
            return MappingResult(original, GENERAL_MAPPINGS[lower], 0.80, "general")

        # Layer 5: Normalized match (strip all non-alphanumeric)
        normalized = self._normalize(lower)
        for key, target in GENERAL_MAPPINGS.items():
            if self._normalize(key) == normalized:
                return MappingResult(original, target, 0.75, "general")

        # Layer 6: Fuzzy match
        return self.fuzzy_match(column_name)

    def fuzzy_match(self, column_name: str) -> MappingResult:
        """
        Attempt fuzzy matching using N-gram similarity.

        Returns the best match above threshold (0.5), or no match.
        """
        lower = column_name.lower().strip()
        best_target = None
        best_score = 0.0

        # Check against all known mappings
        all_known = {**GENERAL_MAPPINGS}
        for sw_map in SOFTWARE_MAPPINGS.values():
            all_known.update(sw_map)

        for known_name, target in all_known.items():
            score = self._ngram_similarity(lower, known_name, n=2)
            if score > best_score:
                best_score = score
                best_target = target

        if best_score >= 0.5:
            confidence = round(best_score * 0.85, 2)  # Scale down slightly
            return MappingResult(column_name, best_target, confidence, "fuzzy")

        return MappingResult(column_name, None, 0.0, "none")

    def map_all(
        self,
        columns: list[str],
        software: Optional[str] = None,
        min_confidence: float = 0.5,
    ) -> dict[str, MappingResult]:
        """
        Map all columns at once.

        Returns:
            Dict of original_column → MappingResult
        """
        return {
            col: self.lookup(col, software=software)
            for col in columns
        }

    def get_coverage(
        self,
        columns: list[str],
        software: Optional[str] = None,
        min_confidence: float = 0.5,
    ) -> float:
        """
        What percentage of columns were successfully mapped?

        Returns:
            0.0 to 1.0
        """
        results = self.map_all(columns, software=software)
        mapped = sum(
            1 for r in results.values()
            if r.mapped_to and r.confidence >= min_confidence
        )
        return mapped / len(columns) if columns else 0.0

    # ── Internal helpers ──���──────────────────────────────────────────────────

    @staticmethod
    def _normalize(text: str) -> str:
        """Strip all non-alphanumeric characters for comparison."""
        return re.sub(r"[^a-z0-9]", "", text.lower())

    @staticmethod
    def _ngram_similarity(a: str, b: str, n: int = 2) -> float:
        """Compute N-gram (bigram) similarity between two strings."""
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0

        a_ngrams = set(a[i:i+n] for i in range(len(a) - n + 1))
        b_ngrams = set(b[i:i+n] for i in range(len(b) - n + 1))

        if not a_ngrams or not b_ngrams:
            return 0.0

        intersection = a_ngrams & b_ngrams
        union = a_ngrams | b_ngrams
        return len(intersection) / len(union)


# ── CLI Demo ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mapper = ColumnMapper()

    test_columns = [
        ("Taareekh", None),
        ("Raqam", None),
        ("تاریخ", None),
        ("رقم", None),
        ("Particulars", "tally"),
        ("Vch Type", "tally"),
        ("Memo", "quickbooks_desktop"),
        ("Transacton Date", None),  # typo
        ("Amount (PKR)", None),
    ]

    print("Column Dictionary Lookup Results:")
    print("-" * 70)
    for col, sw in test_columns:
        result = mapper.lookup(col, software=sw)
        sw_label = f" [{sw}]" if sw else ""
        print(
            f"  {col:20s}{sw_label:15s} → "
            f"{result.mapped_to or 'UNMAPPED':20s} "
            f"({result.confidence:.0%}, {result.source})"
        )

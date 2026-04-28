"""
schemas/transaction.py
----------------------
Pydantic v2 schemas for transactions + accounts.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class AccountResponse(BaseModel):
    id: str
    code: str
    name: str
    type: str
    parent_code: Optional[str]
    is_active: bool

    model_config = {"from_attributes": True}


class TransactionResponse(BaseModel):
    id: str
    txn_date: date
    description: str
    party_name: Optional[str]
    reference: Optional[str]
    amount: Decimal
    currency: str
    direction: str
    account_id: Optional[str]
    category_hint: Optional[str]
    category_confidence: Optional[float]
    created_at: datetime

    model_config = {"from_attributes": True}


class TransactionListResponse(BaseModel):
    items: List[TransactionResponse]
    total: int
    limit: int
    offset: int


class TransactionFilters(BaseModel):
    """Used by GET /transactions query params."""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    direction: Optional[str] = Field(None, pattern="^(debit|credit)$")
    party_name: Optional[str] = None
    min_amount: Optional[Decimal] = None
    max_amount: Optional[Decimal] = None
    account_id: Optional[str] = None
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)

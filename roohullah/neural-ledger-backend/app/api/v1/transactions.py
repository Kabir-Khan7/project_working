"""
api/v1/transactions.py
----------------------
Routes:
  GET  /api/v1/orgs/{org_id}/transactions          → list with filters
  GET  /api/v1/orgs/{org_id}/transactions/{tx_id}  → single tx
  GET  /api/v1/orgs/{org_id}/accounts              → chart of accounts
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from app.core.dependencies import CurrentUser, DBSession, require_org_member
from app.models.account import Account
from app.models.transaction import Transaction
from app.schemas.transaction import (
    AccountResponse,
    TransactionListResponse,
    TransactionResponse,
)

router = APIRouter(prefix="/orgs/{org_id}", tags=["Transactions & Accounts"])


# ── List transactions ─────────────────────────────────────────────────────────
@router.get("/transactions", response_model=TransactionListResponse)
async def list_transactions(
    org_id: str,
    db: DBSession,
    user: CurrentUser,
    start_date: Optional[date] = Query(None),
    end_date:   Optional[date] = Query(None),
    direction:  Optional[str]  = Query(None, pattern="^(debit|credit)$"),
    party_name: Optional[str]  = Query(None),
    min_amount: Optional[Decimal] = Query(None),
    max_amount: Optional[Decimal] = Query(None),
    account_id: Optional[str]  = Query(None),
    limit:  int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _=Depends(require_org_member("viewer")),
):
    query = select(Transaction).where(Transaction.org_id == org_id)

    if start_date: query = query.where(Transaction.txn_date >= start_date)
    if end_date:   query = query.where(Transaction.txn_date <= end_date)
    if direction:  query = query.where(Transaction.direction == direction)
    if party_name:
        query = query.where(Transaction.party_name.ilike(f"%{party_name}%"))
    if min_amount is not None: query = query.where(Transaction.amount >= min_amount)
    if max_amount is not None: query = query.where(Transaction.amount <= max_amount)
    if account_id: query = query.where(Transaction.account_id == account_id)

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar_one()

    # Page
    rows = await db.execute(
        query.order_by(Transaction.txn_date.desc(), Transaction.created_at.desc())
             .offset(offset).limit(limit)
    )
    items = rows.scalars().all()

    return TransactionListResponse(
        items=items, total=total, limit=limit, offset=offset,
    )


# ── Single transaction ────────────────────────────────────────────────────────
@router.get("/transactions/{tx_id}", response_model=TransactionResponse)
async def get_transaction(
    org_id: str,
    tx_id: str,
    db: DBSession,
    user: CurrentUser,
    _=Depends(require_org_member("viewer")),
):
    tx = await db.get(Transaction, tx_id)
    if not tx or tx.org_id != org_id:
        raise HTTPException(404, "Transaction not found")
    return tx


# ── Chart of accounts ─────────────────────────────────────────────────────────
@router.get("/accounts", response_model=list[AccountResponse])
async def list_accounts(
    org_id: str,
    db: DBSession,
    user: CurrentUser,
    _=Depends(require_org_member("viewer")),
):
    result = await db.execute(
        select(Account)
        .where(Account.org_id == org_id, Account.is_active == True)
        .order_by(Account.code)
    )
    return result.scalars().all()

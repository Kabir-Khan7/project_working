"""
test_ingestion.py
-----------------
End-to-end tests for /api/v1/orgs/{org_id}/ingest/* and /transactions endpoints.
"""

import io

import pandas as pd
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


USER = {
    "email": "founder@arkin.dev",
    "full_name": "Founder",
    "password": "Password123",
}
ORG = {"name": "Acme", "slug": "acme", "industry": "retail"}


# ── Helpers ───────────────────────────────────────────────────────────────────
def auth_h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def setup_org(client) -> tuple[str, str]:
    """Register user, create org, return (token, org_id)."""
    await client.post("/api/v1/auth/register", json=USER)
    login = await client.post("/api/v1/auth/login", json={
        "email": USER["email"], "password": USER["password"],
    })
    token = login.json()["access_token"]
    r = await client.post("/api/v1/orgs", json=ORG, headers=auth_h(token))
    return token, r.json()["id"]


def sample_csv() -> bytes:
    df = pd.DataFrame({
        "Date":         ["2025-01-15", "2025-01-16", "2025-01-17"],
        "Description":  ["Salary",     "Office Rent",  "Sale to ABC Co"],
        "Party":        ["Self",       "Landlord",     "ABC Co"],
        "Debit":        [0,            50000,          0],
        "Credit":       [200000,       0,              80000],
    })
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


def sample_xlsx() -> bytes:
    df = pd.DataFrame({
        "txn_date":    ["2025-02-01", "2025-02-05"],
        "description": ["Internet bill", "Cash sale"],
        "amount":      [-3500, 12000],
    })
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


# ── Upload happy-path ─────────────────────────────────────────────────────────
async def test_upload_csv_success(client):
    token, org_id = await setup_org(client)

    res = await client.post(
        f"/api/v1/orgs/{org_id}/ingest/upload",
        headers=auth_h(token),
        files={"file": ("transactions.csv", sample_csv(), "text/csv")},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["job"]["status"] == "completed"
    assert body["job"]["rows_total"] == 3
    assert body["job"]["rows_imported"] == 3
    assert body["duplicate"] is False


async def test_upload_xlsx_success(client):
    token, org_id = await setup_org(client)

    res = await client.post(
        f"/api/v1/orgs/{org_id}/ingest/upload",
        headers=auth_h(token),
        files={"file": ("ledger.xlsx", sample_xlsx(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert res.status_code == 201
    assert res.json()["job"]["rows_imported"] == 2


# ── Idempotency ───────────────────────────────────────────────────────────────
async def test_upload_duplicate_file_blocked(client):
    token, org_id = await setup_org(client)
    csv = sample_csv()

    first = await client.post(
        f"/api/v1/orgs/{org_id}/ingest/upload",
        headers=auth_h(token),
        files={"file": ("transactions.csv", csv, "text/csv")},
    )
    assert first.status_code == 201

    second = await client.post(
        f"/api/v1/orgs/{org_id}/ingest/upload",
        headers=auth_h(token),
        files={"file": ("transactions.csv", csv, "text/csv")},
    )
    assert second.status_code == 201
    assert second.json()["duplicate"] is True


# ── Validation ────────────────────────────────────────────────────────────────
async def test_upload_unsupported_format(client):
    token, org_id = await setup_org(client)

    res = await client.post(
        f"/api/v1/orgs/{org_id}/ingest/upload",
        headers=auth_h(token),
        files={"file": ("garbage.txt", b"not a real file", "text/plain")},
    )
    assert res.status_code == 201   # job is created but failed
    assert res.json()["job"]["status"] == "failed"


async def test_upload_requires_auth(client):
    token, org_id = await setup_org(client)
    res = await client.post(
        f"/api/v1/orgs/{org_id}/ingest/upload",
        files={"file": ("x.csv", sample_csv(), "text/csv")},
    )
    assert res.status_code == 403


# ── Listing transactions ──────────────────────────────────────────────────────
async def test_list_transactions_after_upload(client):
    token, org_id = await setup_org(client)
    await client.post(
        f"/api/v1/orgs/{org_id}/ingest/upload",
        headers=auth_h(token),
        files={"file": ("t.csv", sample_csv(), "text/csv")},
    )

    res = await client.get(
        f"/api/v1/orgs/{org_id}/transactions",
        headers=auth_h(token),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3
    # Date ordering: most recent first
    dates = [item["txn_date"] for item in data["items"]]
    assert dates == sorted(dates, reverse=True)


async def test_list_transactions_with_filters(client):
    token, org_id = await setup_org(client)
    await client.post(
        f"/api/v1/orgs/{org_id}/ingest/upload",
        headers=auth_h(token),
        files={"file": ("t.csv", sample_csv(), "text/csv")},
    )

    # Filter by direction=debit only
    res = await client.get(
        f"/api/v1/orgs/{org_id}/transactions",
        headers=auth_h(token),
        params={"direction": "debit"},
    )
    items = res.json()["items"]
    assert all(i["direction"] == "debit" for i in items)

    # Filter by min_amount
    res = await client.get(
        f"/api/v1/orgs/{org_id}/transactions",
        headers=auth_h(token),
        params={"min_amount": "100000"},
    )
    items = res.json()["items"]
    assert all(float(i["amount"]) >= 100000 for i in items)


# ── Chart of accounts auto-seeded ─────────────────────────────────────────────
async def test_coa_seeded_on_org_creation(client):
    token, org_id = await setup_org(client)
    res = await client.get(
        f"/api/v1/orgs/{org_id}/accounts",
        headers=auth_h(token),
    )
    assert res.status_code == 200
    accounts = res.json()
    assert len(accounts) > 20
    codes = {a["code"] for a in accounts}
    assert "1010" in codes      # Cash in Hand
    assert "5100" in codes      # Salaries & Wages
    assert "4010" in codes      # Sales — Local

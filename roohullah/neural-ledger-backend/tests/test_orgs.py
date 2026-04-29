"""
test_orgs.py
------------
Unit tests for /api/v1/orgs/* endpoints.
"""

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


USER_A = {
    "email": "founder@arkin.dev",
    "full_name": "Founder A",
    "password": "Password123",
}
USER_B = {
    "email": "member@arkin.dev",
    "full_name": "Member B",
    "password": "Password123",
}
ORG_PAYLOAD = {
    "name": "Acme Traders",
    "slug": "acme-traders",
    "industry": "retail",
}


# ── helpers ───────────────────────────────────────────────────────────────────
async def register_and_login(client, payload):
    await client.post("/api/v1/auth/register", json=payload)
    login = await client.post("/api/v1/auth/login", json={
        "email": payload["email"], "password": payload["password"],
    })
    return login.json()["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── create org ────────────────────────────────────────────────────────────────
async def test_create_org_success(client):
    token = await register_and_login(client, USER_A)
    res = await client.post("/api/v1/orgs", json=ORG_PAYLOAD, headers=auth(token))
    assert res.status_code == 201
    data = res.json()
    assert data["slug"] == "acme-traders"
    assert data["currency"] == "PKR"
    assert data["country"] == "PK"


async def test_create_org_duplicate_slug(client):
    token = await register_and_login(client, USER_A)
    await client.post("/api/v1/orgs", json=ORG_PAYLOAD, headers=auth(token))
    res = await client.post("/api/v1/orgs", json=ORG_PAYLOAD, headers=auth(token))
    assert res.status_code == 409


async def test_create_org_requires_auth(client):
    res = await client.post("/api/v1/orgs", json=ORG_PAYLOAD)
    assert res.status_code == 403


# ── list orgs ─────────────────────────────────────────────────────────────────
async def test_list_my_orgs(client):
    token = await register_and_login(client, USER_A)
    await client.post("/api/v1/orgs", json=ORG_PAYLOAD, headers=auth(token))

    res = await client.get("/api/v1/orgs", headers=auth(token))
    assert res.status_code == 200
    orgs = res.json()
    assert len(orgs) == 1
    assert orgs[0]["slug"] == "acme-traders"


# ── members: invite + RBAC ────────────────────────────────────────────────────
async def test_invite_member_as_admin(client):
    admin_token = await register_and_login(client, USER_A)
    await register_and_login(client, USER_B)   # creates the invitee account

    org = await client.post("/api/v1/orgs", json=ORG_PAYLOAD, headers=auth(admin_token))
    org_id = org.json()["id"]

    res = await client.post(
        f"/api/v1/orgs/{org_id}/members",
        json={"email": USER_B["email"], "role": "member"},
        headers=auth(admin_token),
    )
    assert res.status_code == 201
    assert res.json()["role"] == "member"


async def test_non_admin_cannot_invite(client):
    admin_token = await register_and_login(client, USER_A)
    member_token = await register_and_login(client, USER_B)

    org = await client.post("/api/v1/orgs", json=ORG_PAYLOAD, headers=auth(admin_token))
    org_id = org.json()["id"]

    # Add B as plain member
    await client.post(
        f"/api/v1/orgs/{org_id}/members",
        json={"email": USER_B["email"], "role": "member"},
        headers=auth(admin_token),
    )

    # B tries to invite — must be rejected
    res = await client.post(
        f"/api/v1/orgs/{org_id}/members",
        json={"email": "third@arkin.dev", "role": "member"},
        headers=auth(member_token),
    )
    assert res.status_code == 403


async def test_non_member_cannot_view_org(client):
    admin_token = await register_and_login(client, USER_A)
    outsider_token = await register_and_login(client, USER_B)

    org = await client.post("/api/v1/orgs", json=ORG_PAYLOAD, headers=auth(admin_token))
    org_id = org.json()["id"]

    res = await client.get(f"/api/v1/orgs/{org_id}", headers=auth(outsider_token))
    assert res.status_code == 403

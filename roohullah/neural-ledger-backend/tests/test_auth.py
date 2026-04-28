"""
test_auth.py
------------
Unit tests for /api/v1/auth/* endpoints.
"""

import pytest


pytestmark = pytest.mark.asyncio


# ── Helpers ───────────────────────────────────────────────────────────────────
USER_PAYLOAD = {
    "email": "test@arkin.dev",
    "full_name": "Test User",
    "password": "SecurePass123",
}


# ── Register ──────────────────────────────────────────────────────────────────
async def test_register_success(client):
    res = await client.post("/api/v1/auth/register", json=USER_PAYLOAD)
    assert res.status_code == 201
    data = res.json()
    assert data["email"] == USER_PAYLOAD["email"]
    assert data["full_name"] == USER_PAYLOAD["full_name"]
    assert "id" in data
    assert "password" not in data        # never leak password
    assert "password_hash" not in data    # never leak hash either


async def test_register_duplicate_email(client):
    await client.post("/api/v1/auth/register", json=USER_PAYLOAD)
    res = await client.post("/api/v1/auth/register", json=USER_PAYLOAD)
    assert res.status_code == 409


async def test_register_weak_password(client):
    bad = {**USER_PAYLOAD, "password": "weakpass"}        # no digit, no uppercase
    res = await client.post("/api/v1/auth/register", json=bad)
    assert res.status_code == 422


async def test_register_invalid_email(client):
    bad = {**USER_PAYLOAD, "email": "not-an-email"}
    res = await client.post("/api/v1/auth/register", json=bad)
    assert res.status_code == 422


# ── Login ─────────────────────────────────────────────────────────────────────
async def test_login_success(client):
    await client.post("/api/v1/auth/register", json=USER_PAYLOAD)
    res = await client.post("/api/v1/auth/login", json={
        "email": USER_PAYLOAD["email"],
        "password": USER_PAYLOAD["password"],
    })
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0


async def test_login_wrong_password(client):
    await client.post("/api/v1/auth/register", json=USER_PAYLOAD)
    res = await client.post("/api/v1/auth/login", json={
        "email": USER_PAYLOAD["email"],
        "password": "WrongPass123",
    })
    assert res.status_code == 401


async def test_login_unknown_user(client):
    res = await client.post("/api/v1/auth/login", json={
        "email": "ghost@arkin.dev",
        "password": "DoesntMatter1",
    })
    assert res.status_code == 401


# ── Me ────────────────────────────────────────────────────────────────────────
async def test_me_requires_auth(client):
    res = await client.get("/api/v1/auth/me")
    assert res.status_code == 403   # no Bearer header → HTTPBearer rejects


async def test_me_returns_profile(client):
    await client.post("/api/v1/auth/register", json=USER_PAYLOAD)
    login = await client.post("/api/v1/auth/login", json={
        "email": USER_PAYLOAD["email"],
        "password": USER_PAYLOAD["password"],
    })
    token = login.json()["access_token"]

    res = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json()["email"] == USER_PAYLOAD["email"]


# ── Refresh ───────────────────────────────────────────────────────────────────
async def test_refresh_token_rotates(client):
    await client.post("/api/v1/auth/register", json=USER_PAYLOAD)
    login = await client.post("/api/v1/auth/login", json={
        "email": USER_PAYLOAD["email"],
        "password": USER_PAYLOAD["password"],
    })
    refresh = login.json()["refresh_token"]

    res = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert res.status_code == 200
    new = res.json()
    assert "access_token" in new and new["access_token"]


async def test_refresh_with_access_token_rejected(client):
    """Access token shouldn't work in /refresh — only refresh tokens allowed."""
    await client.post("/api/v1/auth/register", json=USER_PAYLOAD)
    login = await client.post("/api/v1/auth/login", json={
        "email": USER_PAYLOAD["email"],
        "password": USER_PAYLOAD["password"],
    })
    access = login.json()["access_token"]

    res = await client.post("/api/v1/auth/refresh", json={"refresh_token": access})
    assert res.status_code == 401

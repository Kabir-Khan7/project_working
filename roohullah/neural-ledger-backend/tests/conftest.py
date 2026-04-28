"""
conftest.py
-----------
Shared pytest fixtures:
  - test database (creates + drops tables per test session)
  - async HTTP client bound to the FastAPI app
  - dependency override so `get_db` yields the test session
"""

import asyncio
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Ensure config picks up test env vars before importing the app
os.environ.setdefault("DATABASE_URL",
    "postgresql+asyncpg://postgres:password@localhost:5432/neural_ledger_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-ci-only")
os.environ.setdefault("MASTER_ENCRYPTION_KEY", "test-aes-master-key-for-ci-only")
os.environ.setdefault("ENVIRONMENT", "test")

from app.core.config import settings  # noqa: E402
from app.core.dependencies import get_db  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.main import app  # noqa: E402


# ── Event loop (function-scoped) ──────────────────────────────────────────────
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Test engine + tables ──────────────────────────────────────────────────────
@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ── Per-test session that rolls back ──────────────────────────────────────────
@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncSession:
    SessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
        # Cleanup any data created so tests are isolated
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(table.delete())
        await session.commit()


# ── Async HTTP client with DB override ────────────────────────────────────────
@pytest_asyncio.fixture
async def client(db_session) -> AsyncClient:
    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()

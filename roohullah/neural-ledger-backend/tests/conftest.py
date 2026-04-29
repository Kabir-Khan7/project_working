"""
conftest.py
-----------
Shared pytest fixtures:
  - test database (creates + drops tables per test session)
  - async HTTP client bound to the FastAPI app
  - dependency override so `get_db` yields the test session

Note on pytest-asyncio 0.24+:
  We set asyncio_default_fixture_loop_scope = session in pytest.ini.
  This means ALL async fixtures share one event loop for the whole test
  session — no more "two kitchens" deadlock. The old manual event_loop
  fixture is no longer needed.
"""

import os

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Force test env vars — use os.environ[] not setdefault() so we override
# whatever the Docker container already has set (e.g. DATABASE_URL pointing
# at the live neural_ledger DB). Tests must use neural_ledger_test so that
# drop_all / create_all don't conflict with the running API server's
# connection pool.
os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:password@db:5432/neural_ledger_test"
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-ci-only")
os.environ.setdefault("MASTER_ENCRYPTION_KEY", "test-aes-master-key-for-ci-only")
os.environ["ENVIRONMENT"] = "test"

from app.core.config import settings  # noqa: E402
from app.core.dependencies import get_db  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.main import app  # noqa: E402


# ── Test engine + tables ──────────────────────────────────────────────────────
# loop_scope="session" → this fixture shares the SAME event loop as all tests.
# Without this, pytest-asyncio 0.24 would put it in a different loop from the
# function-scoped tests → "Future attached to a different loop" crash.
@pytest_asyncio.fixture(scope="session", loop_scope="session")
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
@pytest_asyncio.fixture(loop_scope="session")
async def db_session(test_engine) -> AsyncSession:
    SessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
        # Cleanup any data created so tests are isolated
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(table.delete())
        await session.commit()


# ── Async HTTP client with DB override ────────────────────────────────────────
@pytest_asyncio.fixture(loop_scope="session")
async def client(db_session) -> AsyncClient:
    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()

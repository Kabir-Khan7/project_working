"""
session.py
----------
Async SQLAlchemy engine + session factory.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,       # logs SQL when DEBUG=True
    pool_pre_ping=True,        # recycles stale connections
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,    # avoids lazy-load errors after commit
    autoflush=False,
    autocommit=False,
)

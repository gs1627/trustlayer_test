from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings, normalize_database_url
from app.db import models  # noqa: F401 - register ORM models
from app.db.migrations import ensure_database_schema, verify_database_schema


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def _build_engine(database_url: str) -> tuple[AsyncEngine, str]:
    normalized_url = normalize_database_url(database_url)
    created = create_async_engine(normalized_url, pool_pre_ping=True)
    if created.dialect.name == "sqlite":
        event.listen(created.sync_engine, "connect", _enable_sqlite_foreign_keys)
    return created, normalized_url


engine, _current_database_url = _build_engine(get_settings().database_url)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def set_database_url(database_url: str, *, dispose_existing: bool = True) -> AsyncEngine:
    """Rebind the shared async engine and sessionmaker in place."""
    global engine, _current_database_url
    previous_engine = engine
    new_engine, normalized_url = _build_engine(database_url)
    engine = new_engine
    _current_database_url = normalized_url
    AsyncSessionLocal.configure(bind=new_engine)
    if dispose_existing and previous_engine is not None:
        previous_engine.sync_engine.dispose()
    return new_engine


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    settings = get_settings()
    if settings.app_env == "production":
        await verify_database_schema(engine, database_url=_current_database_url)
        return
    await ensure_database_schema(engine, database_url=_current_database_url)


async def close_db() -> None:
    await engine.dispose()

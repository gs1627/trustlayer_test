from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.rate_limit import reset_rate_limiters
from app.db import session as db_session
from app.main import app
from app.services.events import reset_event_publisher

_ISOLATED_ENV_VARS = (
    "APP_NAME",
    "APP_ENV",
    "API_V1_PREFIX",
    "LOG_LEVEL",
    "DATABASE_URL",
    "DETECTIF_API_KEY",
    "DETECTIF_BASE_URL",
    "DETECTIF_CONNECT_TIMEOUT_SECONDS",
    "DETECTIF_TIMEOUT_SECONDS",
    "DETECTIF_MAX_RETRIES",
    "DETECTIF_RETRY_BACKOFF_SECONDS",
    "DETECTIF_WS_MAX_CONNECTIONS_PER_CALL",
    "DETECTIF_WEBHOOK_SECRET",
    "DETECTIF_WEBHOOK_SECRET_PREVIOUS",
    "WEBHOOK_TOLERANCE_SECONDS",
    "WEBHOOK_MAX_ATTEMPTS",
    "WEBHOOK_RETRY_BASE_SECONDS",
    "CORS_ORIGINS",
    "MAX_UPLOAD_MB",
    "BACKEND_ACCESS_TOKEN",
    "JWT_SECRET_KEY",
    "JWT_ALGORITHM",
    "JWT_ISSUER",
    "JWT_AUDIENCE",
    "JWT_ACCESS_TOKEN_TTL_SECONDS",
    "RATE_LIMIT_ENABLED",
    "RATE_LIMIT_WINDOW_SECONDS",
    "RATE_LIMIT_AUTH_REQUESTS",
    "RATE_LIMIT_CALL_CREATE_REQUESTS",
    "RATE_LIMIT_EVIDENCE_REQUESTS",
    "RATE_LIMIT_ASSESSMENT_REQUESTS",
    "RATE_LIMIT_WEBHOOK_REQUESTS",
    "RATE_LIMIT_WS_CONNECT_REQUESTS",
    "RATE_LIMIT_WS_MESSAGES_PER_WINDOW",
    "TX_POLICY_MIN_ALLOW_TRUST_SCORE",
    "TX_POLICY_BLOCK_TRUST_SCORE",
    "TX_POLICY_HIGH_VALUE_AMOUNT",
    "TX_POLICY_REQUIRE_FINAL_DEEPFAKE",
    "TX_POLICY_REQUIRE_FINAL_VERIFICATION_WHEN_CONFIGURED",
)


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Prevent tests from reading developer shell env vars or backend/.env."""
    for key in _ISOLATED_ENV_VARS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    reset_event_publisher()
    reset_rate_limiters()
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
        reset_event_publisher()
        reset_rate_limiters()


@pytest.fixture
def isolated_sqlite_url(tmp_path) -> str:
    """Provide an isolated per-test SQLite database URL."""
    db_file = (tmp_path / "test_trustlayer.db").as_posix()
    return f"sqlite+aiosqlite:///{db_file}"


@pytest.fixture
def client(
    isolated_sqlite_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """Provide a synchronous FastAPI TestClient bound to an isolated SQLite DB."""
    monkeypatch.setenv("DATABASE_URL", isolated_sqlite_url)
    get_settings.cache_clear()
    db_session.set_database_url(isolated_sqlite_url)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        db_session.set_database_url("sqlite+aiosqlite:///:memory:")


@pytest_asyncio.fixture
async def async_db(
    isolated_sqlite_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Initialize an isolated SQLite database for async DB tests and dispose cleanly."""
    monkeypatch.setenv("DATABASE_URL", isolated_sqlite_url)
    get_settings.cache_clear()
    db_session.set_database_url(isolated_sqlite_url)
    await db_session.init_db()
    try:
        yield db_session.AsyncSessionLocal
    finally:
        await db_session.close_db()
        db_session.set_database_url("sqlite+aiosqlite:///:memory:")


@pytest_asyncio.fixture
async def async_client(
    async_db: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    """Provide an async HTTPX client wired via ASGITransport to an isolated DB."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client

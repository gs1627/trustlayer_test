import asyncio
import io
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, select, text

from app.core.config import BACKEND_DIR, get_settings
from app.db import session as db_session
from app.db.base import Base
from app.db.migrations import adopt_or_upgrade_sync, build_alembic_config, ensure_database_schema
from app.db.models import CallSession, WebhookEvent
from app.main import app


def _create_legacy_priority1_sqlite(db_file: Path) -> None:
    """Create a Priority 1 create_all()-style SQLite DB with pre-existing rows."""
    con = sqlite3.connect(db_file)
    try:
        con.executescript(
            """
            CREATE TABLE webhook_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                delivery_id VARCHAR(160) NOT NULL UNIQUE,
                event_id VARCHAR(160),
                event_type VARCHAR(100) NOT NULL,
                event_created_at VARCHAR(64),
                payload JSON NOT NULL,
                status VARCHAR(30) NOT NULL,
                processing_error TEXT,
                received_at DATETIME NOT NULL
            );
            CREATE INDEX ix_webhook_events_delivery_id ON webhook_events (delivery_id);
            CREATE INDEX ix_webhook_events_event_id ON webhook_events (event_id);
            CREATE INDEX ix_webhook_events_event_type ON webhook_events (event_type);

            CREATE TABLE call_sessions (
                call_id VARCHAR(128) PRIMARY KEY NOT NULL,
                speaker_id VARCHAR(64) NOT NULL,
                provider_stream_id VARCHAR(128),
                status VARCHAR(30) NOT NULL,
                last_deepfake_sequence INTEGER NOT NULL,
                last_provider_event_at VARCHAR(64),
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
            CREATE INDEX ix_call_sessions_provider_stream_id ON call_sessions (provider_stream_id);
            CREATE INDEX ix_call_sessions_speaker_id ON call_sessions (speaker_id);

            INSERT INTO call_sessions (
                call_id, speaker_id, provider_stream_id, status,
                last_deepfake_sequence, last_provider_event_at, created_at, updated_at
            ) VALUES
                ('LEGACY_CALL_Z', 'SPK_1', 'str_1', 'active', 2, '2026-11-11T09:31:24.512Z', '2026-11-11 09:30:00.000000', '2026-11-11 09:31:24.000000'),
                ('LEGACY_CALL_OFFSET', 'SPK_2', NULL, 'created', 0, '2026-11-11T15:01:24+05:30', '2026-11-11 09:30:00.000000', '2026-11-11 09:30:00.000000'),
                ('LEGACY_CALL_BAD_TS', 'SPK_3', NULL, 'created', 0, 'not-a-timestamp', '2026-11-11 09:30:00.000000', '2026-11-11 09:30:00.000000');

            INSERT INTO webhook_events (
                delivery_id, event_id, event_type, event_created_at,
                payload, status, processing_error, received_at
            ) VALUES (
                'msg_legacy_1', 'evt_1', 'stream.started', '2026-11-11T09:31:24.512Z',
                '{"id":"evt_1","type":"stream.started"}', 'received', NULL, '2026-11-11 09:31:25.000000'
            );
            """
        )
        con.commit()
    finally:
        con.close()


def test_fresh_sqlite_migration_upgrade_downgrade_and_schema_parity(tmp_path: Path):
    db_file = tmp_path / "fresh_alembic.db"
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    cfg = build_alembic_config(db_url)

    command.upgrade(cfg, "head")

    sync_engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    try:
        with sync_engine.connect() as conn:
            tables = set(inspect(conn).get_table_names())
            assert {
                "alembic_version",
                "webhook_events",
                "call_sessions",
                "speaker_profiles",
                "provider_operations",
                "evidence_items",
                "trust_assessments",
                "trust_assessment_evidence",
                "simulated_transactions",
            }.issubset(tables)
            # Speculative tables not in scope must NOT exist
            assert "users" not in tables
            assert "audit_logs" not in tables

            rev = MigrationContext.configure(conn).get_current_revision()
            assert rev == "0003_priority4_to_6_schema"

            # Verify zero schema drift between models.py and migrated DB
            mc = MigrationContext.configure(
                conn,
                opts={"compare_type": True, "render_as_batch": True},
            )
            diffs = compare_metadata(mc, Base.metadata)
            assert diffs == []

        # Verify downgrade back to 0002, then 0001, and upgrade back to head
        command.downgrade(cfg, "0002_priority2_schema")
        with sync_engine.connect() as conn:
            assert "simulated_transactions" not in set(inspect(conn).get_table_names())
            assert MigrationContext.configure(conn).get_current_revision() == "0002_priority2_schema"

        command.downgrade(cfg, "0001_initial_priority1")
        with sync_engine.connect() as conn:
            tables_after_down = set(inspect(conn).get_table_names())
            assert {"alembic_version", "webhook_events", "call_sessions"} == tables_after_down

        command.upgrade(cfg, "head")
        with sync_engine.connect() as conn:
            assert MigrationContext.configure(conn).get_current_revision() == "0003_priority4_to_6_schema"
    finally:
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_upgrade_from_priority1_create_all_db_preserves_records(tmp_path: Path):
    db_file = tmp_path / "legacy_priority1.db"
    _create_legacy_priority1_sqlite(db_file)
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"

    db_session.set_database_url(db_url)
    try:
        async with db_session.engine.begin() as conn:
            mode = await conn.run_sync(
                lambda sync_conn: adopt_or_upgrade_sync(sync_conn, database_url=db_url)
            )
        assert mode == "adopted_and_upgraded"

        # Calling a second time must be a clean no-op
        async with db_session.engine.begin() as conn:
            second_mode = await conn.run_sync(
                lambda sync_conn: adopt_or_upgrade_sync(sync_conn, database_url=db_url)
            )
        assert second_mode == "up_to_date"

        async with db_session.AsyncSessionLocal() as session:
            c1 = await session.get(CallSession, "LEGACY_CALL_Z")
            c2 = await session.get(CallSession, "LEGACY_CALL_OFFSET")
            c3 = await session.get(CallSession, "LEGACY_CALL_BAD_TS")
            wh = await session.scalar(
                select(WebhookEvent).where(WebhookEvent.delivery_id == "msg_legacy_1")
            )

            assert c1 is not None and c2 is not None and c3 is not None and wh is not None
            assert c1.checks_mode == "deepfake,verify"
            assert c1.consent_confirmed is False
            assert c1.last_provider_event_at == datetime(2026, 11, 11, 9, 31, 24, 512000, tzinfo=timezone.utc)
            assert c2.last_provider_event_at == datetime(2026, 11, 11, 9, 31, 24, tzinfo=timezone.utc)
            assert c3.last_provider_event_at is None
            assert wh.event_created_at == datetime(2026, 11, 11, 9, 31, 24, 512000, tzinfo=timezone.utc)
            assert wh.payload["type"] == "stream.started"
    finally:
        await db_session.close_db()
        db_session.set_database_url("sqlite+aiosqlite:///:memory:")


@pytest.mark.asyncio
async def test_upgrade_from_empty_alembic_version_and_partial_tables_preserves_records(tmp_path: Path):
    """Ensure interrupted adoption (empty alembic_version + partial tables) upgrades safely."""
    db_file = tmp_path / "partial_legacy.db"
    _create_legacy_priority1_sqlite(db_file)
    con = sqlite3.connect(db_file)
    try:
        con.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        con.execute("CREATE TABLE speaker_profiles (speaker_id VARCHAR(64) PRIMARY KEY, display_name VARCHAR(128), consent_confirmed BOOLEAN NOT NULL, consent_recorded_at DATETIME, enrollment_status VARCHAR(32) NOT NULL, sample_count INTEGER NOT NULL, provider VARCHAR(32) NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)")
        con.commit()
    finally:
        con.close()

    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    db_session.set_database_url(db_url)
    try:
        async with db_session.engine.begin() as conn:
            mode = await conn.run_sync(
                lambda sync_conn: adopt_or_upgrade_sync(sync_conn, database_url=db_url)
            )
        assert mode == "adopted_and_upgraded"

        async with db_session.AsyncSessionLocal() as session:
            c1 = await session.get(CallSession, "LEGACY_CALL_Z")
            assert c1 is not None
            assert c1.checks_mode == "deepfake,verify"
    finally:
        await db_session.close_db()
        db_session.set_database_url("sqlite+aiosqlite:///:memory:")


@pytest.mark.asyncio
async def test_production_startup_requires_migrated_database(
    isolated_sqlite_url: str,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", isolated_sqlite_url)
    get_settings.cache_clear()
    db_session.set_database_url(isolated_sqlite_url)

    try:
        with pytest.raises(RuntimeError, match="alembic upgrade head"):
            await db_session.init_db()

        # Once migrated via Alembic, production startup verification succeeds
        cfg = build_alembic_config(isolated_sqlite_url)
        async with db_session.engine.begin() as conn:
            await conn.run_sync(lambda sc: adopt_or_upgrade_sync(sc, database_url=isolated_sqlite_url))
        await db_session.init_db()
    finally:
        await db_session.close_db()
        db_session.set_database_url("sqlite+aiosqlite:///:memory:")


def test_offline_postgresql_migration_sql_generation():
    buf = io.StringIO()
    cfg = build_alembic_config("postgresql+asyncpg://user:pass@localhost:5432/trustlayer")
    cfg.output_buffer = buf
    command.upgrade(cfg, "head", sql=True)
    sql_out = buf.getvalue()

    assert "CREATE TABLE call_sessions" in sql_out
    assert "CREATE TABLE evidence_items" in sql_out
    assert "CREATE TABLE trust_assessments" in sql_out
    assert "CREATE TABLE trust_assessment_evidence" in sql_out
    assert "TIMESTAMP WITH TIME ZONE" in sql_out
    assert "::timestamptz" in sql_out
    assert "fk_tae_evidence_call" in sql_out


@pytest.mark.asyncio
async def test_incomplete_priority1_schema_is_rejected_without_stamping(tmp_path: Path):
    # Case 1: call_sessions missing speaker_id and webhook_events missing delivery_id unique constraint
    db_file = tmp_path / "incomplete_p1.db"
    con = sqlite3.connect(db_file)
    try:
        con.executescript(
            """
            CREATE TABLE webhook_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                delivery_id VARCHAR(160) NOT NULL,
                event_type VARCHAR(100) NOT NULL,
                payload JSON NOT NULL,
                status VARCHAR(30) NOT NULL,
                received_at DATETIME NOT NULL
            );
            CREATE TABLE call_sessions (
                call_id VARCHAR(128) PRIMARY KEY NOT NULL,
                status VARCHAR(30) NOT NULL
            );
            """
        )
        con.commit()
    finally:
        con.close()

    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    db_session.set_database_url(db_url)
    try:
        with pytest.raises(RuntimeError, match="missing required columns"):
            await ensure_database_schema(db_session.engine, database_url=db_url)

        async with db_session.engine.connect() as conn:
            tables = await conn.run_sync(lambda sc: set(inspect(sc).get_table_names()))
            assert "alembic_version" not in tables
    finally:
        await db_session.close_db()
        db_session.set_database_url("sqlite+aiosqlite:///:memory:")


@pytest.mark.asyncio
async def test_incomplete_priority2_schema_is_rejected_without_stamping(tmp_path: Path):
    # Start from a complete Priority 1 DB, add checks_mode + processed_at + evidence_items WITHOUT FK/trust_assessments
    db_file = tmp_path / "incomplete_p2.db"
    _create_legacy_priority1_sqlite(db_file)
    con = sqlite3.connect(db_file)
    try:
        con.executescript(
            """
            ALTER TABLE webhook_events ADD COLUMN processed_at DATETIME;
            ALTER TABLE call_sessions ADD COLUMN checks_mode VARCHAR(32) NOT NULL DEFAULT 'deepfake,verify';
            CREATE TABLE evidence_items (
                evidence_id VARCHAR(64) PRIMARY KEY,
                call_id VARCHAR(128) NOT NULL
            );
            """
        )
        con.commit()
    finally:
        con.close()

    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    db_session.set_database_url(db_url)
    try:
        with pytest.raises(RuntimeError, match="missing required columns"):
            await ensure_database_schema(db_session.engine, database_url=db_url)

        async with db_session.engine.connect() as conn:
            tables = await conn.run_sync(lambda sc: set(inspect(sc).get_table_names()))
            assert "alembic_version" not in tables
    finally:
        await db_session.close_db()
        db_session.set_database_url("sqlite+aiosqlite:///:memory:")


@pytest.mark.asyncio
async def test_complete_priority2_schema_without_version_row_adopts_head(tmp_path: Path):
    db_file = tmp_path / "complete_unstamped_p2.db"
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    cfg = build_alembic_config(db_url)
    await asyncio.to_thread(command.upgrade, cfg, "head")

    # Drop alembic_version to simulate an unstamped complete Priority 2 schema
    con = sqlite3.connect(db_file)
    try:
        con.execute("DROP TABLE alembic_version")
        con.commit()
    finally:
        con.close()

    db_session.set_database_url(db_url)
    try:
        mode = await ensure_database_schema(db_session.engine, database_url=db_url)
        assert mode == "adopted_head"
        async with db_session.engine.connect() as conn:
            rev = await conn.run_sync(lambda sc: MigrationContext.configure(sc).get_current_revision())
            assert rev == "0003_priority4_to_6_schema"
    finally:
        await db_session.close_db()
        db_session.set_database_url("sqlite+aiosqlite:///:memory:")


@pytest.mark.asyncio
async def test_concurrent_migration_startup_in_process_and_multiprocess(tmp_path: Path):
    # 1. In-process concurrent tasks against legacy Priority 1 DB
    db_file = tmp_path / "concurrent_inproc.db"
    _create_legacy_priority1_sqlite(db_file)
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    db_session.set_database_url(db_url)
    try:
        results = await asyncio.gather(
            *(ensure_database_schema(db_session.engine, database_url=db_url) for _ in range(5))
        )
        assert results.count("adopted_and_upgraded") == 1
        assert results.count("up_to_date") == 4

        async with db_session.AsyncSessionLocal() as session:
            c1 = await session.get(CallSession, "LEGACY_CALL_Z")
            assert c1 is not None
    finally:
        await db_session.close_db()
        db_session.set_database_url("sqlite+aiosqlite:///:memory:")

    # 2. Multi-process OS lock race against fresh SQLite DB
    mp_db = tmp_path / "concurrent_multiproc.db"
    mp_url = f"sqlite+aiosqlite:///{mp_db.as_posix()}"
    script_file = tmp_path / "run_init.py"
    script_file.write_text(
        "\n".join(
            [
                "import asyncio, os, sys",
                f"sys.path.insert(0, {str(BACKEND_DIR)!r})",
                "os.environ['APP_ENV'] = 'test'",
                "os.environ['DATABASE_URL'] = sys.argv[1]",
                "from app.db.session import close_db, init_db",
                "async def main():",
                "    try:",
                "        await init_db()",
                "    finally:",
                "        await close_db()",
                "asyncio.run(main())",
            ]
        ),
        encoding="utf-8",
    )

    procs = [
        subprocess.Popen(
            [sys.executable, str(script_file), mp_url],
            cwd=str(BACKEND_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(3)
    ]
    for proc in procs:
        out, err = proc.communicate(timeout=20)
        assert proc.returncode == 0, f"Worker failed: {out}\n{err}"

    sync_engine = create_engine(f"sqlite:///{mp_db.as_posix()}")
    try:
        with sync_engine.connect() as conn:
            assert MigrationContext.configure(conn).get_current_revision() == "0003_priority4_to_6_schema"
    finally:
        sync_engine.dispose()

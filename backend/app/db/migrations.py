import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import hashlib
import os
from pathlib import Path
import tempfile
import time
from typing import Any
import weakref

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Inspector
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import BACKEND_DIR, get_settings, normalize_database_url

ALEMBIC_INI_PATH = BACKEND_DIR / "alembic.ini"
PRIORITY1_REVISION = "0001_initial_priority1"
PRIORITY2_REVISION = "0002_priority2_schema"
_PG_MIGRATION_LOCK_ID = 6075996008259518809  # Deterministic 64-bit signed key for TRUSTLAYER

_LOOP_LOCKS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)

_PRIORITY1_COLUMNS: dict[str, set[str]] = {
    "webhook_events": {
        "id",
        "delivery_id",
        "event_id",
        "event_type",
        "event_created_at",
        "payload",
        "status",
        "processing_error",
        "received_at",
    },
    "call_sessions": {
        "call_id",
        "speaker_id",
        "provider_stream_id",
        "status",
        "last_deepfake_sequence",
        "last_provider_event_at",
        "created_at",
        "updated_at",
    },
}

_PRIORITY1_PKS: dict[str, list[str]] = {
    "webhook_events": ["id"],
    "call_sessions": ["call_id"],
}

_PRIORITY2_COLUMNS: dict[str, set[str]] = {
    "webhook_events": _PRIORITY1_COLUMNS["webhook_events"] | {"processed_at"},
    "call_sessions": _PRIORITY1_COLUMNS["call_sessions"]
    | {
        "checks_mode",
        "consent_confirmed",
        "consent_recorded_at",
        "ended_at",
        "ended_reason",
    },
    "speaker_profiles": {
        "speaker_id",
        "display_name",
        "consent_confirmed",
        "consent_recorded_at",
        "enrollment_status",
        "sample_count",
        "provider",
        "created_at",
        "updated_at",
    },
    "provider_operations": {
        "id",
        "call_id",
        "speaker_id",
        "provider",
        "operation_type",
        "request_id",
        "operation_id",
        "stream_id",
        "idempotency_key",
        "status",
        "credits",
        "raw_response",
        "created_at",
        "updated_at",
    },
    "evidence_items": {
        "evidence_id",
        "call_id",
        "speaker_id",
        "provider",
        "model",
        "check_type",
        "status",
        "verdict",
        "raw_score",
        "score_type",
        "is_early",
        "is_final",
        "source_channel",
        "source_event_key",
        "sequence",
        "provider_operation_id",
        "provider_request_id",
        "provider_stream_id",
        "observed_at",
        "details",
        "created_at",
    },
    "trust_assessments": {
        "assessment_id",
        "call_id",
        "trust_score",
        "risk_level",
        "recommended_action",
        "summary",
        "reasons",
        "is_final",
        "model_version",
        "created_at",
    },
    "trust_assessment_evidence": {
        "assessment_id",
        "evidence_id",
        "call_id",
        "created_at",
    },
}

_PRIORITY2_PKS: dict[str, list[str]] = {
    "webhook_events": ["id"],
    "call_sessions": ["call_id"],
    "speaker_profiles": ["speaker_id"],
    "provider_operations": ["id"],
    "evidence_items": ["evidence_id"],
    "trust_assessments": ["assessment_id"],
    "trust_assessment_evidence": ["assessment_id", "evidence_id"],
}

_PARTIAL_P2_TABLES = (
    "speaker_profiles",
    "provider_operations",
    "evidence_items",
    "trust_assessments",
    "trust_assessment_evidence",
)

_PRIORITY3_PLUS_EXTRA_COLUMNS: dict[str, set[str]] = {
    "webhook_events": {"call_id", "attempt_count", "last_attempt_at", "next_retry_at", "dead_lettered_at"},
    "speaker_profiles": {"owner_id"},
    "call_sessions": {"owner_id"},
    "provider_operations": {
        "correlation_id",
        "retry_count",
        "error_code",
        "error_message",
        "failure_details",
        "started_at",
        "completed_at",
    },
    "simulated_transactions": {
        "transaction_id",
        "call_id",
        "assessment_id",
        "actor_subject",
        "action_type",
        "amount",
        "currency",
        "recipient_ref",
        "notes",
        "decision",
        "policy_reasons",
        "evidence_ids",
        "policy_version",
        "simulated",
        "created_at",
    },
}


def _get_loop_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _LOOP_LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _LOOP_LOCKS[loop] = lock
    return lock


def _has_unique_columns(inspector: Inspector, table_name: str, expected_cols: list[str]) -> bool:
    for uc in inspector.get_unique_constraints(table_name):
        if uc.get("column_names") == expected_cols:
            return True
    for idx in inspector.get_indexes(table_name):
        if idx.get("unique") and idx.get("column_names") == expected_cols:
            return True
    if inspector.dialect.name == "sqlite":
        safe_table = table_name.replace('"', '""')
        for idx_row in inspector.bind.execute(text(f'PRAGMA index_list("{safe_table}")')).fetchall():
            if idx_row[2] == 1:
                idx_name = str(idx_row[1]).replace('"', '""')
                info_rows = inspector.bind.execute(text(f'PRAGMA index_info("{idx_name}")')).fetchall()
                cols = [row[2] for row in sorted(info_rows, key=lambda r: r[0])]
                if cols == expected_cols:
                    return True
    return False


def _has_foreign_key(
    inspector: Inspector,
    table_name: str,
    constrained_cols: list[str],
    referred_table: str,
    referred_cols: list[str],
) -> bool:
    for fk in inspector.get_foreign_keys(table_name):
        if (
            fk.get("referred_table") == referred_table
            and fk.get("constrained_columns") == constrained_cols
            and fk.get("referred_columns") == referred_cols
        ):
            return True
    return False


def _verify_table_columns_and_pk(
    inspector: Inspector,
    table_name: str,
    expected_cols: set[str],
    expected_pk: list[str],
) -> dict[str, dict[str, Any]]:
    col_map = {col["name"]: col for col in inspector.get_columns(table_name)}
    missing = sorted(expected_cols - set(col_map))
    if missing:
        raise RuntimeError(
            f"Database table '{table_name}' is missing required columns {missing}; refusing to stamp."
        )
    pk_cols = inspector.get_pk_constraint(table_name).get("constrained_columns") or []
    if pk_cols != expected_pk:
        raise RuntimeError(
            f"Database table '{table_name}' primary key {pk_cols} does not match expected {expected_pk}; refusing to stamp."
        )
    return col_map


def _verify_priority1_schema(inspector: Inspector) -> None:
    for table_name in ("webhook_events", "call_sessions"):
        _verify_table_columns_and_pk(
            inspector,
            table_name,
            _PRIORITY1_COLUMNS[table_name],
            _PRIORITY1_PKS[table_name],
        )
    if not _has_unique_columns(inspector, "webhook_events", ["delivery_id"]):
        raise RuntimeError(
            "Database table 'webhook_events' is missing unique constraint on 'delivery_id'; refusing to stamp."
        )


def _verify_priority2_table_details(inspector: Inspector, table_name: str) -> None:
    _verify_table_columns_and_pk(
        inspector,
        table_name,
        _PRIORITY2_COLUMNS[table_name],
        _PRIORITY2_PKS[table_name],
    )
    if table_name == "provider_operations":
        if not _has_unique_columns(inspector, "provider_operations", ["operation_id"]):
            raise RuntimeError("Table 'provider_operations' is missing unique constraint on 'operation_id'.")
        if not _has_foreign_key(inspector, "provider_operations", ["call_id"], "call_sessions", ["call_id"]):
            raise RuntimeError("Table 'provider_operations' is missing foreign key to 'call_sessions'.")
    elif table_name == "evidence_items":
        if not _has_foreign_key(inspector, "evidence_items", ["call_id"], "call_sessions", ["call_id"]):
            raise RuntimeError("Table 'evidence_items' is missing foreign key to 'call_sessions'.")
        if not _has_unique_columns(inspector, "evidence_items", ["evidence_id", "call_id"]):
            raise RuntimeError("Table 'evidence_items' is missing unique constraint on ('evidence_id', 'call_id').")
        if not _has_unique_columns(
            inspector,
            "evidence_items",
            ["call_id", "provider", "check_type", "source_event_key"],
        ):
            raise RuntimeError(
                "Table 'evidence_items' is missing unique constraint on ('call_id', 'provider', 'check_type', 'source_event_key')."
            )
    elif table_name == "trust_assessments":
        if not _has_foreign_key(inspector, "trust_assessments", ["call_id"], "call_sessions", ["call_id"]):
            raise RuntimeError("Table 'trust_assessments' is missing foreign key to 'call_sessions'.")
        if not _has_unique_columns(inspector, "trust_assessments", ["assessment_id", "call_id"]):
            raise RuntimeError(
                "Table 'trust_assessments' is missing unique constraint on ('assessment_id', 'call_id')."
            )
    elif table_name == "trust_assessment_evidence":
        if not _has_foreign_key(
            inspector,
            "trust_assessment_evidence",
            ["assessment_id", "call_id"],
            "trust_assessments",
            ["assessment_id", "call_id"],
        ):
            raise RuntimeError("Table 'trust_assessment_evidence' is missing composite FK to 'trust_assessments'.")
        if not _has_foreign_key(
            inspector,
            "trust_assessment_evidence",
            ["evidence_id", "call_id"],
            "evidence_items",
            ["evidence_id", "call_id"],
        ):
            raise RuntimeError("Table 'trust_assessment_evidence' is missing composite FK to 'evidence_items'.")


def _verify_complete_priority2_schema(inspector: Inspector, tables: set[str]) -> None:
    expected_tables = set(_PRIORITY2_COLUMNS)
    missing_tables = sorted(expected_tables - tables)
    if missing_tables:
        raise RuntimeError(f"Priority 2 schema incomplete; missing tables {missing_tables}.")

    if not _has_unique_columns(inspector, "webhook_events", ["delivery_id"]):
        raise RuntimeError("Table 'webhook_events' is missing unique constraint on 'delivery_id'.")

    cs_cols = _verify_table_columns_and_pk(
        inspector,
        "call_sessions",
        _PRIORITY2_COLUMNS["call_sessions"],
        _PRIORITY2_PKS["call_sessions"],
    )
    if not cs_cols["speaker_id"].get("nullable", False):
        raise RuntimeError("Table 'call_sessions.speaker_id' must be nullable in Priority 2 schema.")

    cs_checks = {ck.get("name") for ck in inspector.get_check_constraints("call_sessions")}
    if not {"ck_call_sessions_checks_mode", "ck_call_sessions_speaker_required"}.issubset(cs_checks):
        raise RuntimeError("Table 'call_sessions' is missing required Priority 2 check constraints.")

    for table_name in ("webhook_events", *_PARTIAL_P2_TABLES):
        _verify_priority2_table_details(inspector, table_name)


def build_alembic_config(database_url: str | None = None) -> Config:
    """Build an Alembic Config anchored to backend/alembic.ini."""
    cfg = Config(str(ALEMBIC_INI_PATH))
    cfg.attributes["skip_logging_config"] = True
    target_url = normalize_database_url(database_url or get_settings().database_url)
    cfg.set_main_option("sqlalchemy.url", target_url.replace("%", "%%"))
    return cfg


def adopt_or_upgrade_sync(
    sync_connection: Connection,
    *,
    database_url: str | None = None,
) -> str:
    """Safely adopt a verified legacy/interrupted DB or upgrade to Alembic head."""
    cfg = build_alembic_config(database_url)
    cfg.attributes["connection"] = sync_connection
    script = ScriptDirectory.from_config(cfg)
    head_rev = script.get_current_head()

    inspector = inspect(sync_connection)
    tables = set(inspector.get_table_names())
    current_rev = (
        MigrationContext.configure(sync_connection).get_current_revision()
        if "alembic_version" in tables
        else None
    )

    if current_rev is None:
        non_alembic_tables = tables - {"alembic_version"}
        if not non_alembic_tables:
            command.upgrade(cfg, "head")
            return "fresh_upgrade"

        if not {"call_sessions", "webhook_events"}.issubset(tables):
            raise RuntimeError(
                "Cannot safely adopt database schema: required baseline tables "
                "'call_sessions' and 'webhook_events' were not both found."
            )

        _verify_priority1_schema(inspector)
        for p2_table in _PARTIAL_P2_TABLES:
            if p2_table in tables:
                _verify_priority2_table_details(inspector, p2_table)

        wh_cols = {col["name"] for col in inspector.get_columns("webhook_events")}
        cs_cols = {col["name"] for col in inspector.get_columns("call_sessions")}
        has_all_p2_tables = set(_PRIORITY2_COLUMNS).issubset(tables)
        if has_all_p2_tables and "checks_mode" in cs_cols and "processed_at" in wh_cols:
            _verify_complete_priority2_schema(inspector, tables)
            if "simulated_transactions" in tables:
                tx_cols = {col["name"] for col in inspector.get_columns("simulated_transactions")}
                if _PRIORITY3_PLUS_EXTRA_COLUMNS["simulated_transactions"].issubset(tx_cols):
                    for tbl in ("webhook_events", "speaker_profiles", "call_sessions", "provider_operations"):
                        extra = _PRIORITY3_PLUS_EXTRA_COLUMNS[tbl]
                        present = {c["name"] for c in inspector.get_columns(tbl)}
                        missing_extra = sorted(extra - present)
                        if missing_extra:
                            raise RuntimeError(
                                f"Table '{tbl}' is missing required migration columns {missing_extra}; refusing to stamp."
                            )
                    command.stamp(cfg, head_rev or "head")
                    return "adopted_head"
                raise RuntimeError("Table 'simulated_transactions' is missing required columns; refusing to stamp.")
            command.stamp(cfg, PRIORITY2_REVISION)
            command.upgrade(cfg, "head")
            return "adopted_and_upgraded"

        command.stamp(cfg, PRIORITY1_REVISION)
        command.upgrade(cfg, "head")
        return "adopted_and_upgraded"

    if current_rev == head_rev:
        return "up_to_date"
    command.upgrade(cfg, "head")
    return "upgraded"


def verify_schema_at_head_sync(
    sync_connection: Connection,
    *,
    database_url: str | None = None,
) -> str:
    """Verify the database has been migrated to the current Alembic head."""
    cfg = build_alembic_config(database_url)
    head_rev = ScriptDirectory.from_config(cfg).get_current_head()
    current_rev = MigrationContext.configure(sync_connection).get_current_revision()
    if current_rev != head_rev:
        raise RuntimeError(
            f"Database schema revision '{current_rev}' does not match Alembic head '{head_rev}'. "
            "Run 'alembic upgrade head' before starting in production."
        )
    return current_rev or ""


def _acquire_file_lock_sync(lock_path: Path, timeout_seconds: float = 30.0) -> int:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    if os.name == "nt":
        import msvcrt

        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\x00")
        deadline = time.monotonic() + timeout_seconds
        while True:
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return fd
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise TimeoutError(f"Timed out waiting for SQLite migration lock: {lock_path}")
                time.sleep(0.02)
    else:
        import fcntl

        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise TimeoutError(f"Timed out waiting for SQLite migration lock: {lock_path}")
                time.sleep(0.02)


def _release_file_lock_sync(fd: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@asynccontextmanager
async def _migration_lock(target_engine: AsyncEngine) -> AsyncIterator[None]:
    """Serialize schema migrations across async tasks and OS worker processes."""
    async with _get_loop_lock():
        dialect_name = target_engine.dialect.name
        if dialect_name == "postgresql":
            async with target_engine.connect() as lock_conn:
                await lock_conn.execute(
                    text("SELECT pg_advisory_lock(:lock_id)"),
                    {"lock_id": _PG_MIGRATION_LOCK_ID},
                )
                try:
                    yield
                finally:
                    await lock_conn.execute(
                        text("SELECT pg_advisory_unlock(:lock_id)"),
                        {"lock_id": _PG_MIGRATION_LOCK_ID},
                    )
            return

        if dialect_name == "sqlite":
            db_name = target_engine.url.database
            if db_name and db_name != ":memory:" and not db_name.startswith("file:"):
                resolved = str(Path(db_name).resolve()).encode("utf-8")
                digest = hashlib.sha256(resolved).hexdigest()[:16]
                lock_path = Path(tempfile.gettempdir()) / f"trustlayer_{digest}.migrate.lock"
                fd = await asyncio.to_thread(_acquire_file_lock_sync, lock_path)
                try:
                    yield
                finally:
                    _release_file_lock_sync(fd)
                return

        yield


async def ensure_database_schema(
    target_engine: AsyncEngine,
    *,
    database_url: str | None = None,
) -> str:
    """Ensure the database schema is initialized/migrated to head via Alembic under lock."""
    async with _migration_lock(target_engine):
        async with target_engine.begin() as connection:
            return await connection.run_sync(
                lambda sync_conn: adopt_or_upgrade_sync(sync_conn, database_url=database_url)
            )


async def verify_database_schema(
    target_engine: AsyncEngine,
    *,
    database_url: str | None = None,
) -> str:
    """Verify database schema revision matches Alembic head without mutating DDL."""
    async with target_engine.connect() as connection:
        return await connection.run_sync(
            lambda sync_conn: verify_schema_at_head_sync(sync_conn, database_url=database_url)
        )

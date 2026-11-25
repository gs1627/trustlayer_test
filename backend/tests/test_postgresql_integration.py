import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import os
import subprocess
import sys
import uuid

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
import asyncpg
import httpx
import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, StatementError

from app.core.config import BACKEND_DIR, normalize_database_url
from app.db import session as db_session
from app.db.base import Base
from app.db.migrations import build_alembic_config, ensure_database_schema
from app.db.models import (
    CallSession,
    EvidenceItem,
    ProviderOperation,
    SpeakerProfile,
    TrustAssessment,
    TrustAssessmentEvidence,
    WebhookEvent,
)
from app.main import app
from app.schemas.contracts import EvidenceItemCreate, TrustAssessmentCreate
from app.services.evidence_repository import EvidenceRepository
from app.services.trust_assessment_repository import TrustAssessmentRepository
from app.services.webhook_service import ingest_webhook_event

PG_ADMIN_URL = os.environ.get("TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not PG_ADMIN_URL,
    reason="TEST_POSTGRES_URL is not set; skipping live PostgreSQL verification",
)


def _strip_asyncpg_scheme(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _replace_db_name(url: str, db_name: str) -> str:
    base, sep, query = url.partition("?")
    prefix, _, _old_db = base.rpartition("/")
    return f"{prefix}/{db_name}{sep}{query}"


async def _create_temp_pg_db() -> tuple[str, str]:
    assert PG_ADMIN_URL is not None
    admin_dsn = _strip_asyncpg_scheme(normalize_database_url(PG_ADMIN_URL))
    db_name = f"tl_pg_test_{uuid.uuid4().hex[:12]}"
    conn = await asyncpg.connect(admin_dsn)
    try:
        await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()
    return db_name, _replace_db_name(normalize_database_url(PG_ADMIN_URL), db_name)


async def _drop_temp_pg_db(db_name: str) -> None:
    assert PG_ADMIN_URL is not None
    admin_dsn = _strip_asyncpg_scheme(normalize_database_url(PG_ADMIN_URL))
    conn = await asyncpg.connect(admin_dsn)
    try:
        await conn.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = $1 AND pid <> pg_backend_pid()
            """,
            db_name,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_postgresql_migrations_parity_and_upgrade_history():
    db_name, async_url = await _create_temp_pg_db()
    cfg = build_alembic_config(async_url)
    try:
        # 1. Fresh Alembic upgrade + model parity + Alembic check.
        await asyncio.to_thread(command.upgrade, cfg, "head")

        db_session.set_database_url(async_url)
        try:
            async with db_session.engine.connect() as conn:
                pg_version = (await conn.execute(text("SELECT version()"))).scalar_one()
                assert "PostgreSQL" in pg_version

                def _inspect_and_parity(sync_conn):
                    insp = inspect(sync_conn)
                    tables = set(insp.get_table_names())
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
                    mc = MigrationContext.configure(sync_conn, opts={"compare_type": True})
                    diffs = compare_metadata(mc, Base.metadata)
                    assert diffs == []

                    # Verify TIMESTAMPTZ columns in PostgreSQL catalog.
                    col_type = str(
                        sync_conn.execute(
                            text(
                                "SELECT data_type FROM information_schema.columns "
                                "WHERE table_name = 'evidence_items' AND column_name = 'observed_at'"
                            )
                        ).scalar_one()
                    ).lower()
                    assert "timestamp with time zone" in col_type
                    return tables

                await conn.run_sync(_inspect_and_parity)

            # 2. Downgrade all the way back through 0002 -> 0001 and re-upgrade with Priority 1 data!
            await asyncio.to_thread(command.downgrade, cfg, "0001_initial_priority1")
            async with db_session.engine.begin() as conn:
                await conn.execute(
                    text(
                        """
                        INSERT INTO call_sessions (
                            call_id, speaker_id, provider_stream_id, status,
                            last_deepfake_sequence, last_provider_event_at, created_at, updated_at
                        ) VALUES
                            ('PG_LEG_Z', 'SPK_1', 'str_1', 'active', 2, '2026-11-11T09:31:24.512Z', now(), now()),
                            ('PG_LEG_OFF', 'SPK_2', NULL, 'created', 0, '2026-11-11T15:01:24+05:30', now(), now()),
                            ('PG_LEG_BAD', 'SPK_3', NULL, 'created', 0, 'corrupt-ts', now(), now())
                        """
                    )
                )
                await conn.execute(
                    text(
                        """
                        INSERT INTO webhook_events (
                            delivery_id, event_id, event_type, event_created_at,
                            payload, status, processing_error, received_at
                        ) VALUES (
                            'pg_msg_1', 'evt_1', 'stream.started', '2026-11-11T09:31:24.512Z',
                            '{"id":"evt_1","type":"stream.started"}'::json, 'received', NULL, now()
                        )
                        """
                    )
                )

            await asyncio.to_thread(command.upgrade, cfg, "head")
            async with db_session.AsyncSessionLocal() as session:
                c1 = await session.get(CallSession, "PG_LEG_Z")
                c2 = await session.get(CallSession, "PG_LEG_OFF")
                c3 = await session.get(CallSession, "PG_LEG_BAD")
                wh = await session.scalar(select(WebhookEvent).where(WebhookEvent.delivery_id == "pg_msg_1"))
                assert c1 is not None and c2 is not None and c3 is not None and wh is not None
                assert c1.last_provider_event_at == datetime(2026, 11, 11, 9, 31, 24, 512000, tzinfo=timezone.utc)
                assert c2.last_provider_event_at == datetime(2026, 11, 11, 9, 31, 24, tzinfo=timezone.utc)
                assert c3.last_provider_event_at is None
                assert wh.event_created_at == datetime(2026, 11, 11, 9, 31, 24, 512000, tzinfo=timezone.utc)
        finally:
            await db_session.close_db()
            assert db_session.engine.pool.checkedout() == 0
            db_session.set_database_url("sqlite+aiosqlite:///:memory:")
    finally:
        await _drop_temp_pg_db(db_name)


@pytest.mark.asyncio
async def test_postgresql_advisory_locking_in_process_and_multiprocess(tmp_path):
    db_name, async_url = await _create_temp_pg_db()
    db_session.set_database_url(async_url)
    try:
        # In-process concurrent advisory lock race on empty Postgres DB.
        results = await asyncio.gather(
            *(ensure_database_schema(db_session.engine, database_url=async_url) for _ in range(5))
        )
        assert results.count("fresh_upgrade") == 1
        assert results.count("up_to_date") == 4
    finally:
        await db_session.close_db()
        db_session.set_database_url("sqlite+aiosqlite:///:memory:")
        await _drop_temp_pg_db(db_name)

    # Multi-process pg_advisory_lock race across 3 separate Python processes.
    mp_db_name, mp_async_url = await _create_temp_pg_db()
    script_file = tmp_path / "pg_init_worker.py"
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
    try:
        procs = [
            subprocess.Popen(
                [sys.executable, str(script_file), mp_async_url],
                cwd=str(BACKEND_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(3)
        ]
        for proc in procs:
            out, err = proc.communicate(timeout=30)
            assert proc.returncode == 0, f"PG worker failed: {out}\n{err}"
    finally:
        await _drop_temp_pg_db(mp_db_name)


@pytest.mark.asyncio
async def test_postgresql_constraints_concurrency_savepoints_and_e2e_apis(monkeypatch: pytest.MonkeyPatch):
    db_name, async_url = await _create_temp_pg_db()
    monkeypatch.setenv("DATABASE_URL", async_url)
    db_session.set_database_url(async_url)
    await db_session.init_db()
    try:
        async with db_session.AsyncSessionLocal() as session:
            session.add_all(
                [
                    SpeakerProfile(speaker_id="PG_SPK_1", consent_confirmed=True, enrollment_status="enrolled"),
                    CallSession(call_id="PG_CALL_A", speaker_id="PG_SPK_1", checks_mode="deepfake,verify"),
                    CallSession(call_id="PG_CALL_B", speaker_id=None, checks_mode="deepfake"),
                ]
            )
            await session.flush()
            op = ProviderOperation(
                call_id="PG_CALL_A",
                speaker_id="PG_SPK_1",
                provider="detectifai",
                operation_type="deepfake.detect",
                idempotency_key="pg_idem_1",
                status="succeeded",
                raw_response={"nested": {"flag": True}},
            )
            ev_b = EvidenceItem(
                evidence_id="pg_ev_b1",
                call_id="PG_CALL_B",
                provider="detectifai",
                model="aletheia",
                check_type="deepfake",
                status="completed",
                source_event_key=None,
                details={"tags": ["a", "b"]},
            )
            # Second NULL source_event_key allowed on PG unique constraint.
            ev_b2 = EvidenceItem(
                evidence_id="pg_ev_b2",
                call_id="PG_CALL_B",
                provider="detectifai",
                model="aletheia",
                check_type="deepfake",
                status="completed",
                source_event_key=None,
            )
            session.add_all([op, ev_b, ev_b2])
            await session.commit()
            op_id = op.id

            # Transaction rollback check & malformed UTC rejection.
            session.add(
                EvidenceItem(
                    evidence_id="pg_ev_bad_ts",
                    call_id="PG_CALL_A",
                    provider="sarvam",
                    model="saaras:v4",
                    check_type="transcription",
                    status="completed",
                    observed_at="bad-ts",  # type: ignore[arg-type]
                )
            )
            with pytest.raises(StatementError):
                await session.commit()
            await session.rollback()

            # Duplicate idempotency key unique constraint check.
            session.add(
                ProviderOperation(
                    call_id="PG_CALL_A",
                    provider="detectifai",
                    operation_type="deepfake.detect",
                    idempotency_key="pg_idem_1",
                    status="pending",
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

            # Delete PG_CALL_B cascades to ev_b; check cross-call TA FK & cascade.
            ta_b = TrustAssessment(
                assessment_id="pg_ta_b",
                call_id="PG_CALL_B",
                trust_score=0.8,
                risk_level="low",
                recommended_action="allow",
                summary="PG test",
                reasons=["r1"],
                model_version="trust-v1",
            )
            session.add(ta_b)
            await session.flush()
            session.add(TrustAssessmentEvidence(assessment_id="pg_ta_b", evidence_id="pg_ev_b1", call_id="PG_CALL_B"))
            await session.commit()

            # Cascade delete PG_CALL_A keeps ProviderOperation with call_id SET NULL.
            call_a = await session.get(CallSession, "PG_CALL_A")
            assert call_a is not None
            await session.delete(call_a)
            await session.commit()
            refreshed_op = await session.get(ProviderOperation, op_id)
            assert refreshed_op is not None and refreshed_op.call_id is None

        # Concurrent evidence insertion across independent sessions on PostgreSQL.
        async def insert_ev():
            async with db_session.AsyncSessionLocal() as s:
                return await EvidenceRepository.create(
                    s,
                    call_id="PG_CALL_B",
                    payload=EvidenceItemCreate(
                        call_id="PG_CALL_B",
                        provider="sarvam",
                        model="saaras:v4",
                        check_type="transcription",
                        status="completed",
                        is_final=True,
                        source_event_key="pg_conc_key_1",
                        details={"transcript": "PG Unicode नमस्ते", "nested": {"count": 2}},
                    ),
                    commit=True,
                )

        res1, res2 = await asyncio.gather(insert_ev(), insert_ev())
        assert res1[0].evidence_id == res2[0].evidence_id
        assert sorted([res1[1], res2[1]]) == [False, True]

        # Concurrent duplicate webhook delivery across independent sessions on PostgreSQL.
        wh_payload = {
            "id": "evt_pg_conc",
            "type": "deepfake.completed",
            "created_at": "2026-11-25T10:00:00Z",
            "data": {"reference": "PG_CALL_B", "operation_id": "op_pg_wh", "result": {"verdict": "real", "score": 0.03}},
        }

        async def send_wh():
            async with db_session.AsyncSessionLocal() as s:
                return await ingest_webhook_event(s, delivery_id="pg_deliv_conc", payload=wh_payload)

        w1, w2 = await asyncio.gather(send_wh(), send_wh())
        assert sorted([w1.duplicate, w2.duplicate]) == [False, True]

        # Webhook savepoint rollback keeps WebhookEvent row cleanly as `failed` on bad payload.
        async with db_session.AsyncSessionLocal() as s:
            fail_wh = await ingest_webhook_event(
                s,
                delivery_id="pg_deliv_fail",
                payload={
                    "id": "evt_pg_fail",
                    "type": "deepfake.completed",
                    "data": {"reference": "PG_CALL_B", "result": {"verdict": "real", "score": "NaN_bad"}},
                },
            )
            assert fail_wh.status == "failed"
            stored_fail = await s.scalar(select(WebhookEvent).where(WebhookEvent.delivery_id == "pg_deliv_fail"))
            assert stored_fail is not None and stored_fail.status == "failed"

        # TrustAssessment + FastAPI end-to-end transaction simulation on PostgreSQL.
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            ev_list = (await http_client.get("/api/v1/calls/sessions/PG_CALL_B/evidence")).json()["items"]
            ta = await http_client.post(
                "/api/v1/calls/sessions/PG_CALL_B/trust-assessments",
                json={
                    "trust_score": 0.9,
                    "risk_level": "low",
                    "recommended_action": "allow",
                    "summary": "All PG checks clean",
                    "evidence_ids": [ev_list[0]["evidence_id"]],
                    "is_final": True,
                    "model_version": "trust-v1",
                },
            )
            assert ta.status_code == 201
            tx = await http_client.post(
                "/api/v1/calls/sessions/PG_CALL_B/transactions/simulate",
                json={"action_type": "fund_transfer", "amount": "2000.00", "currency": "INR"},
            )
            assert tx.status_code == 200 and tx.json()["decision"] == "allow"
    finally:
        await db_session.close_db()
        assert db_session.engine.pool.checkedout() == 0
        db_session.set_database_url("sqlite+aiosqlite:///:memory:")
        await _drop_temp_pg_db(db_name)

import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db import session as db_session
from app.db.models import (
    CallSession,
    EvidenceItem,
    ProviderOperation,
    SpeakerProfile,
    TrustAssessment,
    TrustAssessmentEvidence,
    WebhookEvent,
    parse_utc_datetime,
    safe_parse_utc_datetime,
)
from app.main import app
from app.services.webhook_service import store_webhook_event


@pytest.mark.asyncio
async def test_sqlite_init_and_close_creates_tables_and_disposes(
    isolated_sqlite_url: str,
    tmp_path: Path,
):
    db_session.set_database_url(isolated_sqlite_url)
    await db_session.init_db()
    try:
        async with db_session.engine.connect() as conn:
            table_names = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
            fk_pragma = (await conn.execute(text("PRAGMA foreign_keys"))).scalar_one()
        assert fk_pragma == 1
        assert {
            "alembic_version",
            "webhook_events",
            "call_sessions",
            "speaker_profiles",
            "provider_operations",
            "evidence_items",
            "trust_assessments",
            "trust_assessment_evidence",
        }.issubset(table_names)

        async with db_session.AsyncSessionLocal() as session:
            session.add(CallSession(call_id="CALL_TEST_001", speaker_id="SPK_TEST_001"))
            await session.commit()

        async with db_session.AsyncSessionLocal() as session:
            stored = await session.scalar(
                select(CallSession).where(CallSession.call_id == "CALL_TEST_001")
            )
            assert stored is not None
            assert stored.speaker_id == "SPK_TEST_001"
            assert stored.checks_mode == "deepfake,verify"
            assert stored.status == "created"
    finally:
        await db_session.close_db()
        assert db_session.engine.pool.checkedout() == 0
        db_session.set_database_url("sqlite+aiosqlite:///:memory:")

    assert (tmp_path / "test_trustlayer.db").exists()


@pytest.mark.asyncio
async def test_get_db_yields_working_async_session(async_db):
    async for session in db_session.get_db():
        result = await session.execute(text("SELECT 1"))
        assert result.scalar_one() == 1
        break


@pytest.mark.asyncio
async def test_app_lifespan_initializes_and_closes_database(
    isolated_sqlite_url: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    monkeypatch.setenv("DATABASE_URL", isolated_sqlite_url)
    get_settings.cache_clear()
    db_session.set_database_url(isolated_sqlite_url)

    try:
        async with app.router.lifespan_context(app):
            async with db_session.AsyncSessionLocal() as session:
                val = (await session.execute(text("SELECT 1"))).scalar_one()
                assert val == 1
        assert db_session.engine.pool.checkedout() == 0
        assert (tmp_path / "test_trustlayer.db").exists()
    finally:
        await db_session.close_db()
        db_session.set_database_url("sqlite+aiosqlite:///:memory:")


@pytest.mark.asyncio
async def test_async_client_health_uses_isolated_database(async_client: httpx.AsyncClient):
    response = await async_client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"] == "connected"
    assert payload["detectif_configured"] is False


def test_set_database_url_normalizes_postgresql_for_asyncpg():
    try:
        engine = db_session.set_database_url("postgresql://trustlayer:secret@localhost:5432/trustlayer")
        assert engine.dialect.name == "postgresql"
        assert engine.dialect.driver == "asyncpg"
    finally:
        db_session.set_database_url("sqlite+aiosqlite:///:memory:")


@pytest.mark.asyncio
async def test_relationships_foreign_keys_and_same_call_constraints(async_db):
    async with async_db() as session:
        speaker = SpeakerProfile(
            speaker_id="SPK_1",
            display_name="Caller One",
            consent_confirmed=True,
            consent_recorded_at=datetime.now(timezone.utc),
            enrollment_status="enrolled",
            sample_count=1,
        )
        call_a = CallSession(call_id="CALL_A", speaker_id="SPK_1", checks_mode="deepfake,verify")
        call_b = CallSession(call_id="CALL_B", speaker_id=None, checks_mode="deepfake")
        session.add_all([speaker, call_a, call_b])
        await session.flush()

        op = ProviderOperation(
            call_id="CALL_A",
            speaker_id="SPK_1",
            provider="detectifai",
            operation_type="speaker_verification",
            request_id="req_1",
            operation_id="op_1",
            status="completed",
        )
        ev_a = EvidenceItem(
            evidence_id="ev_a1",
            call_id="CALL_A",
            speaker_id="SPK_1",
            provider="detectifai",
            model="aletheia",
            check_type="deepfake",
            status="completed",
            verdict="real",
            raw_score=0.05,
            score_type="synthetic_score",
            is_early=False,
            is_final=True,
            source_channel="websocket",
            source_event_key="str_a:deepfake:final",
        )
        ev_b = EvidenceItem(
            evidence_id="ev_b1",
            call_id="CALL_B",
            speaker_id=None,
            provider="detectifai",
            model="aletheia",
            check_type="deepfake",
            status="completed",
            is_final=True,
        )
        # Multiple NULL source_event_key values are allowed
        ev_a_null_key = EvidenceItem(
            evidence_id="ev_a2",
            call_id="CALL_A",
            provider="sarvam",
            model="saarika:v2",
            check_type="transcription",
            status="completed",
            source_event_key=None,
        )
        ta_a = TrustAssessment(
            assessment_id="ta_a1",
            call_id="CALL_A",
            trust_score=0.91,
            risk_level="low",
            recommended_action="allow",
            summary="Legitimate caller",
            reasons=["aletheia:real"],
            is_final=True,
            model_version="trust-v1",
        )
        session.add_all([op, ev_a, ev_b, ev_a_null_key, ta_a])
        await session.flush()
        op_id = op.id

        session.add(TrustAssessmentEvidence(assessment_id="ta_a1", evidence_id="ev_a1", call_id="CALL_A"))
        await session.commit()

        async with async_db() as read_session:
            loaded_ta = await read_session.get(TrustAssessment, "ta_a1")
            assert loaded_ta is not None
            assert loaded_ta.evidence_ids == ["ev_a1"]

        # Cross-call evidence association must be rejected by composite FK
        session.add(TrustAssessmentEvidence(assessment_id="ta_a1", evidence_id="ev_b1", call_id="CALL_A"))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        # Duplicate non-null source_event_key per (call_id, provider, check_type) must fail
        session.add(
            EvidenceItem(
                evidence_id="ev_a_dup",
                call_id="CALL_A",
                provider="detectifai",
                model="aletheia",
                check_type="deepfake",
                status="completed",
                source_event_key="str_a:deepfake:final",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        # Check constraint on trust_score bounds
        session.add(
            TrustAssessment(
                assessment_id="ta_bad_score",
                call_id="CALL_A",
                trust_score=1.5,
                risk_level="low",
                recommended_action="allow",
                summary="Invalid score",
                model_version="trust-v1",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        # Deleting CallSession cascades to EvidenceItem and TrustAssessment
        target_call = await session.get(CallSession, "CALL_A")
        assert target_call is not None
        await session.delete(target_call)
        await session.commit()

        assert await session.get(EvidenceItem, "ev_a1") is None
        assert await session.get(TrustAssessment, "ta_a1") is None
        # ProviderOperation uses SET NULL on call_id
        async with async_db() as check_session:
            persisted_op = await check_session.get(ProviderOperation, op_id)
            assert persisted_op is not None
            assert persisted_op.call_id is None


@pytest.mark.asyncio
async def test_webhook_service_persists_utc_datetimes(async_db):
    async with async_db() as session:
        session.add(CallSession(call_id="CALL_WH_1", speaker_id="SPK_1"))
        await session.commit()

        dup1 = await store_webhook_event(
            session,
            delivery_id="msg_wh_1",
            payload={
                "id": "evt_wh_1",
                "type": "stream.deepfake.updated",
                "created_at": "2026-11-11T09:31:24.512Z",
                "data": {"reference": "CALL_WH_1", "stream_id": "str_wh_1", "sequence": 3},
            },
        )
        assert dup1 is False

        call_row = await session.get(CallSession, "CALL_WH_1")
        wh_row = await session.scalar(select(WebhookEvent).where(WebhookEvent.delivery_id == "msg_wh_1"))
        assert call_row is not None and wh_row is not None
        assert call_row.last_deepfake_sequence == 3
        assert call_row.last_provider_event_at == datetime(2026, 11, 11, 9, 31, 24, 512000, tzinfo=timezone.utc)
        assert wh_row.event_created_at == datetime(2026, 11, 11, 9, 31, 24, 512000, tzinfo=timezone.utc)


def test_create_call_session_modes_and_consent_persistence(client: TestClient):
    # Backward-compatible verify call
    r1 = client.post("/api/v1/calls/sessions", json={"call_id": "CALL_HTTP_1", "speaker_id": "SPK_HTTP_1"})
    assert r1.status_code == 200
    assert r1.json() == {
        "call_id": "CALL_HTTP_1",
        "speaker_id": "SPK_HTTP_1",
        "checks_mode": "deepfake,verify",
        "status": "created",
    }

    # Deepfake-only call with nullable speaker_id
    r2 = client.post("/api/v1/calls/sessions", json={"call_id": "CALL_HTTP_2", "checks_mode": "deepfake"})
    assert r2.status_code == 200
    assert r2.json()["speaker_id"] is None
    assert r2.json()["checks_mode"] == "deepfake"

    # Enrollment requires consent_confirmed=true
    r3_fail = client.post(
        "/api/v1/calls/sessions",
        json={"call_id": "CALL_HTTP_3", "speaker_id": "SPK_HTTP_2", "checks_mode": "deepfake,enroll"},
    )
    assert r3_fail.status_code == 422

    r3_ok = client.post(
        "/api/v1/calls/sessions",
        json={
            "call_id": "CALL_HTTP_3",
            "speaker_id": "SPK_HTTP_2",
            "checks_mode": "deepfake,enroll",
            "consent_confirmed": True,
            "display_name": "Speaker Two",
        },
    )
    assert r3_ok.status_code == 200
    assert r3_ok.json()["checks_mode"] == "deepfake,enroll"


@pytest.mark.asyncio
async def test_utc_datetime_strict_bind_and_legacy_safe_parser(async_db):
    # Direct parser checks
    assert parse_utc_datetime(None) is None
    naive = datetime(2026, 11, 25, 10, 0, 0)
    assert parse_utc_datetime(naive) == datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc)
    offset_aware = datetime(2026, 11, 25, 15, 30, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert parse_utc_datetime(offset_aware) == datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc)
    assert parse_utc_datetime("2026-11-25T10:00:00Z") == datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc)
    assert parse_utc_datetime("2026-11-25T15:30:00+05:30") == datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc)

    for bad_str in ("not-a-timestamp", "", "   "):
        with pytest.raises(ValueError):
            parse_utc_datetime(bad_str)
        assert safe_parse_utc_datetime(bad_str) is None

    for unsupported in (12345, {"ts": "2026-11-25"}, date(2026, 11, 25)):
        with pytest.raises(TypeError):
            parse_utc_datetime(unsupported)  # type: ignore[arg-type]
        assert safe_parse_utc_datetime(unsupported) is None  # type: ignore[arg-type]

    # ORM DB round-trip checks
    async with async_db() as session:
        session.add(CallSession(call_id="CALL_TS_1", checks_mode="deepfake"))
        session.add(
            EvidenceItem(
                evidence_id="ev_ts_none",
                call_id="CALL_TS_1",
                provider="detectifai",
                model="aletheia",
                check_type="deepfake",
                status="completed",
                observed_at=None,
            )
        )
        session.add(
            EvidenceItem(
                evidence_id="ev_ts_iso",
                call_id="CALL_TS_1",
                provider="detectifai",
                model="aletheia",
                check_type="deepfake",
                status="completed",
                observed_at="2026-11-25T15:30:00+05:30",  # type: ignore[arg-type]
            )
        )
        session.add(
            EvidenceItem(
                evidence_id="ev_ts_naive",
                call_id="CALL_TS_1",
                provider="detectifai",
                model="aletheia",
                check_type="deepfake",
                status="completed",
                observed_at=naive,
            )
        )
        await session.commit()

        async with async_db() as read_session:
            none_row = await read_session.get(EvidenceItem, "ev_ts_none")
            iso_row = await read_session.get(EvidenceItem, "ev_ts_iso")
            naive_row = await read_session.get(EvidenceItem, "ev_ts_naive")
            assert none_row is not None and none_row.observed_at is None
            assert iso_row is not None and iso_row.observed_at == datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc)
            assert naive_row is not None and naive_row.observed_at == datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc)

        # Malformed string must raise on bind instead of silently becoming None
        session.add(
            EvidenceItem(
                evidence_id="ev_ts_bad",
                call_id="CALL_TS_1",
                provider="detectifai",
                model="aletheia",
                check_type="deepfake",
                status="completed",
                observed_at="invalid-timestamp",  # type: ignore[arg-type]
            )
        )
        with pytest.raises(StatementError):
            await session.commit()
        await session.rollback()

        # Unsupported type must raise on bind
        session.add(
            EvidenceItem(
                evidence_id="ev_ts_type",
                call_id="CALL_TS_1",
                provider="detectifai",
                model="aletheia",
                check_type="deepfake",
                status="completed",
                observed_at=1700000000,  # type: ignore[arg-type]
            )
        )
        with pytest.raises(StatementError):
            await session.commit()
        await session.rollback()


@pytest.mark.asyncio
async def test_trust_assessment_evidence_ids_ordering_is_deterministic(async_db):
    base_time = datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc)
    async with async_db() as session:
        session.add(CallSession(call_id="CALL_ORDER", checks_mode="deepfake"))
        session.add_all(
            [
                EvidenceItem(
                    evidence_id="ev_z",
                    call_id="CALL_ORDER",
                    provider="detectifai",
                    model="aletheia",
                    check_type="deepfake",
                    status="completed",
                    created_at=base_time,
                ),
                EvidenceItem(
                    evidence_id="ev_a",
                    call_id="CALL_ORDER",
                    provider="sarvam",
                    model="saarika:v2",
                    check_type="transcription",
                    status="completed",
                    created_at=base_time,
                ),
                EvidenceItem(
                    evidence_id="ev_m",
                    call_id="CALL_ORDER",
                    provider="gemini",
                    model="gemini-2.5",
                    check_type="context",
                    status="completed",
                    created_at=base_time + timedelta(seconds=5),
                ),
            ]
        )
        session.add(
            TrustAssessment(
                assessment_id="ta_order",
                call_id="CALL_ORDER",
                trust_score=0.8,
                risk_level="low",
                recommended_action="allow",
                summary="Deterministic order check",
                model_version="trust-v1",
            )
        )
        await session.flush()

        # Insert links out of chronological/ID order
        session.add_all(
            [
                TrustAssessmentEvidence(
                    assessment_id="ta_order",
                    evidence_id="ev_m",
                    call_id="CALL_ORDER",
                    created_at=base_time + timedelta(seconds=5),
                ),
                TrustAssessmentEvidence(
                    assessment_id="ta_order",
                    evidence_id="ev_z",
                    call_id="CALL_ORDER",
                    created_at=base_time,
                ),
                TrustAssessmentEvidence(
                    assessment_id="ta_order",
                    evidence_id="ev_a",
                    call_id="CALL_ORDER",
                    created_at=base_time,
                ),
            ]
        )
        await session.commit()

    async with async_db() as read_session:
        loaded = await read_session.get(TrustAssessment, "ta_order")
        assert loaded is not None
        assert loaded.evidence_ids == ["ev_a", "ev_z", "ev_m"]

        loaded_with_items = await read_session.scalar(
            select(TrustAssessment)
            .options(selectinload(TrustAssessment.evidence_items))
            .where(TrustAssessment.assessment_id == "ta_order")
        )
        assert loaded_with_items is not None
        assert [item.evidence_id for item in loaded_with_items.evidence_items] == ["ev_a", "ev_z", "ev_m"]


@pytest.mark.asyncio
async def test_deleted_speaker_profile_resets_to_pending_on_new_enroll_session(
    async_client: httpx.AsyncClient,
    async_db,
):
    async with async_db() as session:
        session.add(
            SpeakerProfile(
                speaker_id="SPK_DELETED",
                display_name="Old Name",
                consent_confirmed=False,
                enrollment_status="deleted",
                sample_count=3,
            )
        )
        await session.commit()

    response = await async_client.post(
        "/api/v1/calls/sessions",
        json={
            "call_id": "CALL_REENROLL_1",
            "speaker_id": "SPK_DELETED",
            "checks_mode": "deepfake,enroll",
            "consent_confirmed": True,
            "display_name": "Updated Name",
        },
    )
    assert response.status_code == 200
    assert response.json()["checks_mode"] == "deepfake,enroll"

    async with async_db() as read_session:
        profile = await read_session.get(SpeakerProfile, "SPK_DELETED")
        call_row = await read_session.get(CallSession, "CALL_REENROLL_1")
        assert profile is not None and call_row is not None
        assert profile.enrollment_status == "pending"
        assert profile.sample_count == 0
        assert profile.consent_confirmed is True
        assert profile.consent_recorded_at is not None
        assert profile.display_name == "Updated Name"
        assert call_row.consent_confirmed is True


@pytest.mark.asyncio
async def test_concurrent_duplicate_call_session_returns_409_and_rolls_back(
    async_client: httpx.AsyncClient,
    async_db,
    monkeypatch: pytest.MonkeyPatch,
):
    # 1. Real concurrent POST requests for identical call_id
    responses = await asyncio.gather(
        async_client.post(
            "/api/v1/calls/sessions",
            json={"call_id": "CALL_CONCURRENT_1", "speaker_id": "SPK_1"},
        ),
        async_client.post(
            "/api/v1/calls/sessions",
            json={"call_id": "CALL_CONCURRENT_1", "speaker_id": "SPK_1"},
        ),
    )
    statuses = sorted(resp.status_code for resp in responses)
    assert statuses == [200, 409]

    # 2. Explicit commit-time IntegrityError path after passing pre-check
    original_get = AsyncSession.get
    skipped_once = False

    async def get_bypass_once(self, entity, ident, **kwargs):
        nonlocal skipped_once
        if entity is CallSession and ident == "CALL_CONCURRENT_1" and not skipped_once:
            skipped_once = True
            return None
        return await original_get(self, entity, ident, **kwargs)

    monkeypatch.setattr(AsyncSession, "get", get_bypass_once)
    rollback_calls = 0
    original_rollback = AsyncSession.rollback

    async def tracked_rollback(self):
        nonlocal rollback_calls
        rollback_calls += 1
        return await original_rollback(self)

    monkeypatch.setattr(AsyncSession, "rollback", tracked_rollback)

    race_response = await async_client.post(
        "/api/v1/calls/sessions",
        json={"call_id": "CALL_CONCURRENT_1", "speaker_id": "SPK_1"},
    )
    assert race_response.status_code == 409
    assert race_response.json()["detail"] == "call_id already exists"
    assert rollback_calls >= 1

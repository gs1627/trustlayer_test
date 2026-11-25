import asyncio
import base64
import hashlib
import hmac
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services import events as event_service
from app.services.evidence_mapper import map_aletheia_rest_result
from app.services.evidence_repository import EvidenceRepository


def _sign_webhook(secret: str, webhook_id: str, timestamp: str, raw_body: bytes) -> dict[str, str]:
    key = base64.b64decode(secret.removeprefix("whsec_"))
    signed = f"{webhook_id}.{timestamp}.".encode("utf-8") + raw_body
    sig = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode("ascii")
    return {
        "webhook-id": webhook_id,
        "webhook-timestamp": timestamp,
        "webhook-signature": f"v1,{sig}",
    }


def test_call_session_list_detail_and_idempotent_termination(client: TestClient):
    assert client.post("/api/v1/calls/sessions", json={"call_id": "CALL_01", "speaker_id": "SPK_A"}).status_code == 200
    assert (
        client.post(
            "/api/v1/calls/sessions",
            json={"call_id": "CALL_02", "checks_mode": "deepfake"},
        ).status_code
        == 200
    )
    assert client.post("/api/v1/calls/sessions", json={"call_id": "CALL_03", "speaker_id": "SPK_A"}).status_code == 200

    # List with filter and pagination.
    filtered = client.get("/api/v1/calls/sessions", params={"speaker_id": "SPK_A", "limit": 1, "offset": 0})
    assert filtered.status_code == 200
    f_body = filtered.json()
    assert f_body["total"] == 2
    assert len(f_body["items"]) == 1

    # End CALL_01 with reason, then repeat idempotently with different/omitted body.
    end_1 = client.post("/api/v1/calls/sessions/CALL_01/end", json={"reason": "caller_hangup"})
    assert end_1.status_code == 200
    ended_payload_1 = end_1.json()
    assert ended_payload_1["status"] == "ended"
    assert ended_payload_1["ended_reason"] == "caller_hangup"
    assert ended_payload_1["ended_at"] is not None

    end_2 = client.post("/api/v1/calls/sessions/CALL_01/end", json={"reason": "different_reason"})
    assert end_2.status_code == 200
    assert end_2.json()["ended_at"] == ended_payload_1["ended_at"]
    assert end_2.json()["ended_reason"] == "caller_hangup"

    end_3 = client.post("/api/v1/calls/sessions/CALL_01/end")
    assert end_3.status_code == 200
    assert end_3.json()["ended_at"] == ended_payload_1["ended_at"]

    by_status = client.get("/api/v1/calls/sessions", params={"status": "ended"})
    assert by_status.status_code == 200
    assert [row["call_id"] for row in by_status.json()["items"]] == ["CALL_01"]

    # Detail check on non-existent call returns 404 ErrorResponse envelope.
    missing = client.get("/api/v1/calls/sessions/CALL_UNKNOWN")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "call_session_not_found"


@pytest.mark.asyncio
async def test_evidence_crud_filtering_dedup_provisional_protection_and_concurrency(
    async_client: httpx.AsyncClient,
    async_db,
):
    bus = event_service.reset_event_publisher()
    async with bus.subscribe() as queue:
        create_res = await async_client.post(
            "/api/v1/calls/sessions",
            json={"call_id": "CALL_EV_1", "speaker_id": "SPK_EV_1"},
        )
        assert create_res.status_code == 200

        await async_client.post(
            "/api/v1/calls/sessions",
            json={"call_id": "CALL_EV_OTHER", "checks_mode": "deepfake"},
        )

        # Submit Member 3 Sarvam and Gemini evidence directly.
        sarvam_res = await async_client.post(
            "/api/v1/calls/sessions/CALL_EV_1/evidence",
            json={
                "call_id": "CALL_EV_1",
                "speaker_id": "SPK_EV_1",
                "provider": "sarvam",
                "model": "saaras:v4",
                "check_type": "transcription",
                "status": "completed",
                "raw_score": 0.94,
                "score_type": "language_probability",
                "is_final": True,
                "source_channel": "internal",
                "source_event_key": "srv:CALL_EV_1:turn_1",
                "details": {"transcript": "Open vault access", "api_key": "secret-leak"},
            },
        )
        assert sarvam_res.status_code == 201
        ev_srv = sarvam_res.json()
        assert ev_srv["evidence_id"].startswith("ev_")
        assert ev_srv["details"]["api_key"] == "[REDACTED]"

        gemini_res = await async_client.post(
            "/api/v1/calls/sessions/CALL_EV_1/evidence",
            json={
                "call_id": "CALL_EV_1",
                "provider": "gemini",
                "model": "gemini-2.5-flash",
                "check_type": "context",
                "status": "completed",
                "verdict": "high_risk_pretext",
                "raw_score": 0.9,
                "score_type": "contextual_risk_score",
                "is_final": True,
                "source_channel": "internal",
                "source_event_key": "gem:CALL_EV_1:ctx_1",
                "details": {"cues": ["authority_impersonation"]},
            },
        )
        assert gemini_res.status_code == 201

        # Repeating a final event with an early/provisional flag under the same key
        # MUST return the original final record untouched (HTTP 200) and NOT overwrite it.
        downgrade_attempt = await async_client.post(
            "/api/v1/calls/sessions/CALL_EV_1/evidence",
            json={
                "call_id": "CALL_EV_1",
                "provider": "gemini",
                "model": "gemini-2.5-flash",
                "check_type": "context",
                "status": "pending",
                "verdict": "safe",
                "is_early": True,
                "is_final": False,
                "source_channel": "internal",
                "source_event_key": "gem:CALL_EV_1:ctx_1",
            },
        )
        assert downgrade_attempt.status_code == 200
        assert downgrade_attempt.json()["evidence_id"] == gemini_res.json()["evidence_id"]
        assert downgrade_attempt.json()["is_final"] is True
        assert downgrade_attempt.json()["verdict"] == "high_risk_pretext"

        # Separate provisional DetectifAI event preserves is_early/is_final independently.
        aletheia_early = await async_client.post(
            "/api/v1/calls/sessions/CALL_EV_1/evidence",
            json={
                "call_id": "CALL_EV_1",
                "provider": "detectifai",
                "model": "aletheia",
                "check_type": "deepfake",
                "status": "pending",
                "verdict": "real",
                "raw_score": 0.04,
                "score_type": "synthetic_score",
                "is_early": False,
                "is_final": False,
                "source_channel": "websocket",
                "source_event_key": "ws:str1:deepfake:seq_1",
                "sequence": 1,
            },
        )
        assert aletheia_early.status_code == 201

        # Concurrent duplicate ingestion via HTTP creates only 1 row and both return same ID.
        concurrent_payload = {
            "call_id": "CALL_EV_1",
            "provider": "detectifai",
            "model": "eidos",
            "check_type": "speaker_verification",
            "status": "completed",
            "verdict": "match",
            "raw_score": 0.81,
            "score_type": "cosine_similarity",
            "is_final": True,
            "source_channel": "rest",
            "source_event_key": "rest:op_concurrent_eidos",
        }
        r_a, r_b = await asyncio.gather(
            async_client.post("/api/v1/calls/sessions/CALL_EV_1/evidence", json=concurrent_payload),
            async_client.post("/api/v1/calls/sessions/CALL_EV_1/evidence", json=concurrent_payload),
        )
        assert sorted([r_a.status_code, r_b.status_code]) == [200, 201]
        assert r_a.json()["evidence_id"] == r_b.json()["evidence_id"]

        # Filtering and deterministic pagination.
        all_ev = await async_client.get("/api/v1/calls/sessions/CALL_EV_1/evidence", params={"limit": 2, "offset": 0})
        next_ev = await async_client.get("/api/v1/calls/sessions/CALL_EV_1/evidence", params={"limit": 2, "offset": 2})
        assert all_ev.status_code == 200 and next_ev.status_code == 200
        assert all_ev.json()["total"] == 4
        ids_page_1 = [row["evidence_id"] for row in all_ev.json()["items"]]
        ids_page_2 = [row["evidence_id"] for row in next_ev.json()["items"]]
        assert len(set(ids_page_1) & set(ids_page_2)) == 0

        only_final = await async_client.get("/api/v1/calls/sessions/CALL_EV_1/evidence", params={"is_final": True})
        assert only_final.json()["total"] == 3

        only_gemini = await async_client.get(
            "/api/v1/calls/sessions/CALL_EV_1/evidence",
            params={"provider": "gemini", "check_type": "context"},
        )
        assert only_gemini.json()["total"] == 1

        # Cross-call rejection in API and repository.
        cross_api = await async_client.post(
            "/api/v1/calls/sessions/CALL_EV_OTHER/evidence",
            json={**concurrent_payload, "source_event_key": "other:1"},
        )
        assert cross_api.status_code == 422
        assert cross_api.json()["error"]["code"] == "cross_call_mismatch"

        async with async_db() as session:
            with pytest.raises(Exception) as exc_info:
                await EvidenceRepository.get_by_id(
                    session,
                    evidence_id=ev_srv["evidence_id"],
                    call_id="CALL_EV_OTHER",
                )
            assert getattr(exc_info.value, "code", None) == "cross_call_evidence_not_allowed"

        # Forged backend-generated fields fail 422.
        forged = await async_client.post(
            "/api/v1/calls/sessions/CALL_EV_1/evidence",
            json={**concurrent_payload, "evidence_id": "forged_ev_1", "source_event_key": "other:2"},
        )
        assert forged.status_code == 422

        # Collect emitted domain events: 2 session creations + 4 new evidence creations (not 5 or 6!).
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        assert [e.event_type for e in events].count("call.status_changed") == 2
        assert [e.event_type for e in events].count("evidence.added") == 4


@pytest.mark.asyncio
async def test_trust_assessments_creation_validation_history_and_detail_view(
    async_client: httpx.AsyncClient,
):
    bus = event_service.reset_event_publisher()
    async with bus.subscribe(call_id="CALL_TA_1") as queue:
        await async_client.post("/api/v1/calls/sessions", json={"call_id": "CALL_TA_1", "speaker_id": "SPK_TA_1"})
        await async_client.post("/api/v1/calls/sessions", json={"call_id": "CALL_TA_2", "checks_mode": "deepfake"})

        # Missing latest assessment returns 404.
        latest_missing = await async_client.get("/api/v1/calls/sessions/CALL_TA_1/trust-assessments/latest")
        assert latest_missing.status_code == 404
        assert latest_missing.json()["error"]["code"] == "trust_assessment_not_found"

        ev1 = (
            await async_client.post(
                "/api/v1/calls/sessions/CALL_TA_1/evidence",
                json={
                    "call_id": "CALL_TA_1",
                    "provider": "detectifai",
                    "model": "aletheia",
                    "check_type": "deepfake",
                    "status": "pending",
                    "is_early": True,
                    "is_final": False,
                    "source_event_key": "ev_ta_1",
                },
            )
        ).json()["evidence_id"]

        await asyncio.sleep(0.01)
        ev2 = (
            await async_client.post(
                "/api/v1/calls/sessions/CALL_TA_1/evidence",
                json={
                    "call_id": "CALL_TA_1",
                    "provider": "gemini",
                    "model": "gemini-2.5-flash",
                    "check_type": "context",
                    "status": "completed",
                    "is_final": True,
                    "source_event_key": "ev_ta_2",
                },
            )
        ).json()["evidence_id"]

        ev_other_call = (
            await async_client.post(
                "/api/v1/calls/sessions/CALL_TA_2/evidence",
                json={
                    "call_id": "CALL_TA_2",
                    "provider": "detectifai",
                    "model": "aletheia",
                    "check_type": "deepfake",
                    "status": "completed",
                    "is_final": True,
                    "source_event_key": "ev_ta_other",
                },
            )
        ).json()["evidence_id"]

        # Reject missing evidence ID.
        missing_ev_res = await async_client.post(
            "/api/v1/calls/sessions/CALL_TA_1/trust-assessments",
            json={
                "trust_score": 0.5,
                "risk_level": "medium",
                "recommended_action": "hold",
                "summary": "References unknown evidence",
                "evidence_ids": [ev1, "ev_does_not_exist"],
                "model_version": "trust-v1",
            },
        )
        assert missing_ev_res.status_code == 422
        assert missing_ev_res.json()["error"]["code"] == "evidence_not_found"

        # Reject evidence belonging to another call.
        cross_ev_res = await async_client.post(
            "/api/v1/calls/sessions/CALL_TA_1/trust-assessments",
            json={
                "trust_score": 0.5,
                "risk_level": "medium",
                "recommended_action": "hold",
                "summary": "References another call",
                "evidence_ids": [ev1, ev_other_call],
                "model_version": "trust-v1",
            },
        )
        assert cross_ev_res.status_code == 422
        assert cross_ev_res.json()["error"]["code"] == "cross_call_evidence_not_allowed"

        # Create initial provisional snapshot passing evidence_ids reversed to verify deterministic order.
        ta_1 = await async_client.post(
            "/api/v1/calls/sessions/CALL_TA_1/trust-assessments",
            json={
                "trust_score": 0.62,
                "risk_level": "medium",
                "recommended_action": "step_up_verify",
                "summary": "Initial provisional check",
                "reasons": ["provisional_evidence"],
                "evidence_ids": [ev2, ev1],
                "is_final": False,
                "model_version": "trust-v1",
            },
        )
        assert ta_1.status_code == 201
        ta_1_body = ta_1.json()
        assert ta_1_body["assessment_id"].startswith("ta_")
        assert ta_1_body["evidence_ids"] == [ev1, ev2]

        await asyncio.sleep(0.01)
        ta_2 = await async_client.post(
            "/api/v1/calls/sessions/CALL_TA_1/trust-assessments",
            json={
                "trust_score": 0.19,
                "risk_level": "critical",
                "recommended_action": "block",
                "summary": "Final risk elevated",
                "reasons": ["context_risk"],
                "evidence_ids": [ev1, ev2],
                "is_final": True,
                "model_version": "trust-v1",
            },
        )
        assert ta_2.status_code == 201
        ta_2_body = ta_2.json()

        # Latest and immutable paginated history.
        latest_res = await async_client.get("/api/v1/calls/sessions/CALL_TA_1/trust-assessments/latest")
        assert latest_res.status_code == 200
        assert latest_res.json()["assessment_id"] == ta_2_body["assessment_id"]

        hist_res = await async_client.get(
            "/api/v1/calls/sessions/CALL_TA_1/trust-assessments",
            params={"limit": 1, "offset": 1},
        )
        assert hist_res.status_code == 200
        assert hist_res.json()["total"] == 2
        assert hist_res.json()["items"][0]["assessment_id"] == ta_1_body["assessment_id"]

        # Call detail endpoint includes evidence counts and latest trust assessment.
        detail_res = await async_client.get("/api/v1/calls/sessions/CALL_TA_1")
        assert detail_res.status_code == 200
        detail_body = detail_res.json()
        assert detail_body["evidence_summary"]["total"] == 2
        assert detail_body["evidence_summary"]["final_count"] == 1
        assert detail_body["evidence_summary"]["provisional_count"] == 1
        assert detail_body["latest_trust_assessment"]["assessment_id"] == ta_2_body["assessment_id"]

        # Verify trust.updated events published for CALL_TA_1 only.
        ta_events = []
        while not queue.empty():
            ta_events.append(queue.get_nowait())
        assert [e.event_type for e in ta_events].count("trust.updated") == 2


def test_signed_webhook_persists_normalized_evidence_and_deduplicates(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    secret = "whsec_" + base64.b64encode(b"webhook-secret-p3").decode("ascii")
    monkeypatch.setenv("DETECTIF_WEBHOOK_SECRET", secret)
    get_settings.cache_clear()

    assert client.post("/api/v1/calls/sessions", json={"call_id": "CALL_WH_P3", "speaker_id": "SPK_WH_P3"}).status_code == 200

    ts = str(int(time.time()))
    upd_body = json.dumps(
        {
            "id": "evt_wh_upd_1",
            "type": "stream.deepfake.updated",
            "created_at": "2026-11-25T10:00:02Z",
            "data": {
                "stream_id": "str_wh_p3",
                "reference": "CALL_WH_P3",
                "sequence": 1,
                "early": True,
                "verdict": "real",
                "score": 0.03,
            },
        }
    ).encode("utf-8")

    r_upd = client.post(
        "/api/v1/webhooks/detectifai",
        content=upd_body,
        headers=_sign_webhook(secret, "msg_wh_p3_1", ts, upd_body),
    )
    assert r_upd.status_code == 202 and r_upd.json()["duplicate"] is False

    # Re-delivery of same webhook returns duplicate=True and creates no second evidence item.
    r_upd_dup = client.post(
        "/api/v1/webhooks/detectifai",
        content=upd_body,
        headers=_sign_webhook(secret, "msg_wh_p3_1", ts, upd_body),
    )
    assert r_upd_dup.status_code == 202 and r_upd_dup.json()["duplicate"] is True

    # stream.completed webhook appends final deepfake + speaker_verification evidence.
    comp_body = json.dumps(
        {
            "id": "evt_wh_comp_1",
            "type": "stream.completed",
            "created_at": "2026-11-25T10:00:15Z",
            "data": {
                "stream_id": "str_wh_p3",
                "reference": "CALL_WH_P3",
                "speaker_id": "SPK_WH_P3",
                "results": {
                    "deepfake": {"verdict": "real", "score": 0.04},
                    "verify": {"status": "match", "similarity": 0.89},
                },
            },
        }
    ).encode("utf-8")
    r_comp = client.post(
        "/api/v1/webhooks/detectifai",
        content=comp_body,
        headers=_sign_webhook(secret, "msg_wh_p3_2", ts, comp_body),
    )
    assert r_comp.status_code == 202

    ev_list = client.get("/api/v1/calls/sessions/CALL_WH_P3/evidence")
    assert ev_list.status_code == 200
    assert ev_list.json()["total"] == 3

    detail = client.get("/api/v1/calls/sessions/CALL_WH_P3").json()
    assert detail["provider_stream_id"] == "str_wh_p3"
    assert detail["status"] == "completed"
    assert detail["evidence_summary"]["final_count"] == 2
    assert detail["evidence_summary"]["provisional_count"] == 1


def test_websocket_callback_normalizes_stream_messages_with_mocked_relay(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.api.routes import calls as calls_route

    async def fake_relay(
        *,
        browser_ws,
        call_id,
        speaker_id,
        checks_mode="deepfake,verify",
        consent_confirmed=False,
        on_provider_message=None,
    ):
        assert call_id == "CALL_WS_P3"
        assert speaker_id == "SPK_WS_P3"
        assert checks_mode == "deepfake,verify"
        assert on_provider_message is not None
        for msg in (
            {"type": "ready", "stream_id": "str_ws_p3"},
            {"type": "deepfake", "stream_id": "str_ws_p3", "sequence": 1, "early": False, "final": False, "verdict": "real", "score": 0.07},
            {"type": "completed", "stream_id": "str_ws_p3", "results": {"deepfake": {"verdict": "real", "score": 0.06}, "verify": {"decision": "match", "similarity": 0.91}}},
        ):
            await on_provider_message(msg)
            await browser_ws.send_json({"source": "detectifai", **msg})

    monkeypatch.setattr(calls_route, "relay_browser_audio_to_detectif", fake_relay)

    assert client.post("/api/v1/calls/sessions", json={"call_id": "CALL_WS_P3", "speaker_id": "SPK_WS_P3"}).status_code == 200
    with client.websocket_connect("/api/v1/calls/ws/CALL_WS_P3") as ws:
        msgs = [ws.receive_json() for _ in range(3)]
        assert [m["type"] for m in msgs] == ["ready", "deepfake", "completed"]

    ev_list = client.get("/api/v1/calls/sessions/CALL_WS_P3/evidence")
    assert ev_list.status_code == 200
    assert ev_list.json()["total"] == 3


def test_priority3_endpoints_enforce_authentication_and_production_fail_closed(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    endpoints = [
        ("GET", "/api/v1/calls/sessions", None),
        ("GET", "/api/v1/calls/sessions/CALL_AUTH", None),
        ("POST", "/api/v1/calls/sessions/CALL_AUTH/end", {}),
        ("GET", "/api/v1/calls/sessions/CALL_AUTH/evidence", None),
        (
            "POST",
            "/api/v1/calls/sessions/CALL_AUTH/evidence",
            {
                "call_id": "CALL_AUTH",
                "provider": "sarvam",
                "model": "saaras:v4",
                "check_type": "transcription",
                "status": "completed",
            },
        ),
        (
            "POST",
            "/api/v1/calls/sessions/CALL_AUTH/trust-assessments",
            {
                "trust_score": 0.5,
                "risk_level": "medium",
                "recommended_action": "hold",
                "summary": "Auth check",
                "model_version": "trust-v1",
            },
        ),
        ("GET", "/api/v1/calls/sessions/CALL_AUTH/trust-assessments/latest", None),
        ("GET", "/api/v1/calls/sessions/CALL_AUTH/trust-assessments", None),
    ]

    # 1. With BACKEND_ACCESS_TOKEN set: missing or wrong token returns 401.
    monkeypatch.setenv("BACKEND_ACCESS_TOKEN", "top-secret-token")
    get_settings.cache_clear()

    assert (
        client.post(
            "/api/v1/calls/sessions",
            json={"call_id": "CALL_AUTH", "checks_mode": "deepfake"},
            headers={"Authorization": "Bearer top-secret-token"},
        ).status_code
        == 200
    )

    for method, path, body in endpoints:
        unauth = client.request(method, path, json=body)
        assert unauth.status_code == 401
        wrong = client.request(method, path, json=body, headers={"Authorization": "Bearer wrong"})
        assert wrong.status_code == 401

    # Valid Bearer token succeeds.
    authed_list = client.get(
        "/api/v1/calls/sessions",
        headers={"Authorization": "Bearer top-secret-token"},
    )
    assert authed_list.status_code == 200

    # 2. Production mode without BACKEND_ACCESS_TOKEN fails closed with 503.
    monkeypatch.delenv("BACKEND_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    for method, path, body in endpoints:
        prod_resp = client.request(method, path, json=body)
        assert prod_resp.status_code == 503


def test_aletheia_rest_mapper_works_with_repository_pipeline(client: TestClient):
    # Sanity test for end-to-end provider JSON -> EvidenceItemCreate -> POST /evidence.
    assert client.post("/api/v1/calls/sessions", json={"call_id": "CALL_PIPE_1", "checks_mode": "deepfake"}).status_code == 200
    mapped = map_aletheia_rest_result(
        {"request_id": "req_pipe", "operation_id": "op_pipe", "result": {"verdict": "real", "score": 0.02}},
        call_id="CALL_PIPE_1",
    )
    res = client.post(
        "/api/v1/calls/sessions/CALL_PIPE_1/evidence",
        json=mapped.model_dump(mode="json"),
    )
    assert res.status_code == 201
    assert res.json()["provider_operation_id"] == "op_pipe"
    assert res.json()["is_final"] is True

import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.api.routes import calls as calls_route
from app.core.config import get_settings


def _sign_wh(secret: str, webhook_id: str, ts: int, body: bytes) -> dict[str, str]:
    key = base64.b64decode(secret.removeprefix("whsec_"))
    signed = f"{webhook_id}.{ts}.".encode("utf-8") + body
    sig = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode("ascii")
    return {
        "webhook-id": webhook_id,
        "webhook-timestamp": str(ts),
        "webhook-signature": f"v1,{sig}",
    }


def test_dashboard_events_websocket_multi_subscriber_and_disconnect_safety(client: TestClient):
    assert client.post("/api/v1/calls/sessions", json={"call_id": "CALL_DASH_1", "checks_mode": "deepfake"}).status_code == 200

    with (
        client.websocket_connect("/api/v1/calls/ws/CALL_DASH_1/events") as ws1,
        client.websocket_connect("/api/v1/calls/ws/CALL_DASH_1/events") as ws2,
    ):
        sub1 = ws1.receive_json()
        sub2 = ws2.receive_json()
        assert sub1["type"] == "subscribed" and sub2["type"] == "subscribed"

        # Publish evidence.added -> received by both active dashboard subscribers.
        ev_res = client.post(
            "/api/v1/calls/sessions/CALL_DASH_1/evidence",
            json={
                "call_id": "CALL_DASH_1",
                "provider": "sarvam",
                "model": "saaras:v4",
                "check_type": "transcription",
                "status": "completed",
                "is_final": True,
                "source_event_key": "dash_ev_1",
            },
        )
        assert ev_res.status_code == 201
        ev_id = ev_res.json()["evidence_id"]

        msg1 = ws1.receive_json()
        msg2 = ws2.receive_json()
        assert msg1["event_type"] == "evidence.added" and msg1["payload"]["evidence_id"] == ev_id
        assert msg2["event_type"] == "evidence.added" and msg2["payload"]["evidence_id"] == ev_id

    # After both subscribers disconnected, a third subscription reconnects cleanly.
    with client.websocket_connect("/api/v1/calls/ws/CALL_DASH_1/events") as ws3:
        assert ws3.receive_json()["type"] == "subscribed"
        client.post(
            "/api/v1/calls/sessions/CALL_DASH_1/trust-assessments",
            json={
                "trust_score": 0.85,
                "risk_level": "low",
                "recommended_action": "allow",
                "summary": "Safe call",
                "evidence_ids": [ev_id],
                "is_final": True,
                "model_version": "trust-v1",
            },
        )
        ta_msg = ws3.receive_json()
        assert ta_msg["event_type"] == "trust.updated"

        client.post("/api/v1/calls/sessions/CALL_DASH_1/end", json={"reason": "done"})
        end_msg = ws3.receive_json()
        assert end_msg["event_type"] == "call.status_changed"
        assert end_msg["payload"]["status"] == "ended"


def test_full_end_to_end_trustlayer_workflow_mocked_providers(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    wh_secret = "whsec_" + base64.b64encode(b"e2e-webhook-secret").decode()
    monkeypatch.setenv("BACKEND_ACCESS_TOKEN", "e2e-shared-svc-key")
    monkeypatch.setenv("JWT_SECRET_KEY", "e2e-jwt-signing-secret-32-bytes-long!")
    monkeypatch.setenv("DETECTIF_WEBHOOK_SECRET", wh_secret)
    get_settings.cache_clear()

    # Mint JWTs for Member 2 user/operator and Member 3 AI service.
    user_token = client.post(
        "/api/v1/auth/token",
        json={"subject": "cust_user_1", "role": "user"},
        headers={"Authorization": "Bearer e2e-shared-svc-key"},
    ).json()["access_token"]
    service_token = client.post(
        "/api/v1/auth/token",
        json={"subject": "member3_ai", "role": "service"},
        headers={"Authorization": "Bearer e2e-shared-svc-key"},
    ).json()["access_token"]

    user_hdr = {"Authorization": f"Bearer {user_token}"}
    svc_hdr = {"Authorization": f"Bearer {service_token}"}

    # 1. Create call session.
    create_res = client.post(
        "/api/v1/calls/sessions",
        json={"call_id": "CALL_E2E_001", "speaker_id": "SPK_E2E_001", "checks_mode": "deepfake,verify"},
        headers=user_hdr,
    )
    assert create_res.status_code == 200

    # 2. Mock browser audio relay sending live DetectifAI WS events.
    async def fake_relay(
        *,
        browser_ws,
        call_id,
        speaker_id=None,
        checks_mode="deepfake,verify",
        consent_confirmed=False,
        on_provider_message=None,
    ):
        assert call_id == "CALL_E2E_001"
        assert checks_mode == "deepfake,verify"
        for frame in (
            {"type": "ready", "stream_id": "str_e2e_1"},
            {
                "type": "deepfake",
                "stream_id": "str_e2e_1",
                "sequence": 1,
                "early": True,
                "final": False,
                "verdict": "real",
                "score": 0.05,
            },
            {
                "type": "completed",
                "stream_id": "str_e2e_1",
                "results": {
                    "deepfake": {"verdict": "real", "score": 0.03},
                    "verify": {"decision": "match", "similarity": 0.92},
                },
            },
        ):
            if on_provider_message:
                await on_provider_message(frame)
            await browser_ws.send_json({"source": "detectifai", **frame})

    monkeypatch.setattr(calls_route, "relay_browser_audio_to_detectif", fake_relay)

    # Open Dashboard events subscriber alongside audio relay WebSocket.
    with client.websocket_connect("/api/v1/calls/ws/CALL_E2E_001/events") as dash_ws:
        dash_ws.send_json({"type": "auth", "token": user_token})
        assert dash_ws.receive_json()["type"] == "subscribed"

        with client.websocket_connect("/api/v1/calls/ws/CALL_E2E_001") as audio_ws:
            audio_ws.send_json({"type": "auth", "token": user_token})
            relayed = [audio_ws.receive_json() for _ in range(3)]
            assert [m["type"] for m in relayed] == ["ready", "deepfake", "completed"]

        # 3. Signed webhook (stream.deepfake.updated out-of-order + duplicate) handled idempotently.
        ts = int(time.time())
        wh_body = json.dumps(
            {
                "id": "evt_e2e_wh_1",
                "type": "stream.deepfake.updated",
                "created_at": ts,
                "data": {
                    "stream_id": "str_e2e_1",
                    "reference": "CALL_E2E_001",
                    "sequence": 1,
                    "early": True,
                    "verdict": "real",
                    "score": 0.04,
                },
            }
        ).encode("utf-8")
        wh_hdrs = _sign_wh(wh_secret, "msg_e2e_1", ts, wh_body)
        assert client.post("/api/v1/webhooks/detectifai", content=wh_body, headers=wh_hdrs).status_code == 202
        dup = client.post("/api/v1/webhooks/detectifai", content=wh_body, headers=wh_hdrs)
        assert dup.status_code == 202 and dup.json()["duplicate"] is True

        # 4. Member 3 submits Sarvam + Gemini evidence cleanly.
        srv_res = client.post(
            "/api/v1/calls/sessions/CALL_E2E_001/evidence",
            json={
                "call_id": "CALL_E2E_001",
                "speaker_id": "SPK_E2E_001",
                "provider": "sarvam",
                "model": "saaras:v4",
                "check_type": "transcription",
                "status": "completed",
                "raw_score": 0.98,
                "score_type": "language_probability",
                "is_final": True,
                "source_channel": "internal",
                "source_event_key": "e2e:sarvam:1",
                "details": {"transcript": "Check my balance please", "language": "en-IN"},
            },
            headers=svc_hdr,
        )
        assert srv_res.status_code == 201
        ev_srv_id = srv_res.json()["evidence_id"]

        gem_res = client.post(
            "/api/v1/calls/sessions/CALL_E2E_001/evidence",
            json={
                "call_id": "CALL_E2E_001",
                "speaker_id": "SPK_E2E_001",
                "provider": "gemini",
                "model": "gemini-2.5-flash",
                "check_type": "context",
                "status": "completed",
                "verdict": "routine",
                "is_final": True,
                "source_channel": "internal",
                "source_event_key": "e2e:gemini:1",
                "details": {"risk_label": "routine", "reasoning_summary": "Standard customer inquiry"},
            },
            headers=svc_hdr,
        )
        assert gem_res.status_code == 201
        ev_gem_id = gem_res.json()["evidence_id"]

        # 5. Collect all evidence IDs and persist immutable TrustAssessment.
        all_ev = client.get("/api/v1/calls/sessions/CALL_E2E_001/evidence", headers=user_hdr).json()["items"]
        assert len(all_ev) == 6  # 3 from WS + 1 webhook update + Sarvam + Gemini
        ta_res = client.post(
            "/api/v1/calls/sessions/CALL_E2E_001/trust-assessments",
            json={
                "trust_score": 0.93,
                "risk_level": "low",
                "recommended_action": "allow",
                "summary": "Real human voice verified; routine inquiry",
                "reasons": ["aletheia:real", "eidos:match", "gemini:routine"],
                "evidence_ids": [ev_gem_id, ev_srv_id],
                "is_final": True,
                "model_version": "trust-v1",
            },
            headers=svc_hdr,
        )
        assert ta_res.status_code == 201
        assert ta_res.json()["evidence_ids"] == [ev_srv_id, ev_gem_id]

        # 6. Latest assessment retrieval.
        latest_ta = client.get("/api/v1/calls/sessions/CALL_E2E_001/trust-assessments/latest", headers=user_hdr)
        assert latest_ta.status_code == 200 and latest_ta.json()["trust_score"] == 0.93

        # 7. Simulated transaction policy gate returns allow.
        tx_res = client.post(
            "/api/v1/calls/sessions/CALL_E2E_001/transactions/simulate",
            json={"action_type": "fund_transfer", "amount": "5000.00", "currency": "INR"},
            headers=user_hdr,
        )
        assert tx_res.status_code == 200
        assert tx_res.json()["decision"] == "allow"
        assert tx_res.json()["simulated"] is True

        # 8. End call idempotently & inspect completed call history.
        end_res = client.post(
            "/api/v1/calls/sessions/CALL_E2E_001/end",
            json={"reason": "completed_e2e"},
            headers=user_hdr,
        )
        assert end_res.status_code == 200 and end_res.json()["status"] == "ended"

        # 9. Verify dashboard WebSocket received live status, evidence, and trust events.
        received_types = []
        for _ in range(11):
            received_types.append(dash_ws.receive_json()["event_type"])
        assert "call.status_changed" in received_types
        assert "evidence.added" in received_types
        assert "trust.updated" in received_types
        assert received_types[-1] == "call.status_changed"

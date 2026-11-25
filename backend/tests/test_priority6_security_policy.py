from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.auth import create_access_token
from app.core.config import Settings, get_settings


def test_jwt_lifecycle_rbac_and_cross_user_isolation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("BACKEND_ACCESS_TOKEN", "shared-svc-secret")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-hmac-key-at-least-32-bytes")
    get_settings.cache_clear()

    # Cannot mint JWT with a non-service/user credential.
    mint_res = client.post(
        "/api/v1/auth/token",
        json={"subject": "user_alice", "role": "user", "expires_in_seconds": 300},
        headers={"Authorization": "Bearer shared-svc-secret"},
    )
    assert mint_res.status_code == 200
    alice_jwt = mint_res.json()["access_token"]

    bob_jwt = client.post(
        "/api/v1/auth/token",
        json={"subject": "user_bob", "role": "user"},
        headers={"Authorization": "Bearer shared-svc-secret"},
    ).json()["access_token"]

    service_jwt = client.post(
        "/api/v1/auth/token",
        json={"subject": "member3-trust-engine", "role": "service"},
        headers={"Authorization": "Bearer shared-svc-secret"},
    ).json()["access_token"]

    admin_jwt = client.post(
        "/api/v1/auth/token",
        json={"subject": "ops-admin", "role": "admin"},
        headers={"Authorization": "Bearer shared-svc-secret"},
    ).json()["access_token"]

    # Expired JWT fails with 401 token_expired.
    expired_token, _ = create_access_token(
        subject="user_alice",
        role="user",
        expires_in_seconds=-5,
        settings=get_settings(),
    )
    exp_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert exp_resp.status_code == 401
    assert exp_resp.json()["error"]["code"] == "token_expired"

    # Tampered signature fails 401.
    parts = alice_jwt.split(".")
    tampered_jwt = f"{parts[0]}.{parts[1]}.tampered"
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered_jwt}"}).status_code == 401

    # Alice creates her call session; Bob cannot guess & access Alice's call, evidence, or simulations (403)!
    assert (
        client.post(
            "/api/v1/calls/sessions",
            json={"call_id": "CALL_ALICE", "checks_mode": "deepfake"},
            headers={"Authorization": f"Bearer {alice_jwt}"},
        ).status_code
        == 200
    )

    # Bob's listing only shows his calls (0), never Alice's.
    bob_list = client.get("/api/v1/calls/sessions", headers={"Authorization": f"Bearer {bob_jwt}"})
    assert bob_list.status_code == 200 and bob_list.json()["total"] == 0

    for method, path, body in (
        ("GET", "/api/v1/calls/sessions/CALL_ALICE", None),
        ("GET", "/api/v1/calls/sessions/CALL_ALICE/evidence", None),
        ("GET", "/api/v1/calls/sessions/CALL_ALICE/trust-assessments", None),
        ("POST", "/api/v1/calls/sessions/CALL_ALICE/end", {}),
        (
            "POST",
            "/api/v1/calls/sessions/CALL_ALICE/transactions/simulate",
            {"action_type": "fund_transfer", "amount": "100.00", "currency": "INR"},
        ),
    ):
        resp = client.request(method, path, json=body, headers={"Authorization": f"Bearer {bob_jwt}"})
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "call_access_forbidden"

    # Regular user cannot submit Member 3 evidence or trust assessments directly (403).
    user_ev_attempt = client.post(
        "/api/v1/calls/sessions/CALL_ALICE/evidence",
        json={
            "call_id": "CALL_ALICE",
            "provider": "sarvam",
            "model": "saaras:v4",
            "check_type": "transcription",
            "status": "completed",
        },
        headers={"Authorization": f"Bearer {alice_jwt}"},
    )
    assert user_ev_attempt.status_code == 403

    # Service role (Member 3) can append evidence & trust assessments cleanly.
    svc_ev = client.post(
        "/api/v1/calls/sessions/CALL_ALICE/evidence",
        json={
            "call_id": "CALL_ALICE",
            "provider": "sarvam",
            "model": "saaras:v4",
            "check_type": "transcription",
            "status": "completed",
            "is_final": True,
        },
        headers={"Authorization": f"Bearer {service_jwt}"},
    )
    assert svc_ev.status_code == 201

    # Service role (JWT) gets 403 on admin-only webhook reconciliation endpoints; Admin gets 200.
    assert client.get("/api/v1/webhooks/events", headers={"Authorization": f"Bearer {service_jwt}"}).status_code == 403
    assert client.get("/api/v1/webhooks/events", headers={"Authorization": f"Bearer {admin_jwt}"}).status_code == 200


def test_websocket_auth_and_authorization_enforcement(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("BACKEND_ACCESS_TOKEN", "shared-ws-secret")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-hmac-key-at-least-32-bytes")
    get_settings.cache_clear()

    alice_jwt = client.post(
        "/api/v1/auth/token",
        json={"subject": "ws_alice", "role": "user"},
        headers={"Authorization": "Bearer shared-ws-secret"},
    ).json()["access_token"]
    bob_jwt = client.post(
        "/api/v1/auth/token",
        json={"subject": "ws_bob", "role": "user"},
        headers={"Authorization": "Bearer shared-ws-secret"},
    ).json()["access_token"]

    assert (
        client.post(
            "/api/v1/calls/sessions",
            json={"call_id": "CALL_WS_SEC", "checks_mode": "deepfake"},
            headers={"Authorization": f"Bearer {alice_jwt}"},
        ).status_code
        == 200
    )

    # Bob connecting to Alice's event WebSocket fails with code=forbidden / 4403!
    with client.websocket_connect("/api/v1/calls/ws/CALL_WS_SEC/events") as ws:
        ws.send_json({"type": "auth", "token": bob_jwt})
        msg = ws.receive_json()
        assert msg == {"type": "error", "code": "forbidden"}

    # Bad token fails with 4401 / unauthorized.
    with client.websocket_connect("/api/v1/calls/ws/CALL_WS_SEC/events") as ws:
        ws.send_json({"type": "auth", "token": "wrong-token"})
        msg = ws.receive_json()
        assert msg == {"type": "error", "code": "unauthorized"}

    # Alice connects successfully.
    with client.websocket_connect("/api/v1/calls/ws/CALL_WS_SEC/events") as ws:
        ws.send_json({"type": "auth", "token": alice_jwt})
        msg = ws.receive_json()
        assert msg["type"] == "subscribed" and msg["call_id"] == "CALL_WS_SEC"


def test_rate_limiting_returns_429_with_retry_after(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("RATE_LIMIT_CALL_CREATE_REQUESTS", "2")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")
    get_settings.cache_clear()

    r1 = client.post("/api/v1/calls/sessions", json={"call_id": "CALL_RL_1", "checks_mode": "deepfake"})
    r2 = client.post("/api/v1/calls/sessions", json={"call_id": "CALL_RL_2", "checks_mode": "deepfake"})
    r3 = client.post("/api/v1/calls/sessions", json={"call_id": "CALL_RL_3", "checks_mode": "deepfake"})

    assert r1.status_code == 200 and r2.status_code == 200
    assert r3.status_code == 429
    assert r3.json()["error"]["code"] == "rate_limit_exceeded"
    assert r3.json()["error"]["retryable"] is True
    assert "retry-after" in {k.lower() for k in r3.headers.keys()}


def test_simulated_transaction_policy_decisions_and_persistence(client: TestClient):
    # 1. Missing TrustAssessment -> conservative hold.
    assert client.post("/api/v1/calls/sessions", json={"call_id": "CALL_TX_1", "speaker_id": "SPK_TX"}).status_code == 200
    hold_res = client.post(
        "/api/v1/calls/sessions/CALL_TX_1/transactions/simulate",
        json={"action_type": "fund_transfer", "amount": "1500.00", "currency": "INR"},
    )
    assert hold_res.status_code == 200
    assert hold_res.json()["decision"] == "hold"
    assert hold_res.json()["simulated"] is True
    assert "missing_trust_assessment" in hold_res.json()["policy_reasons"]

    # 2. Complete passing evidence + low risk assessment -> allow (below high-value threshold).
    ev_df = client.post(
        "/api/v1/calls/sessions/CALL_TX_1/evidence",
        json={
            "call_id": "CALL_TX_1",
            "provider": "detectifai",
            "model": "aletheia",
            "check_type": "deepfake",
            "status": "completed",
            "verdict": "real",
            "is_final": True,
            "source_event_key": "tx_df_ok",
        },
    ).json()["evidence_id"]
    ev_ver = client.post(
        "/api/v1/calls/sessions/CALL_TX_1/evidence",
        json={
            "call_id": "CALL_TX_1",
            "provider": "detectifai",
            "model": "eidos",
            "check_type": "speaker_verification",
            "status": "completed",
            "verdict": "match",
            "is_final": True,
            "source_event_key": "tx_ver_ok",
        },
    ).json()["evidence_id"]
    ev_ctx = client.post(
        "/api/v1/calls/sessions/CALL_TX_1/evidence",
        json={
            "call_id": "CALL_TX_1",
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "check_type": "context",
            "status": "completed",
            "verdict": "routine",
            "is_final": True,
            "source_event_key": "tx_ctx_ok",
        },
    ).json()["evidence_id"]
    client.post(
        "/api/v1/calls/sessions/CALL_TX_1/trust-assessments",
        json={
            "trust_score": 0.91,
            "risk_level": "low",
            "recommended_action": "allow",
            "summary": "All final signals legitimate",
            "evidence_ids": [ev_df, ev_ver, ev_ctx],
            "is_final": True,
            "model_version": "trust-v1",
        },
    )

    allow_res = client.post(
        "/api/v1/calls/sessions/CALL_TX_1/transactions/simulate",
        json={"action_type": "fund_transfer", "amount": "2500.00", "currency": "INR", "recipient_ref": "ACC_1"},
    )
    assert allow_res.status_code == 200
    assert allow_res.json()["decision"] == "allow"
    assert allow_res.json()["transaction_id"].startswith("tx_")
    assert set(allow_res.json()["evidence_ids"]) == {ev_df, ev_ver, ev_ctx}

    # 3. Context risk signal elevates to step_up_verify (and block for high value).
    ev_ctx_risk = client.post(
        "/api/v1/calls/sessions/CALL_TX_1/evidence",
        json={
            "call_id": "CALL_TX_1",
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "check_type": "context",
            "status": "completed",
            "verdict": "social_engineering",
            "is_final": True,
            "source_event_key": "tx_ctx_risk",
        },
    ).json()["evidence_id"]
    client.post(
        "/api/v1/calls/sessions/CALL_TX_1/trust-assessments",
        json={
            "trust_score": 0.68,
            "risk_level": "medium",
            "recommended_action": "step_up_verify",
            "summary": "Social engineering cues detected",
            "evidence_ids": [ev_df, ev_ver, ev_ctx_risk],
            "is_final": True,
            "model_version": "trust-v1",
        },
    )
    stepup_res = client.post(
        "/api/v1/calls/sessions/CALL_TX_1/transactions/simulate",
        json={"action_type": "fund_transfer", "amount": "1000.00", "currency": "INR"},
    )
    assert stepup_res.status_code == 200 and stepup_res.json()["decision"] == "step_up_verify"

    high_val_block = client.post(
        "/api/v1/calls/sessions/CALL_TX_1/transactions/simulate",
        json={"action_type": "fund_transfer", "amount": "75000.00", "currency": "INR"},
    )
    assert high_val_block.status_code == 200 and high_val_block.json()["decision"] == "block"

    # 4. Final deepfake detected always blocks cleanly.
    assert client.post("/api/v1/calls/sessions", json={"call_id": "CALL_TX_FAKE", "checks_mode": "deepfake"}).status_code == 200
    ev_fake = client.post(
        "/api/v1/calls/sessions/CALL_TX_FAKE/evidence",
        json={
            "call_id": "CALL_TX_FAKE",
            "provider": "detectifai",
            "model": "aletheia",
            "check_type": "deepfake",
            "status": "completed",
            "verdict": "fake",
            "raw_score": 0.96,
            "score_type": "synthetic_score",
            "is_final": True,
            "source_event_key": "tx_df_fake",
        },
    ).json()["evidence_id"]
    client.post(
        "/api/v1/calls/sessions/CALL_TX_FAKE/trust-assessments",
        json={
            "trust_score": 0.12,
            "risk_level": "critical",
            "recommended_action": "block",
            "summary": "Synthetic voice clone detected",
            "evidence_ids": [ev_fake],
            "is_final": True,
            "model_version": "trust-v1",
        },
    )
    block_res = client.post(
        "/api/v1/calls/sessions/CALL_TX_FAKE/transactions/simulate",
        json={"action_type": "credential_reset", "amount": "1.00", "currency": "INR"},
    )
    assert block_res.status_code == 200 and block_res.json()["decision"] == "block"

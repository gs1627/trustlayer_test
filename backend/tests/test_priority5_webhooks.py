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
from app.core.security import WebhookSignatureError, verify_detectif_webhook_signature
from app.db.models import CallSession, SpeakerProfile, WebhookEvent


def _make_sig_headers(secret: str, webhook_id: str, ts: int, body: bytes) -> dict[str, str]:
    key = base64.b64decode(secret.removeprefix("whsec_"))
    signed = f"{webhook_id}.{ts}.".encode("utf-8") + body
    sig = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode("ascii")
    return {
        "webhook-id": webhook_id,
        "webhook-timestamp": str(ts),
        "webhook-signature": f"v1,{sig}",
    }


def test_webhook_signature_supports_key_rotation_and_rejects_future_replay():
    old_secret = "whsec_" + base64.b64encode(b"old-secret-bytes").decode()
    new_secret = "whsec_" + base64.b64encode(b"new-secret-bytes").decode()
    body = b'{"type":"webhook.test"}'
    now = int(time.time())

    # Delivered signed by rotated old secret passes when listed in previous_secrets.
    headers_old = _make_sig_headers(old_secret, "msg_rot_1", now, body)
    verify_detectif_webhook_signature(
        secret=new_secret,
        previous_secrets=(old_secret,),
        headers=headers_old,
        raw_body=body,
        now=float(now),
    )

    # Space-separated signatures (rotation window) succeed if one matches.
    headers_multi = {
        **headers_old,
        "webhook-signature": f"v1,invalidSig== {headers_old['webhook-signature']}",
    }
    verify_detectif_webhook_signature(
        secret=new_secret,
        previous_secrets=(old_secret,),
        headers=headers_multi,
        raw_body=body,
        now=float(now),
    )

    # Far-future forged timestamp rejected against replay/skew.
    headers_future = _make_sig_headers(new_secret, "msg_fut_1", now + 600, body)
    with pytest.raises(WebhookSignatureError):
        verify_detectif_webhook_signature(
            secret=new_secret,
            headers=headers_future,
            raw_body=body,
            now=float(now),
        )


def test_webhook_out_of_order_enrollment_and_unmatched_reconciliation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    secret = "whsec_" + base64.b64encode(b"p5-webhook-secret").decode()
    monkeypatch.setenv("DETECTIF_WEBHOOK_SECRET", secret)
    get_settings.cache_clear()
    now = int(time.time())

    # 1. Webhook arriving BEFORE call session exists is persisted cleanly as `unmatched` (zero event loss!).
    early_body = json.dumps(
        {
            "id": "evt_early_unmatched",
            "type": "deepfake.completed",
            "created_at": now,
            "data": {
                "reference": "CALL_P5_RECONCILE",
                "operation_id": "op_df_early_1",
                "result": {"verdict": "real", "score": 0.05},
            },
        }
    ).encode("utf-8")
    r_unmatched = client.post(
        "/api/v1/webhooks/detectifai",
        content=early_body,
        headers=_make_sig_headers(secret, "msg_early_1", now, early_body),
    )
    assert r_unmatched.status_code == 202
    assert r_unmatched.json()["status"] == "unmatched"

    # Creating the matching CallSession automatically reconciles the unmatched webhook event & normalizes evidence!
    r_create = client.post(
        "/api/v1/calls/sessions",
        json={
            "call_id": "CALL_P5_RECONCILE",
            "speaker_id": "SPK_P5",
            "checks_mode": "deepfake,enroll",
            "consent_confirmed": True,
        },
    )
    assert r_create.status_code == 200
    ev_after = client.get("/api/v1/calls/sessions/CALL_P5_RECONCILE/evidence").json()
    assert ev_after["total"] == 1
    assert ev_after["items"][0]["is_final"] is True

    # 2. Out-of-order: stream.completed arrives first, followed by stale stream.started and stream.deepfake.updated.
    comp_body = json.dumps(
        {
            "id": "evt_p5_comp",
            "type": "stream.completed",
            "created_at": now + 20,
            "data": {
                "stream_id": "str_p5_ooo",
                "reference": "CALL_P5_RECONCILE",
                "speaker_id": "SPK_P5",
                "results": {
                    "deepfake": {"verdict": "real", "score": 0.02},
                    "enroll": {"status": "enrolled", "sample_count": 1},
                },
            },
        }
    ).encode("utf-8")
    assert (
        client.post(
            "/api/v1/webhooks/detectifai",
            content=comp_body,
            headers=_make_sig_headers(secret, "msg_p5_comp", now, comp_body),
        ).status_code
        == 202
    )

    late_started = json.dumps(
        {
            "id": "evt_p5_late_start",
            "type": "stream.started",
            "created_at": now + 1,
            "data": {"stream_id": "str_p5_ooo", "reference": "CALL_P5_RECONCILE"},
        }
    ).encode("utf-8")
    assert (
        client.post(
            "/api/v1/webhooks/detectifai",
            content=late_started,
            headers=_make_sig_headers(secret, "msg_p5_late_start", now, late_started),
        ).status_code
        == 202
    )

    late_prov = json.dumps(
        {
            "id": "evt_p5_late_upd",
            "type": "stream.deepfake.updated",
            "created_at": now + 5,
            "data": {
                "stream_id": "str_p5_ooo",
                "reference": "CALL_P5_RECONCILE",
                "sequence": 1,
                "early": True,
                "verdict": "fake",
                "score": 0.99,
            },
        }
    ).encode("utf-8")
    assert (
        client.post(
            "/api/v1/webhooks/detectifai",
            content=late_prov,
            headers=_make_sig_headers(secret, "msg_p5_late_upd", now, late_prov),
        ).status_code
        == 202
    )

    detail = client.get("/api/v1/calls/sessions/CALL_P5_RECONCILE").json()
    # Out-of-order stream.started NEVER reverted status from completed back to active!
    assert detail["status"] == "completed"
    # Final deepfake items preserved without being overwritten by provisional event.
    final_items = client.get(
        "/api/v1/calls/sessions/CALL_P5_RECONCILE/evidence",
        params={"is_final": True, "check_type": "deepfake"},
    ).json()["items"]
    assert len(final_items) == 2
    assert all(item["verdict"] == "real" for item in final_items)

    # speaker.enrolled and speaker.verified webhook events handled cleanly.
    verified_body = json.dumps(
        {
            "id": "evt_p5_spk_ver",
            "type": "speaker.verified",
            "created_at": now + 25,
            "data": {
                "reference": "CALL_P5_RECONCILE",
                "speaker_id": "SPK_P5",
                "operation_id": "op_spk_ver_wh",
                "decision": "match",
                "similarity": 0.91,
            },
        }
    ).encode("utf-8")
    assert (
        client.post(
            "/api/v1/webhooks/detectifai",
            content=verified_body,
            headers=_make_sig_headers(secret, "msg_p5_ver", now, verified_body),
        ).status_code
        == 202
    )


def test_failed_webhook_retries_dead_letter_and_manual_reprocess(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    secret = "whsec_" + base64.b64encode(b"p5-dlq-secret").decode()
    monkeypatch.setenv("DETECTIF_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("WEBHOOK_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("WEBHOOK_RETRY_BASE_SECONDS", "1")
    get_settings.cache_clear()
    now = int(time.time())

    assert client.post("/api/v1/calls/sessions", json={"call_id": "CALL_P5_DLQ", "checks_mode": "deepfake"}).status_code == 200

    # Corrupt score ("not-float") fails normalization inside savepoint, saving WebhookEvent as `failed`.
    bad_body = json.dumps(
        {
            "id": "evt_p5_bad",
            "type": "deepfake.completed",
            "created_at": now,
            "data": {"reference": "CALL_P5_DLQ", "result": {"verdict": "real", "score": "not-float"}},
        }
    ).encode("utf-8")

    r1 = client.post(
        "/api/v1/webhooks/detectifai",
        content=bad_body,
        headers=_make_sig_headers(secret, "msg_p5_bad", now, bad_body),
    )
    assert r1.status_code == 202
    assert r1.json()["status"] == "failed"

    # Reconcile advances failed event to dead_letter when max_attempts=2 is reached.
    rec = client.post("/api/v1/webhooks/reconcile")
    assert rec.status_code == 200
    assert rec.json()["dead_lettered"] == 1

    dlq_list = client.get("/api/v1/webhooks/events", params={"status": "dead_letter"}).json()
    assert dlq_list["total"] == 1
    assert dlq_list["items"][0]["delivery_id"] == "msg_p5_bad"
    assert dlq_list["items"][0]["dead_lettered_at"] is not None


@pytest.mark.asyncio
async def test_concurrent_duplicate_webhook_delivery_produces_one_event_and_one_evidence(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    secret = "whsec_" + base64.b64encode(b"p5-conc-secret").decode()
    monkeypatch.setenv("DETECTIF_WEBHOOK_SECRET", secret)
    get_settings.cache_clear()
    now = int(time.time())

    await async_client.post("/api/v1/calls/sessions", json={"call_id": "CALL_P5_CONC", "checks_mode": "deepfake"})

    body = json.dumps(
        {
            "id": "evt_p5_conc_1",
            "type": "deepfake.completed",
            "created_at": now,
            "data": {"reference": "CALL_P5_CONC", "operation_id": "op_conc_wh", "result": {"verdict": "real", "score": 0.04}},
        }
    ).encode("utf-8")
    headers = _make_sig_headers(secret, "msg_p5_conc", now, body)

    r1, r2 = await asyncio.gather(
        async_client.post("/api/v1/webhooks/detectifai", content=body, headers=headers),
        async_client.post("/api/v1/webhooks/detectifai", content=body, headers=headers),
    )
    assert r1.status_code == 202 and r2.status_code == 202
    assert sorted([r1.json()["duplicate"], r2.json()["duplicate"]]) == [False, True]

    ev_res = await async_client.get("/api/v1/calls/sessions/CALL_P5_CONC/evidence")
    assert ev_res.json()["total"] == 1

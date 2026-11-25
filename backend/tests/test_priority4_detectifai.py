import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.routes import detectif as detectif_route
from app.core.config import Settings, get_settings
from app.db.models import SpeakerProfile
from app.services.detectif_client import DetectifAPIError, DetectifClient
from app.services.detectif_stream import DetectifStreamError, relay_browser_audio_to_detectif


@pytest.mark.asyncio
async def test_detectif_client_retries_transient_503_and_preserves_idempotency_key():
    seen_headers: list[dict[str, str]] = []
    attempt = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempt
        attempt += 1
        seen_headers.append(dict(request.headers))
        if attempt == 1:
            return httpx.Response(
                503,
                json={"error": {"type": "overloaded", "code": "overloaded", "message": "Try again"}},
                headers={"X-Request-Id": "req_retry_1"},
            )
        return httpx.Response(
            200,
            json={
                "request_id": "req_ok_2",
                "operation_id": "op_retry_ok",
                "object": "deepfake.detection",
                "result": {"verdict": "real", "score": 0.04},
            },
        )

    settings = Settings(
        detectif_api_key="test-key",
        detectif_base_url="https://mock.detectif.test",
        detectif_max_retries=2,
        detectif_retry_backoff_seconds=0.0,
    )
    client = DetectifClient(settings)
    client._http_client = httpx.AsyncClient(
        base_url="https://mock.detectif.test",
        transport=httpx.MockTransport(handler),
    )
    import asyncio

    client._client_loop = asyncio.get_running_loop()
    client._client_base_url = "https://mock.detectif.test"
    client._client_timeouts = (
        settings.detectif_connect_timeout_seconds,
        settings.detectif_timeout_seconds,
    )
    try:
        payload, meta = await client.detect_deepfake_with_meta(
            filename="sample.wav",
            content=b"RIFF....",
            content_type="audio/wav",
            idempotency_key="idem-fixed-123",
            correlation_id="corr-fixed-123",
        )
        assert payload["operation_id"] == "op_retry_ok"
        assert meta["retry_count"] == 1
        assert len(seen_headers) == 2
        assert seen_headers[0]["idempotency-key"] == "idem-fixed-123"
        assert seen_headers[1]["idempotency-key"] == "idem-fixed-123"
        assert seen_headers[0]["x-correlation-id"] == "corr-fixed-123"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_detectif_client_does_not_retry_insufficient_credits_or_400():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            429,
            json={
                "error": {
                    "type": "insufficient_credits",
                    "code": "credit_balance_exhausted",
                    "message": "Out of credits",
                },
                "request_id": "req_credits",
            },
        )

    settings = Settings(
        detectif_api_key="test-key",
        detectif_base_url="https://mock.detectif.test",
        detectif_max_retries=3,
        detectif_retry_backoff_seconds=0.0,
    )
    client = DetectifClient(settings)
    import asyncio

    client._http_client = httpx.AsyncClient(
        base_url="https://mock.detectif.test",
        transport=httpx.MockTransport(handler),
    )
    client._client_loop = asyncio.get_running_loop()
    client._client_base_url = "https://mock.detectif.test"
    client._client_timeouts = (
        settings.detectif_connect_timeout_seconds,
        settings.detectif_timeout_seconds,
    )
    try:
        with pytest.raises(DetectifAPIError) as exc_info:
            await client.detect_deepfake_with_meta(
                filename="a.wav",
                content=b"abc",
                content_type="audio/wav",
            )
        assert exc_info.value.status_code == 429
        assert exc_info.value.retryable is False
        assert exc_info.value.code == "credit_balance_exhausted"
        assert calls == 1
    finally:
        await client.aclose()


def test_detectif_routes_track_operations_unknown_caller_enroll_verify_and_sync(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("DETECTIF_API_KEY", "test-placeholder")
    get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/deepfake/detect":
            return httpx.Response(
                200,
                json={
                    "request_id": "req_df_p4",
                    "operation_id": "op_df_p4",
                    "object": "deepfake.detection",
                    "result": {"verdict": "real", "score": 0.03},
                    "credits": 1,
                },
            )
        if path == "/v1/speakers/enroll":
            return httpx.Response(
                200,
                json={
                    "request_id": "req_enr_p4",
                    "operation_id": "op_enr_p4",
                    "object": "speaker.enrollment",
                    "result": {"speaker_id": "SPK_P4", "status": "enrolled", "sample_count": 1},
                },
            )
        if path == "/v1/speakers/verify":
            body_text = request.content.decode("utf-8", errors="ignore")
            if "UNKNOWN_CALLER_SPK" in body_text:
                return httpx.Response(
                    404,
                    json={
                        "error": {
                            "type": "not_found",
                            "code": "speaker_not_found",
                            "message": "Speaker not found",
                        },
                        "request_id": "req_ver_unk",
                    },
                )
            return httpx.Response(
                200,
                json={
                    "request_id": "req_ver_p4",
                    "operation_id": "op_ver_p4",
                    "object": "speaker.verification",
                    "result": {
                        "decision": "match",
                        "similarity": 0.87,
                        "speaker_id": "SPK_P4",
                        "deepfake": {"verdict": "real", "score": 0.02},
                    },
                },
            )
        if path == "/v1/operations/op_df_p4":
            return httpx.Response(
                200,
                json={
                    "request_id": "req_op_poll",
                    "object": "operation",
                    "operation_id": "op_df_p4",
                    "type": "deepfake.detect",
                    "status": "succeeded",
                    "source": "api",
                    "parent_operation_id": None,
                    "credits_charged": 2,
                    "created_at": "2026-11-25T10:00:00Z",
                    "completed_at": "2026-11-25T10:00:02Z",
                    "result": {"verdict": "real", "score": 0.03},
                    "error": None,
                },
            )
        if path == "/v1/speakers/SPK_P4" and request.method == "DELETE":
            return httpx.Response(200, json={"deleted": True, "speaker_id": "SPK_P4"})
        return httpx.Response(404, json={"error": {"type": "not_found", "code": "not_found"}})

    monkeypatch.setattr(detectif_route, "client", DetectifClient())
    import httpx as _httpx

    orig_get_client = detectif_route.client._get_http_client

    async def mocked_http_client():
        if detectif_route.client._http_client is None or detectif_route.client._http_client.is_closed:
            detectif_route.client._http_client = _httpx.AsyncClient(
                base_url="https://platform.detectif.ai",
                transport=_httpx.MockTransport(handler),
            )
        return detectif_route.client._http_client

    monkeypatch.setattr(detectif_route.client, "_get_http_client", mocked_http_client)

    # Scenario 1: Unknown caller call (deepfake-only) + REST upload attaches evidence cleanly.
    assert client.post("/api/v1/calls/sessions", json={"call_id": "CALL_UNK_P4", "checks_mode": "deepfake"}).status_code == 200
    df_resp = client.post(
        "/api/v1/detectif/deepfake",
        files={"file": ("clip.wav", b"RIFF1234", "audio/wav")},
        data={"call_id": "CALL_UNK_P4"},
        headers={"Idempotency-Key": "idem-df-p4"},
    )
    assert df_resp.status_code == 200
    assert df_resp.json()["operation_id"] == "op_df_p4"
    assert client.get("/api/v1/calls/sessions/CALL_UNK_P4/evidence").json()["total"] == 1

    # Scenario 2: Enroll with consent -> SpeakerProfile tracked + consent enforced.
    bad_enroll = client.post(
        "/api/v1/detectif/speakers/enroll",
        data={"speaker_id": "SPK_P4", "consent_confirmed": "false"},
        files={"file": ("enr.wav", b"RIFF1234", "audio/wav")},
    )
    assert bad_enroll.status_code == 400

    ok_enroll = client.post(
        "/api/v1/detectif/speakers/enroll",
        data={"speaker_id": "SPK_P4", "display_name": "Alice", "consent_confirmed": "true"},
        files={"file": ("enr.wav", b"RIFF1234", "audio/wav")},
    )
    assert ok_enroll.status_code == 200

    # Scenario 3: Registered verify (emits both Eidos + Aletheia evidence) & unknown speaker 404.
    assert client.post("/api/v1/calls/sessions", json={"call_id": "CALL_REG_P4", "speaker_id": "SPK_P4"}).status_code == 200
    ver_ok = client.post(
        "/api/v1/detectif/speakers/verify",
        data={"speaker_id": "SPK_P4", "detect_deepfake": "true", "call_id": "CALL_REG_P4"},
        files={"file": ("ver.wav", b"RIFF1234", "audio/wav")},
    )
    assert ver_ok.status_code == 200
    assert client.get("/api/v1/calls/sessions/CALL_REG_P4/evidence").json()["total"] == 2

    ver_unknown = client.post(
        "/api/v1/detectif/speakers/verify",
        data={"speaker_id": "UNKNOWN_CALLER_SPK", "detect_deepfake": "true"},
        files={"file": ("ver.wav", b"RIFF1234", "audio/wav")},
    )
    assert ver_unknown.status_code == 404
    assert ver_unknown.json()["detail"]["code"] == "speaker_not_found"

    # Operation polling syncs credits & listing tracked operations includes failed & succeeded.
    op_get = client.get("/api/v1/detectif/operations/op_df_p4")
    assert op_get.status_code == 200
    tracked_ops = client.get("/api/v1/detectif/operations")
    assert tracked_ops.status_code == 200
    assert tracked_ops.json()["total"] >= 4
    df_tracked = [o for o in tracked_ops.json()["items"] if o["operation_id"] == "op_df_p4"][0]
    assert df_tracked["credits"] == 2
    assert df_tracked["completed_at"] is not None

    # Delete speaker syncs local profile cleanly.
    del_res = client.delete("/api/v1/detectif/speakers/SPK_P4")
    assert del_res.status_code == 200


@pytest.mark.asyncio
async def test_stream_relay_handles_deepfake_only_and_enroll_modes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DETECTIF_API_KEY", "test-stream-secret")
    get_settings.cache_clear()

    opened_urls: list[str] = []

    class FakeProviderWS:
        def __init__(self):
            self.sent = []
            self._msgs = [
                json.dumps({"type": "ready", "stream_id": "str_test"}),
                json.dumps({"type": "completed", "stream_id": "str_test", "results": {"deepfake": {"verdict": "real", "score": 0.01}}}),
            ]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def __aiter__(self):
            self._it = iter(self._msgs)
            return self

        async def __anext__(self):
            try:
                return next(self._it)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

        async def send(self, data):
            self.sent.append(data)

    class FakeBrowserWS:
        def __init__(self):
            self.sent_json = []
            self._incoming = [{"type": "text", "text": json.dumps({"type": "stop"})}]

        async def receive(self):
            if self._incoming:
                return self._incoming.pop(0)
            await asyncio.sleep(0.05)
            return {"type": "websocket.disconnect"}

        async def send_json(self, data):
            self.sent_json.append(data)

    import asyncio
    from app.services import detectif_stream as stream_mod

    def fake_connect(url, **_kwargs):
        opened_urls.append(url)
        return FakeProviderWS()

    monkeypatch.setattr(stream_mod.websockets, "connect", fake_connect)

    # 1. Unknown caller (checks=deepfake) does NOT require speaker_id and omits it in query string!
    browser_1 = FakeBrowserWS()
    await relay_browser_audio_to_detectif(
        browser_ws=browser_1,
        call_id="CALL_STR_UNK",
        speaker_id=None,
        checks_mode="deepfake",
    )
    assert "checks=deepfake" in opened_urls[0]
    assert "speaker_id" not in opened_urls[0]

    # 2. Enrollment requires consent_confirmed=True.
    with pytest.raises(DetectifStreamError, match="consent"):
        await relay_browser_audio_to_detectif(
            browser_ws=FakeBrowserWS(),
            call_id="CALL_STR_ENR",
            speaker_id="SPK_1",
            checks_mode="deepfake,enroll",
            consent_confirmed=False,
        )

    await relay_browser_audio_to_detectif(
        browser_ws=FakeBrowserWS(),
        call_id="CALL_STR_ENR",
        speaker_id="SPK_1",
        checks_mode="deepfake,enroll",
        consent_confirmed=True,
    )
    assert "checks=deepfake%2Cenroll" in opened_urls[1]
    assert "speaker_id=SPK_1" in opened_urls[1]

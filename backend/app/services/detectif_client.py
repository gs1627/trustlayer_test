from __future__ import annotations

import asyncio
import logging
import random
from typing import Any
import uuid

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_NON_RETRYABLE_ERROR_TYPES = frozenset(
    {
        "invalid_request",
        "authentication",
        "permission",
        "not_found",
        "conflict",
        "insufficient_credits",
        "payload_too_large",
        "unsupported_media",
        "unprocessable_audio",
    }
)
_NON_RETRYABLE_ERROR_CODES = frozenset({"credit_balance_exhausted", "insufficient_credits"})
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class DetectifNotConfiguredError(RuntimeError):
    pass


class DetectifAPIError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        detail: Any,
        *,
        code: str = "detectifai_api_error",
        error_type: str | None = None,
        provider_request_id: str | None = None,
        retryable: bool = False,
        retry_attempts: int = 0,
    ) -> None:
        self.status_code = status_code
        self.detail = detail
        self.code = code
        self.error_type = error_type
        self.provider_request_id = provider_request_id
        self.retryable = retryable
        self.retry_attempts = retry_attempts
        super().__init__(f"DetectifAI returned HTTP {status_code} ({code})")


def _classify_provider_error(status_code: int, payload: Any) -> tuple[str, str | None, bool, str | None]:
    provider_req_id = payload.get("request_id") if isinstance(payload, dict) else None
    err = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(err, dict):
        err_type = str(err.get("type") or "") or None
        err_code = str(err.get("code") or err_type or f"provider_http_{status_code}")
        if err_type in _NON_RETRYABLE_ERROR_TYPES or err_code in _NON_RETRYABLE_ERROR_CODES:
            return err_code, err_type, False, provider_req_id
        if status_code in _RETRYABLE_STATUS_CODES or err_type in {"rate_limited", "overloaded", "internal"}:
            return err_code, err_type, True, provider_req_id
        return err_code, err_type, False, provider_req_id

    if status_code == 429:
        return "provider_rate_limited", "rate_limited", True, provider_req_id
    if status_code in _RETRYABLE_STATUS_CODES:
        return f"provider_http_{status_code}", "transient_error", True, provider_req_id
    return f"provider_http_{status_code}", "client_error", False, provider_req_id


def _parse_retry_after(header_value: str | None) -> float | None:
    if not header_value:
        return None
    try:
        delay = float(header_value.strip())
        return min(max(delay, 0.0), 30.0)
    except ValueError:
        return None


class DetectifClient:
    """Hardened async HTTP client for DetectifAI with connection pooling and safe retries.

    Audio bytes and API secrets are never logged.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._explicit_settings = settings
        self._http_client: httpx.AsyncClient | None = None
        self._client_loop: asyncio.AbstractEventLoop | None = None
        self._client_base_url: str | None = None
        self._client_timeouts: tuple[float, float] | None = None

    @property
    def settings(self) -> Settings:
        return self._explicit_settings if self._explicit_settings is not None else get_settings()

    async def _get_http_client(self) -> httpx.AsyncClient:
        settings = self.settings
        running_loop = asyncio.get_running_loop()
        base_url = settings.detectif_base_url.rstrip("/")
        timeouts = (settings.detectif_connect_timeout_seconds, settings.detectif_timeout_seconds)

        needs_recreate = (
            self._http_client is None
            or self._http_client.is_closed
            or self._client_loop is not running_loop
            or self._client_base_url != base_url
            or self._client_timeouts != timeouts
        )
        if needs_recreate:
            if self._http_client is not None and not self._http_client.is_closed:
                try:
                    await self._http_client.aclose()
                except Exception:
                    pass
            timeout = httpx.Timeout(
                timeout=settings.detectif_timeout_seconds,
                connect=settings.detectif_connect_timeout_seconds,
                read=settings.detectif_timeout_seconds,
                write=settings.detectif_timeout_seconds,
                pool=settings.detectif_connect_timeout_seconds,
            )
            limits = httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=30.0)
            self._http_client = httpx.AsyncClient(base_url=base_url, timeout=timeout, limits=limits)
            self._client_loop = running_loop
            self._client_base_url = base_url
            self._client_timeouts = timeouts
        return self._http_client

    async def aclose(self) -> None:
        """Close the shared connection pool during application shutdown."""
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
        self._http_client = None
        self._client_loop = None

    def _auth_headers(self, *, correlation_id: str, idempotency_key: str | None = None) -> dict[str, str]:
        if not self.settings.detectif_api_key:
            raise DetectifNotConfiguredError("DETECTIF_API_KEY is not configured")
        headers = {
            "Authorization": f"Bearer {self.settings.detectif_api_key}",
            "X-Correlation-ID": correlation_id,
        }
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _compute_backoff(self, attempt_index: int, retry_after: float | None = None) -> float:
        if retry_after is not None:
            return retry_after
        base = self.settings.detectif_retry_backoff_seconds
        if base <= 0:
            return 0.0
        jitter = random.uniform(0.0, base * 0.25)
        return min(base * (2**attempt_index) + jitter, 15.0)

    async def _send_with_retry(
        self,
        *,
        method: str,
        path: str,
        is_idempotent: bool,
        headers: dict[str, str],
        correlation_id: str,
        **request_kwargs: Any,
    ) -> tuple[dict[str, Any], int]:
        max_retries = self.settings.detectif_max_retries if is_idempotent else 0
        total_attempts = 1 + max_retries
        client = await self._get_http_client()

        for attempt in range(total_attempts):
            try:
                response = await client.request(method, path, headers=headers, **request_kwargs)
            except httpx.TimeoutException as exc:
                logger.warning(
                    "DetectifAI request timeout method=%s path=%s attempt=%d/%d correlation_id=%s",
                    method,
                    path,
                    attempt + 1,
                    total_attempts,
                    correlation_id,
                )
                if attempt + 1 < total_attempts:
                    await asyncio.sleep(self._compute_backoff(attempt))
                    continue
                raise DetectifAPIError(
                    504,
                    {"code": "provider_timeout", "message": "DetectifAI request timed out"},
                    code="provider_timeout",
                    error_type="timeout",
                    retryable=True,
                    retry_attempts=attempt,
                ) from exc
            except httpx.HTTPError as exc:
                logger.warning(
                    "DetectifAI transport error method=%s path=%s attempt=%d/%d correlation_id=%s",
                    method,
                    path,
                    attempt + 1,
                    total_attempts,
                    correlation_id,
                )
                if attempt + 1 < total_attempts:
                    await asyncio.sleep(self._compute_backoff(attempt))
                    continue
                raise DetectifAPIError(
                    502,
                    {"code": "provider_connection_error", "message": "Could not connect to DetectifAI"},
                    code="provider_connection_error",
                    error_type="connection_error",
                    retryable=True,
                    retry_attempts=attempt,
                ) from exc

            try:
                payload = response.json()
            except ValueError:
                payload = {"message": response.text[:1000]}

            req_id = response.headers.get("X-Request-Id") or (
                payload.get("request_id") if isinstance(payload, dict) else None
            )

            if not response.is_success:
                err_code, err_type, retryable, body_req_id = _classify_provider_error(
                    response.status_code,
                    payload,
                )
                resolved_req_id = body_req_id or req_id
                logger.warning(
                    "DetectifAI API error status=%d code=%s retryable=%s attempt=%d/%d correlation_id=%s request_id=%s",
                    response.status_code,
                    err_code,
                    retryable,
                    attempt + 1,
                    total_attempts,
                    correlation_id,
                    resolved_req_id,
                )
                if retryable and attempt + 1 < total_attempts:
                    retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                    await asyncio.sleep(self._compute_backoff(attempt, retry_after=retry_after))
                    continue
                raise DetectifAPIError(
                    response.status_code,
                    payload,
                    code=err_code,
                    error_type=err_type,
                    provider_request_id=resolved_req_id,
                    retryable=retryable,
                    retry_attempts=attempt,
                )

            if not isinstance(payload, dict):
                raise DetectifAPIError(
                    502,
                    {"code": "invalid_provider_response", "message": "Expected JSON object from DetectifAI"},
                    code="invalid_provider_response",
                    error_type="invalid_response",
                    provider_request_id=req_id,
                    retryable=False,
                    retry_attempts=attempt,
                )

            if req_id and "request_id" not in payload:
                payload["request_id"] = req_id

            logger.info(
                "DetectifAI request succeeded method=%s path=%s attempt=%d correlation_id=%s request_id=%s operation_id=%s",
                method,
                path,
                attempt + 1,
                correlation_id,
                payload.get("request_id"),
                payload.get("operation_id"),
            )
            return payload, attempt

        raise AssertionError("Unreachable retry loop exit")

    async def _post_audio_with_meta(
        self,
        *,
        path: str,
        filename: str,
        content: bytes,
        content_type: str,
        data: dict[str, str] | None = None,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        corr_id = correlation_id or f"corr_{uuid.uuid4().hex}"
        idem_key = idempotency_key or str(uuid.uuid4())
        headers = self._auth_headers(correlation_id=corr_id, idempotency_key=idem_key)
        payload, retry_count = await self._send_with_retry(
            method="POST",
            path=path,
            is_idempotent=True,
            headers=headers,
            correlation_id=corr_id,
            data=data or {},
            files={"file": (filename, content, content_type)},
        )
        return payload, {"retry_count": retry_count, "correlation_id": corr_id, "idempotency_key": idem_key}

    async def detect_deepfake_with_meta(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return await self._post_audio_with_meta(
            path="/v1/deepfake/detect",
            filename=filename,
            content=content,
            content_type=content_type,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    async def detect_deepfake(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        payload, _ = await self.detect_deepfake_with_meta(
            filename=filename,
            content=content,
            content_type=content_type,
            idempotency_key=idempotency_key,
        )
        return payload

    async def enroll_speaker_with_meta(
        self,
        *,
        speaker_id: str,
        filename: str,
        content: bytes,
        content_type: str,
        display_name: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        data = {"speaker_id": speaker_id}
        if display_name:
            data["display_name"] = display_name
        return await self._post_audio_with_meta(
            path="/v1/speakers/enroll",
            filename=filename,
            content=content,
            content_type=content_type,
            data=data,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    async def enroll_speaker(
        self,
        *,
        speaker_id: str,
        filename: str,
        content: bytes,
        content_type: str,
        display_name: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        payload, _ = await self.enroll_speaker_with_meta(
            speaker_id=speaker_id,
            filename=filename,
            content=content,
            content_type=content_type,
            display_name=display_name,
            idempotency_key=idempotency_key,
        )
        return payload

    async def verify_speaker_with_meta(
        self,
        *,
        speaker_id: str,
        filename: str,
        content: bytes,
        content_type: str,
        detect_deepfake: bool = True,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        data = {
            "speaker_id": speaker_id,
            "detect_deepfake": "true" if detect_deepfake else "false",
        }
        return await self._post_audio_with_meta(
            path="/v1/speakers/verify",
            filename=filename,
            content=content,
            content_type=content_type,
            data=data,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    async def verify_speaker(
        self,
        *,
        speaker_id: str,
        filename: str,
        content: bytes,
        content_type: str,
        detect_deepfake: bool = True,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        payload, _ = await self.verify_speaker_with_meta(
            speaker_id=speaker_id,
            filename=filename,
            content=content,
            content_type=content_type,
            detect_deepfake=detect_deepfake,
            idempotency_key=idempotency_key,
        )
        return payload

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        correlation_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        corr_id = correlation_id or f"corr_{uuid.uuid4().hex}"
        headers = self._auth_headers(correlation_id=corr_id)
        custom_headers = kwargs.pop("headers", None)
        if isinstance(custom_headers, dict):
            headers.update(custom_headers)
        is_idempotent = method.upper() in {"GET", "HEAD", "OPTIONS"}
        payload, _ = await self._send_with_retry(
            method=method,
            path=path,
            is_idempotent=is_idempotent,
            headers=headers,
            correlation_id=corr_id,
            **kwargs,
        )
        return payload

    async def get_operation(self, operation_id: str, *, correlation_id: str | None = None) -> dict[str, Any]:
        return await self._request_json("GET", f"/v1/operations/{operation_id}", correlation_id=correlation_id)

    async def list_speakers(
        self,
        limit: int = 20,
        cursor: str | None = None,
        *,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._request_json("GET", "/v1/speakers", params=params, correlation_id=correlation_id)

    async def delete_speaker(self, speaker_id: str, *, correlation_id: str | None = None) -> dict[str, Any]:
        return await self._request_json("DELETE", f"/v1/speakers/{speaker_id}", correlation_id=correlation_id)

    async def get_stream(self, stream_id: str, *, correlation_id: str | None = None) -> dict[str, Any]:
        return await self._request_json("GET", f"/v1/streams/{stream_id}", correlation_id=correlation_id)

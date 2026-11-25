from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
import logging
import time
from urllib.parse import urlencode
import uuid

import websockets
from websockets.exceptions import ConnectionClosed

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_VALID_CHECKS_MODES = frozenset({"deepfake", "deepfake,verify", "deepfake,enroll"})
_MAX_AUDIO_FRAME_BYTES = 64 * 1024
_MAX_TEXT_FRAME_BYTES = 16 * 1024


class DetectifStreamError(RuntimeError):
    pass


def _build_stream_ws_url(
    *,
    base_url: str,
    call_id: str,
    checks_mode: str,
    speaker_id: str | None,
) -> str:
    ws_base = base_url.rstrip("/")
    if ws_base.startswith("https://"):
        ws_base = "wss://" + ws_base[len("https://") :]
    elif ws_base.startswith("http://"):
        ws_base = "ws://" + ws_base[len("http://") :]

    params: dict[str, str] = {
        "checks": checks_mode,
        "encoding": "pcm_s16le",
        "sample_rate": "16000",
        "reference": call_id,
    }
    if speaker_id:
        params["speaker_id"] = speaker_id
    return f"{ws_base}/v1/stream?{urlencode(params)}"


async def relay_browser_audio_to_detectif(
    *,
    browser_ws,
    call_id: str,
    speaker_id: str | None = None,
    checks_mode: str = "deepfake,verify",
    consent_confirmed: bool = False,
    on_provider_message: Callable[[dict], Awaitable[None]] | None = None,
) -> None:
    """Relay raw 16 kHz mono PCM16 browser frames to a DetectifAI live stream.

    Supports all three documented session modes:
    - `deepfake`: unknown caller deepfake check without requiring `speaker_id`
    - `deepfake,verify`: registered caller deepfake + Eidos verification
    - `deepfake,enroll`: deepfake + consent-verified Eidos speaker enrollment
    """
    settings = get_settings()
    if not settings.detectif_api_key:
        raise DetectifStreamError("DETECTIF_API_KEY is not configured")
    if checks_mode not in _VALID_CHECKS_MODES:
        raise DetectifStreamError(f"Unsupported checks_mode '{checks_mode}'")
    if checks_mode in {"deepfake,verify", "deepfake,enroll"} and not speaker_id:
        raise DetectifStreamError(f"speaker_id is required when checks_mode is '{checks_mode}'")
    if checks_mode == "deepfake,enroll" and not consent_confirmed:
        raise DetectifStreamError("Explicit speaker consent is required when checks_mode is 'deepfake,enroll'")

    correlation_id = f"corr_{uuid.uuid4().hex}"
    url = _build_stream_ws_url(
        base_url=settings.detectif_base_url,
        call_id=call_id,
        checks_mode=checks_mode,
        speaker_id=speaker_id,
    )
    headers = {
        "Authorization": f"Bearer {settings.detectif_api_key}",
        "X-Correlation-ID": correlation_id,
    }

    window_seconds = settings.rate_limit_window_seconds
    max_msgs_per_window = settings.rate_limit_ws_messages_per_window
    msg_timestamps_start = time.monotonic()
    msg_count = 0

    try:
        logger.info(
            "Opening DetectifAI live stream call_id=%s checks_mode=%s correlation_id=%s",
            call_id,
            checks_mode,
            correlation_id,
        )
        async with websockets.connect(
            url,
            additional_headers=headers,
            open_timeout=settings.detectif_connect_timeout_seconds,
            max_size=2 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=20,
        ) as provider_ws:
            async def provider_to_browser() -> None:
                async for raw_message in provider_ws:
                    if isinstance(raw_message, bytes):
                        continue
                    try:
                        payload = json.loads(raw_message)
                    except json.JSONDecodeError:
                        payload = {"type": "provider_message", "raw": raw_message}
                    if not isinstance(payload, dict):
                        payload = {"type": "provider_message", "raw": payload}
                    if on_provider_message:
                        await on_provider_message(payload)
                    await browser_ws.send_json({"source": "detectifai", **payload})
                    if payload.get("type") == "completed":
                        return

            async def browser_to_provider() -> str:
                nonlocal msg_timestamps_start, msg_count
                while True:
                    message = await browser_ws.receive()
                    if message.get("type") == "websocket.disconnect":
                        return "disconnect"

                    now = time.monotonic()
                    if now - msg_timestamps_start >= window_seconds:
                        msg_timestamps_start = now
                        msg_count = 0
                    msg_count += 1
                    if settings.rate_limit_enabled and msg_count > max_msgs_per_window:
                        await browser_ws.send_json(
                            {"type": "error", "code": "rate_limited", "message": "Audio frame rate limit exceeded"}
                        )
                        continue

                    if message.get("bytes") is not None:
                        chunk = message["bytes"]
                        if len(chunk) > _MAX_AUDIO_FRAME_BYTES:
                            await browser_ws.send_json({"type": "error", "code": "audio_frame_too_large"})
                            continue
                        if chunk:
                            await provider_ws.send(chunk)
                    elif message.get("text") is not None:
                        raw_text = message["text"]
                        if len(raw_text.encode("utf-8")) > _MAX_TEXT_FRAME_BYTES:
                            await browser_ws.send_json({"type": "error", "code": "control_frame_too_large"})
                            continue
                        try:
                            control = json.loads(raw_text)
                        except json.JSONDecodeError:
                            await browser_ws.send_json({"type": "error", "code": "invalid_control_json"})
                            continue
                        if not isinstance(control, dict):
                            await browser_ws.send_json({"type": "error", "code": "invalid_control_message"})
                            continue
                        if control.get("type") == "stop":
                            await provider_ws.send(json.dumps({"type": "stop"}))
                            return "stop"

            receive_task = asyncio.create_task(provider_to_browser())
            send_task = asyncio.create_task(browser_to_provider())
            done, _ = await asyncio.wait(
                {receive_task, send_task}, return_when=asyncio.FIRST_COMPLETED
            )

            if receive_task in done:
                await receive_task
                if not send_task.done():
                    send_task.cancel()
                    await asyncio.gather(send_task, return_exceptions=True)
            else:
                reason = await send_task
                if reason == "stop":
                    # Wait for DetectifAI final `completed` message after client stop signal.
                    try:
                        await asyncio.wait_for(receive_task, timeout=45)
                    except asyncio.TimeoutError:
                        receive_task.cancel()
                        await asyncio.gather(receive_task, return_exceptions=True)
                else:
                    receive_task.cancel()
                    await asyncio.gather(receive_task, return_exceptions=True)
    except ConnectionClosed:
        return
    except DetectifStreamError:
        raise
    except TimeoutError as exc:
        raise DetectifStreamError("Timed out connecting to DetectifAI live stream") from exc
    except Exception as exc:
        logger.warning(
            "DetectifAI stream failed call_id=%s correlation_id=%s error_type=%s",
            call_id,
            correlation_id,
            type(exc).__name__,
        )
        raise DetectifStreamError(f"DetectifAI live stream failed ({type(exc).__name__})") from exc

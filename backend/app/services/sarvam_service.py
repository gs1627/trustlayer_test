from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterable, AsyncIterator
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from app.core.config import Settings, get_settings
from app.schemas.contracts import EvidenceItem


class SarvamService:
    """Sarvam Saaras v4 adapter.

    - transcribe_clip(): short REST clips (Sarvam REST limit: 30 seconds).
    - stream_transcribe(): live mono PCM audio (8/16 kHz) over the realtime WS API.

    For live calls, P1 must tee the same PCM frames it sends to DetectifAI into
    this service. Keep the Sarvam API key on the backend only.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _api_key(self) -> str | None:
        return self.settings.sarvam_api_key

    def _evidence(
        self,
        *,
        call_id: str,
        status: str,
        verdict: str | None,
        is_final: bool,
        details: dict[str, Any],
    ) -> EvidenceItem:
        return EvidenceItem(
            call_id=call_id,
            provider="sarvam",
            model=self.settings.sarvam_model,
            check_type="transcription",
            status=status,
            verdict=verdict,
            is_final=is_final,
            observed_at=datetime.now(timezone.utc),
            details=details,
        )

    async def transcribe_clip(
        self,
        audio: bytes,
        *,
        call_id: str,
        filename: str = "recording.wav",
        content_type: str = "audio/wav",
        language_code: str = "unknown",
    ) -> EvidenceItem:
        """Transcribe a clip of 30 seconds or less; use stream_transcribe for live audio."""
        if not audio:
            return self._evidence(
                call_id=call_id,
                status="inconclusive",
                verdict=None,
                is_final=True,
                details={"error": "empty_audio"},
            )
        api_key = self._api_key()
        if not api_key:
            return self._evidence(
                call_id=call_id,
                status="failed",
                verdict=None,
                is_final=True,
                details={"error": "sarvam_not_configured"},
            )

        url = f"{self.settings.sarvam_base_url.rstrip('/')}/speech-to-text"
        data = {
            "model": self.settings.sarvam_model,
            "mode": "transcribe",
            "language_code": language_code,
        }
        headers = {"api-subscription-key": api_key}

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.sarvam_timeout_seconds, connect=15.0)
            ) as client:
                response = await client.post(
                    url,
                    headers=headers,
                    data=data,
                    files={"file": (filename, audio, content_type)},
                )
            if not response.is_success:
                return self._evidence(
                    call_id=call_id,
                    status="failed",
                    verdict=None,
                    is_final=True,
                    details={
                        "error": "sarvam_http_error",
                        "status_code": response.status_code,
                    },
                )
            payload = response.json()
            if not isinstance(payload, dict):
                return self._evidence(
                    call_id=call_id,
                    status="inconclusive",
                    verdict="invalid_provider_response",
                    is_final=True,
                    details={"error": "sarvam_invalid_response"},
                )
            transcript = str(payload.get("transcript") or "").strip()
            language = payload.get("language_code")
            status = "completed" if transcript else "inconclusive"
            return self._evidence(
                call_id=call_id,
                status=status,
                verdict="transcribed" if transcript else "empty_transcript",
                is_final=True,
                details={
                    "text": transcript,
                    "language": language,
                    "language_probability": payload.get("language_probability"),
                    "request_id": payload.get("request_id"),
                    "mode": "transcribe",
                },
            )
        except (httpx.HTTPError, ValueError) as exc:
            return self._evidence(
                call_id=call_id,
                status="failed",
                verdict=None,
                is_final=True,
                details={"error": "sarvam_request_failed", "error_type": type(exc).__name__},
            )

    async def stream_transcribe(
        self,
        audio_chunks: AsyncIterable[bytes],
        *,
        call_id: str,
        sample_rate: int | None = None,
        encoding: str | None = None,
        stream_type: str = "fast",
    ) -> AsyncIterator[EvidenceItem]:
        """Yield partial/final EvidenceItems from raw mono PCM frames.

        Expected audio: signed 16-bit little-endian mono PCM, 8 kHz or 16 kHz.
        For 16 kHz PCM16, ~3,200-byte frames are about 100 ms. The `fast` stream
        type rejects frames above 16,000 bytes (500 ms).
        """
        api_key = self._api_key()
        if not api_key:
            yield self._evidence(
                call_id=call_id,
                status="failed",
                verdict=None,
                is_final=True,
                details={"error": "sarvam_not_configured"},
            )
            return

        rate = sample_rate or self.settings.sarvam_sample_rate
        audio_encoding = encoding or self.settings.sarvam_encoding
        if rate not in (8000, 16000):
            yield self._evidence(
                call_id=call_id,
                status="inconclusive",
                verdict=None,
                is_final=True,
                details={"error": "unsupported_sample_rate", "sample_rate": rate},
            )
            return

        params = {
            "model": self.settings.sarvam_model,
            "language_code": "auto",
            "stream_type": stream_type,
            "mode": "transcribe",
            "encoding": audio_encoding,
            "sample_rate": str(rate),
        }
        base = self.settings.sarvam_base_url.rstrip("/")
        ws_base = base.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        url = f"{ws_base}/speech-to-text-realtime/ws?{urlencode(params)}"

        try:
            async with websockets.connect(
                url,
                additional_headers={"api-subscription-key": api_key},
                open_timeout=20,
                close_timeout=5,
                max_size=1024 * 1024,
                ping_interval=20,
                ping_timeout=20,
            ) as ws:
                async def send_audio() -> None:
                    try:
                        async for chunk in audio_chunks:
                            if not chunk:
                                continue
                            # Fast stream caps a frame at 500 ms. At 16 kHz mono
                            # PCM16 this is 16,000 bytes; at 8 kHz it is 8,000.
                            max_frame_bytes = rate if stream_type == "fast" else rate * 2
                            frame_bytes = max_frame_bytes - (max_frame_bytes % 2)
                            for offset in range(0, len(chunk), frame_bytes):
                                frame = chunk[offset : offset + frame_bytes]
                                if len(frame) % 2:
                                    raise ValueError("PCM16 audio chunk must contain an even number of bytes")
                                await ws.send(
                                    json.dumps(
                                        {
                                            "event": "audio_input",
                                            "audio": base64.b64encode(frame).decode("ascii"),
                                        }
                                    )
                                )
                    finally:
                        # Flush the stream even if the caller's audio iterator ends or errors.
                        try:
                            await ws.send(json.dumps({"event": "end"}))
                        except ConnectionClosed:
                            pass

                sender = asyncio.create_task(send_audio())
                fatal_error = False
                try:
                    async for raw_message in ws:
                        try:
                            message = json.loads(raw_message)
                        except (TypeError, json.JSONDecodeError):
                            continue

                        event = message.get("event") or message.get("type")
                        if event in {"transcript.partial", "transcript.final"}:
                            text = str(message.get("text") or message.get("transcript") or "").strip()
                            final = event == "transcript.final"
                            yield self._evidence(
                                call_id=call_id,
                                status="completed" if final and text else "pending" if text else "inconclusive",
                                verdict="final" if final else "partial",
                                is_final=final,
                                details={
                                    "text": text,
                                    "language": message.get("language"),
                                    "language_confidence": message.get("language_confidence"),
                                    "event": event,
                                },
                            )
                        elif event == "error":
                            fatal = bool(message.get("is_fatal", True))
                            yield self._evidence(
                                call_id=call_id,
                                status="failed" if fatal else "inconclusive",
                                verdict="provider_error",
                                is_final=fatal,
                                details={
                                    "error": str(message.get("code") or "sarvam_stream_error"),
                                    "message": str(message.get("message") or "Sarvam streaming error")[:300],
                                },
                            )
                            if fatal:
                                fatal_error = True
                                break
                        elif event == "session.end":
                            break

                    if fatal_error:
                        sender.cancel()
                        await asyncio.gather(sender, return_exceptions=True)
                    else:
                        await sender
                finally:
                    if not sender.done():
                        sender.cancel()
                        await asyncio.gather(sender, return_exceptions=True)
        except (ConnectionClosed, OSError, ValueError, httpx.HTTPError) as exc:
            yield self._evidence(
                call_id=call_id,
                status="failed",
                verdict="provider_error",
                is_final=True,
                details={"error": "sarvam_stream_failed", "error_type": type(exc).__name__},
            )
        except Exception as exc:
            # Keep provider/library error text out of the evidence object.
            yield self._evidence(
                call_id=call_id,
                status="failed",
                verdict="provider_error",
                is_final=True,
                details={"error": "sarvam_stream_failed", "error_type": type(exc).__name__},
            )

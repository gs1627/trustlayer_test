from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any

from app.db.models import parse_utc_datetime
from app.schemas.contracts import (
    EvidenceCheckType,
    EvidenceItemCreate,
    EvidenceSourceChannel,
    EvidenceStatus,
)

_SENSITIVE_EXACT_KEYS = frozenset(
    {
        "authorization",
        "auth_header",
        "api_key",
        "apikey",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "auth_token",
        "bearer_token",
        "secret",
        "webhook_secret",
        "signing_secret",
        "client_secret",
        "password",
        "passwd",
        "signature",
        "webhook_signature",
        "private_key",
        "audio",
        "audio_base64",
        "audio_bytes",
        "raw_audio",
        "pcm",
        "pcm16",
        "file_content",
        "wav_bytes",
        "phone",
        "phone_number",
        "caller_number",
        "callee_number",
        "email",
        "email_address",
        "ssn",
        "account_number",
        "card_number",
        "pan",
        "aadhaar",
    }
)
_SENSITIVE_SUFFIXES = (
    "_secret",
    "_password",
    "_api_key",
    "_apikey",
    "_access_token",
    "_refresh_token",
    "_auth_token",
    "_private_key",
)
_INCONCLUSIVE_MARKERS = frozenset(
    {
        "inconclusive",
        "indeterminate",
        "uncertain",
        "insufficient_speech",
        "insufficient_audio",
        "insufficient_context",
        "unknown",
    }
)
_FAILED_STATUS_MARKERS = frozenset({"failed", "error", "errored", "timeout", "cancelled", "canceled"})
_PENDING_STATUS_MARKERS = frozenset({"pending", "processing", "queued", "in_progress", "running"})
_COMPLETED_STATUS_MARKERS = frozenset({"completed", "complete", "succeeded", "success", "done"})
_VALID_EVIDENCE_STATUSES: frozenset[str] = frozenset({"pending", "completed", "failed", "inconclusive"})


class EvidenceMappingError(ValueError):
    """Raised when a provider payload cannot be mapped without guessing or corrupting data."""


def _is_sensitive_key(key: str) -> bool:
    lowered = key.strip().lower()
    if lowered in _SENSITIVE_EXACT_KEYS:
        return True
    return lowered.endswith(_SENSITIVE_SUFFIXES)


def _sanitize_value(value: Any, *, key_hint: str | None = None) -> Any:
    if key_hint and _is_sensitive_key(key_hint):
        return "[REDACTED]"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EvidenceMappingError(f"Non-finite floating-point value in details for '{key_hint or 'value'}'")
        return value
    if isinstance(value, str):
        if key_hint and "audio" in key_hint.lower() and len(value) > 256:
            return "[REDACTED]"
        if len(value) > 16384:
            return value[:16384] + "...[TRUNCATED]"
        return value
    if isinstance(value, (bytes, bytearray)):
        return f"<redacted-bytes:{len(value)}>"
    if isinstance(value, datetime):
        parsed = parse_utc_datetime(value)
        return parsed.isoformat() if parsed is not None else None
    if isinstance(value, dict):
        return {
            str(k): _sanitize_value(v, key_hint=str(k))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item) for item in value]
    return str(value)


def sanitize_evidence_details(details: dict[str, Any] | None) -> dict[str, Any]:
    """Return a copy of provider/evidence metadata with secrets, raw audio, and PII redacted."""
    if details is None:
        return {}
    if not isinstance(details, dict):
        raise EvidenceMappingError("details must be a JSON object")
    sanitized = _sanitize_value(details)
    assert isinstance(sanitized, dict)
    return sanitized


def _require_dict(payload: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise EvidenceMappingError(f"{context} must be a JSON object")
    return payload


def _opt_str(value: Any, *, field_name: str = "field", allow_blank: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise EvidenceMappingError(f"'{field_name}' must be a string when supplied")
    cleaned = value.strip()
    if not cleaned and not allow_blank:
        return None
    return cleaned if allow_blank else cleaned


def _opt_bool(value: Any, *, field_name: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise EvidenceMappingError(f"'{field_name}' must be a boolean when supplied")
    return value


def _opt_int(value: Any, *, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvidenceMappingError(f"'{field_name}' must be an integer when supplied")
    return value


def _opt_finite_float(value: Any, *, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvidenceMappingError(f"'{field_name}' must be numeric when supplied")
    number = float(value)
    if not math.isfinite(number):
        raise EvidenceMappingError(f"'{field_name}' must be finite (NaN/Infinity rejected)")
    return number


def _opt_observed_at(value: Any, *, field_name: str = "observed_at") -> datetime | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise EvidenceMappingError(f"'{field_name}' cannot be a boolean")
    if isinstance(value, (int, float)):
        epoch = float(value)
        if not math.isfinite(epoch):
            raise EvidenceMappingError(f"'{field_name}' epoch timestamp must be finite")
        try:
            return datetime.fromtimestamp(epoch, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise EvidenceMappingError(f"Invalid epoch timestamp for '{field_name}'") from exc
    try:
        return parse_utc_datetime(value)
    except (TypeError, ValueError) as exc:
        raise EvidenceMappingError(f"Invalid timestamp for '{field_name}': {exc}") from exc


def _payload_digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _clamp_source_key(key: str) -> str:
    if len(key) <= 200:
        return key
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    prefix = key[:170]
    return f"{prefix}:{digest}"


def build_source_event_key(
    *,
    source_channel: EvidenceSourceChannel,
    call_id: str,
    check_type: EvidenceCheckType,
    provider_operation_id: str | None = None,
    provider_request_id: str | None = None,
    provider_stream_id: str | None = None,
    event_id: str | None = None,
    delivery_id: str | None = None,
    sequence: int | None = None,
    is_final: bool = False,
    suffix: str | None = None,
    payload: Any = None,
) -> str:
    """Build a deterministic deduplication key within the 200-char DB column limit."""
    if source_channel == "webhook":
        if suffix:
            return _clamp_source_key(f"wh:{suffix}")
        if provider_stream_id and sequence is not None:
            return _clamp_source_key(f"wh:{provider_stream_id}:seq_{sequence}:f_{int(is_final)}")
        if provider_operation_id:
            return _clamp_source_key(f"wh:op:{provider_operation_id}:f_{int(is_final)}")
        if event_id:
            return _clamp_source_key(f"wh:evt:{event_id}")
        if delivery_id:
            return _clamp_source_key(f"wh:del:{delivery_id}")
        return _clamp_source_key(f"wh:{call_id}:{check_type}:h_{_payload_digest(payload)}")

    if source_channel == "websocket":
        scope = provider_stream_id or call_id
        if suffix:
            return _clamp_source_key(f"ws:{scope}:{check_type}:{suffix}")
        if sequence is not None:
            return _clamp_source_key(f"ws:{scope}:{check_type}:seq_{sequence}:f_{int(is_final)}")
        if provider_operation_id:
            return _clamp_source_key(f"ws:{scope}:{check_type}:op:{provider_operation_id}:f_{int(is_final)}")
        return _clamp_source_key(f"ws:{scope}:{check_type}:f_{int(is_final)}:h_{_payload_digest(payload)}")

    if source_channel == "rest":
        if provider_operation_id:
            return _clamp_source_key(f"rest:op:{provider_operation_id}:f_{int(is_final)}")
        if provider_request_id:
            return _clamp_source_key(f"rest:req:{provider_request_id}:f_{int(is_final)}")
        return _clamp_source_key(f"rest:{call_id}:{check_type}:h_{_payload_digest(payload)}")

    # internal channel (Sarvam, Gemini, etc.)
    if provider_operation_id:
        return _clamp_source_key(f"int:op:{provider_operation_id}:f_{int(is_final)}")
    if provider_request_id:
        return _clamp_source_key(f"int:req:{provider_request_id}:f_{int(is_final)}")
    if sequence is not None:
        return _clamp_source_key(f"int:{call_id}:{check_type}:seq_{sequence}:f_{int(is_final)}")
    return _clamp_source_key(f"int:{call_id}:{check_type}:h_{_payload_digest(payload)}")


def _extract_first_score(
    block: dict[str, Any],
    candidates: tuple[tuple[str, str], ...],
) -> tuple[float | None, str | None]:
    for key, semantic_label in candidates:
        if key in block and block[key] is not None:
            return _opt_finite_float(block[key], field_name=key), semantic_label
    return None, None


def _derive_status(
    *,
    explicit_status: str | None,
    has_error: bool,
    verdict: str | None,
    is_final: bool,
) -> EvidenceStatus:
    normalized_status = explicit_status.lower() if explicit_status else None
    normalized_verdict = verdict.lower() if verdict else None

    if has_error or (normalized_status in _FAILED_STATUS_MARKERS):
        return "failed"
    if normalized_status in _INCONCLUSIVE_MARKERS or normalized_verdict in _INCONCLUSIVE_MARKERS:
        return "inconclusive"
    if normalized_status in _PENDING_STATUS_MARKERS:
        return "pending"
    if normalized_status in _COMPLETED_STATUS_MARKERS:
        return "completed"
    if normalized_status is not None:
        if normalized_status in _VALID_EVIDENCE_STATUSES:
            return normalized_status  # type: ignore[return-value]
        raise EvidenceMappingError(f"Unsupported provider status '{explicit_status}'")
    return "completed" if is_final else "pending"


def _unwrap_provider_raw(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("raw")
    if isinstance(raw, dict) and "result" not in payload and "verdict" not in payload and "decision" not in payload:
        merged = {**raw}
        for key in ("request_id", "operation_id"):
            if key not in merged and payload.get(key) is not None:
                merged[key] = payload[key]
        return merged
    return payload


def _build_aletheia_item(
    *,
    call_id: str,
    block: dict[str, Any],
    envelope: dict[str, Any],
    speaker_id: str | None,
    source_channel: EvidenceSourceChannel,
    source_event_key: str | None,
    provider_operation_id: str | None,
    provider_request_id: str | None,
    provider_stream_id: str | None,
    sequence: int | None,
    observed_at: datetime | None,
    is_early: bool | None,
    is_final: bool,
    extra_details: dict[str, Any] | None = None,
    event_id: str | None = None,
    delivery_id: str | None = None,
    key_suffix: str | None = None,
) -> EvidenceItemCreate:
    verdict = _opt_str(block.get("verdict"), field_name="verdict")
    raw_score, score_type = _extract_first_score(
        block,
        (
            ("score", "synthetic_score"),
            ("synthetic_score", "synthetic_score"),
            ("synthetic_risk_score", "synthetic_risk_score"),
            ("confidence", "provider_confidence"),
        ),
    )
    explicit_status = _opt_str(block.get("status"), field_name="status") or _opt_str(
        envelope.get("status"), field_name="status"
    )
    error_obj = block.get("error") if block.get("error") is not None else envelope.get("error")
    has_error = error_obj is not None
    status = _derive_status(
        explicit_status=explicit_status,
        has_error=has_error,
        verdict=verdict,
        is_final=is_final,
    )

    if verdict is None and raw_score is None and explicit_status is None and not has_error:
        raise EvidenceMappingError("Aletheia deepfake payload missing verdict, score, status, and error")

    details_payload = sanitize_evidence_details(
        {
            **block,
            **({"error": error_obj} if error_obj is not None and "error" not in block else {}),
            **(extra_details or {}),
        }
    )

    resolved_key = source_event_key or build_source_event_key(
        source_channel=source_channel,
        call_id=call_id,
        check_type="deepfake",
        provider_operation_id=provider_operation_id,
        provider_request_id=provider_request_id,
        provider_stream_id=provider_stream_id,
        event_id=event_id,
        delivery_id=delivery_id,
        sequence=sequence,
        is_final=is_final,
        suffix=key_suffix,
        payload=envelope,
    )

    return EvidenceItemCreate(
        call_id=call_id,
        speaker_id=speaker_id,
        provider="detectifai",
        model=_opt_str(block.get("model"), field_name="model") or "aletheia",
        check_type="deepfake",
        status=status,
        verdict=verdict,
        raw_score=raw_score,
        score_type=score_type,
        is_early=is_early,
        is_final=is_final,
        source_channel=source_channel,
        source_event_key=resolved_key,
        sequence=sequence,
        provider_operation_id=provider_operation_id,
        provider_request_id=provider_request_id,
        provider_stream_id=provider_stream_id,
        observed_at=observed_at,
        details=details_payload,
    )


def _extract_eidos_verdict(block: dict[str, Any]) -> str | None:
    decision = _opt_str(block.get("decision"), field_name="decision")
    if decision is not None:
        return decision
    verdict = _opt_str(block.get("verdict"), field_name="verdict")
    if verdict is not None:
        return verdict
    status_val = _opt_str(block.get("status"), field_name="status")
    if status_val and status_val.lower() in {"match", "no_match"}:
        return status_val.lower()
    match_val = _opt_bool(block.get("match"), field_name="match")
    if match_val is True:
        return "match"
    if match_val is False:
        return "no_match"
    return None


def _build_eidos_item(
    *,
    call_id: str,
    block: dict[str, Any],
    envelope: dict[str, Any],
    speaker_id: str | None,
    source_channel: EvidenceSourceChannel,
    source_event_key: str | None,
    provider_operation_id: str | None,
    provider_request_id: str | None,
    provider_stream_id: str | None,
    sequence: int | None,
    observed_at: datetime | None,
    is_early: bool | None,
    is_final: bool,
    extra_details: dict[str, Any] | None = None,
    event_id: str | None = None,
    delivery_id: str | None = None,
    key_suffix: str | None = None,
) -> EvidenceItemCreate:
    verdict = _extract_eidos_verdict(block)
    raw_score, score_type = _extract_first_score(
        block,
        (
            ("similarity", "cosine_similarity"),
            ("similarity_score", "similarity_score"),
            ("score", "verification_score"),
        ),
    )
    raw_status = _opt_str(block.get("status"), field_name="status")
    # Some DetectifAI stream.completed verification blocks put "match"/"no_match" in `status`.
    explicit_status = (
        None
        if raw_status and raw_status.lower() in {"match", "no_match"}
        else raw_status or _opt_str(envelope.get("status"), field_name="status")
    )
    error_obj = block.get("error") if block.get("error") is not None else envelope.get("error")
    has_error = error_obj is not None
    status = _derive_status(
        explicit_status=explicit_status,
        has_error=has_error,
        verdict=verdict,
        is_final=is_final,
    )

    resolved_speaker = (
        _opt_str(block.get("speaker_id"), field_name="speaker_id")
        or _opt_str(envelope.get("speaker_id"), field_name="speaker_id")
        or speaker_id
    )

    if verdict is None and raw_score is None and explicit_status is None and not has_error:
        raise EvidenceMappingError("Eidos verification payload missing verdict/decision/match, score, status, and error")

    details_payload = sanitize_evidence_details(
        {
            **{k: v for k, v in block.items() if k not in {"deepfake", "deepfake_result"}},
            **({"error": error_obj} if error_obj is not None and "error" not in block else {}),
            **(extra_details or {}),
        }
    )

    resolved_key = source_event_key or build_source_event_key(
        source_channel=source_channel,
        call_id=call_id,
        check_type="speaker_verification",
        provider_operation_id=provider_operation_id,
        provider_request_id=provider_request_id,
        provider_stream_id=provider_stream_id,
        event_id=event_id,
        delivery_id=delivery_id,
        sequence=sequence,
        is_final=is_final,
        suffix=key_suffix,
        payload=envelope,
    )

    return EvidenceItemCreate(
        call_id=call_id,
        speaker_id=resolved_speaker,
        provider="detectifai",
        model=_opt_str(block.get("model"), field_name="model") or "eidos",
        check_type="speaker_verification",
        status=status,
        verdict=verdict,
        raw_score=raw_score,
        score_type=score_type,
        is_early=is_early,
        is_final=is_final,
        source_channel=source_channel,
        source_event_key=resolved_key,
        sequence=sequence,
        provider_operation_id=provider_operation_id,
        provider_request_id=provider_request_id,
        provider_stream_id=provider_stream_id,
        observed_at=observed_at,
        details=details_payload,
    )


def map_aletheia_rest_result(
    payload: dict[str, Any],
    *,
    call_id: str,
    speaker_id: str | None = None,
    source_channel: EvidenceSourceChannel = "rest",
    source_event_key: str | None = None,
    provider_request_id: str | None = None,
    provider_operation_id: str | None = None,
    provider_stream_id: str | None = None,
    observed_at: datetime | str | int | float | None = None,
) -> EvidenceItemCreate:
    """Normalize a DetectifAI Aletheia REST / operation result into EvidenceItemCreate."""
    data = _unwrap_provider_raw(_require_dict(payload, context="Aletheia REST payload"))
    result_raw = data.get("result")
    if result_raw is not None and not isinstance(result_raw, dict):
        raise EvidenceMappingError("'result' must be a JSON object")
    block = result_raw if isinstance(result_raw, dict) else data

    req_id = _opt_str(data.get("request_id"), field_name="request_id") or provider_request_id
    op_id = _opt_str(data.get("operation_id"), field_name="operation_id") or provider_operation_id
    strm_id = _opt_str(data.get("stream_id"), field_name="stream_id") or provider_stream_id
    obs_dt = _opt_observed_at(
        observed_at if observed_at is not None else (block.get("observed_at") or data.get("created_at")),
        field_name="observed_at",
    )

    is_early = _opt_bool(
        block.get("early") if "early" in block else data.get("early"),
        field_name="early",
    )
    explicit_final = _opt_bool(
        block.get("final") if "final" in block else data.get("final"),
        field_name="final",
    )
    raw_status = (_opt_str(block.get("status"), field_name="status") or _opt_str(data.get("status"), field_name="status"))
    if explicit_final is not None:
        is_final = explicit_final
    elif raw_status and raw_status.lower() in _PENDING_STATUS_MARKERS:
        is_final = False
    else:
        is_final = True

    extra: dict[str, Any] = {}
    if data.get("object") is not None:
        extra["object"] = data["object"]
    if isinstance(result_raw, dict) and data.get("credits") is not None:
        extra["credits"] = data["credits"]

    return _build_aletheia_item(
        call_id=call_id,
        block=block,
        envelope=data,
        speaker_id=_opt_str(data.get("speaker_id"), field_name="speaker_id") or speaker_id,
        source_channel=source_channel,
        source_event_key=source_event_key,
        provider_operation_id=op_id,
        provider_request_id=req_id,
        provider_stream_id=strm_id,
        sequence=_opt_int(block.get("sequence") if "sequence" in block else data.get("sequence"), field_name="sequence"),
        observed_at=obs_dt,
        is_early=is_early,
        is_final=is_final,
        extra_details=extra,
    )


def map_eidos_verify_rest_results(
    payload: dict[str, Any],
    *,
    call_id: str,
    speaker_id: str | None = None,
    source_channel: EvidenceSourceChannel = "rest",
    source_event_key: str | None = None,
    provider_request_id: str | None = None,
    provider_operation_id: str | None = None,
    provider_stream_id: str | None = None,
    observed_at: datetime | str | int | float | None = None,
) -> list[EvidenceItemCreate]:
    """Normalize a DetectifAI Eidos verification REST payload (plus optional nested deepfake)."""
    data = _unwrap_provider_raw(_require_dict(payload, context="Eidos REST payload"))
    result_raw = data.get("result")
    if result_raw is not None and not isinstance(result_raw, dict):
        raise EvidenceMappingError("'result' must be a JSON object")
    block = result_raw if isinstance(result_raw, dict) else data

    req_id = _opt_str(data.get("request_id"), field_name="request_id") or provider_request_id
    op_id = _opt_str(data.get("operation_id"), field_name="operation_id") or provider_operation_id
    strm_id = _opt_str(data.get("stream_id"), field_name="stream_id") or provider_stream_id
    obs_dt = _opt_observed_at(
        observed_at if observed_at is not None else (block.get("observed_at") or data.get("created_at")),
        field_name="observed_at",
    )

    is_early = _opt_bool(
        block.get("early") if "early" in block else data.get("early"),
        field_name="early",
    )
    explicit_final = _opt_bool(
        block.get("final") if "final" in block else data.get("final"),
        field_name="final",
    )
    raw_status = (_opt_str(block.get("status"), field_name="status") or _opt_str(data.get("status"), field_name="status"))
    if explicit_final is not None:
        is_final = explicit_final
    elif raw_status and raw_status.lower() in _PENDING_STATUS_MARKERS:
        is_final = False
    else:
        is_final = True

    extra: dict[str, Any] = {}
    if data.get("object") is not None:
        extra["object"] = data["object"]
    if isinstance(result_raw, dict) and data.get("credits") is not None:
        extra["credits"] = data["credits"]

    eidos_item = _build_eidos_item(
        call_id=call_id,
        block=block,
        envelope=data,
        speaker_id=speaker_id,
        source_channel=source_channel,
        source_event_key=source_event_key,
        provider_operation_id=op_id,
        provider_request_id=req_id,
        provider_stream_id=strm_id,
        sequence=_opt_int(block.get("sequence") if "sequence" in block else data.get("sequence"), field_name="sequence"),
        observed_at=obs_dt,
        is_early=is_early,
        is_final=is_final,
        extra_details=extra,
    )
    items: list[EvidenceItemCreate] = [eidos_item]

    nested_deepfake = None
    for candidate in (block.get("deepfake"), block.get("deepfake_result"), data.get("deepfake"), data.get("deepfake_result")):
        if candidate is not None:
            nested_deepfake = _require_dict(candidate, context="nested deepfake block")
            break

    if nested_deepfake is not None:
        df_early = _opt_bool(nested_deepfake.get("early"), field_name="deepfake.early")
        if df_early is None:
            df_early = is_early
        df_final = _opt_bool(nested_deepfake.get("final"), field_name="deepfake.final")
        if df_final is None:
            df_final = is_final
        df_op_id = _opt_str(nested_deepfake.get("operation_id"), field_name="deepfake.operation_id") or op_id
        df_item = _build_aletheia_item(
            call_id=call_id,
            block=nested_deepfake,
            envelope=data,
            speaker_id=eidos_item.speaker_id,
            source_channel=source_channel,
            source_event_key=f"{source_event_key}:deepfake" if source_event_key else None,
            provider_operation_id=df_op_id,
            provider_request_id=req_id,
            provider_stream_id=strm_id,
            sequence=eidos_item.sequence,
            observed_at=obs_dt,
            is_early=df_early,
            is_final=df_final,
            extra_details={"embedded_in": "speaker.verification", **extra},
        )
        items.append(df_item)

    return items


def map_detectif_websocket_message(
    payload: dict[str, Any],
    *,
    call_id: str,
    speaker_id: str | None = None,
    provider_stream_id: str | None = None,
    observed_at: datetime | str | int | float | None = None,
) -> list[EvidenceItemCreate]:
    """Normalize a DetectifAI WebSocket message (`deepfake`, `verification`, `completed`, etc.)."""
    data = _require_dict(payload, context="DetectifAI WebSocket message")
    msg_type = _opt_str(data.get("type"), field_name="type")
    if msg_type is None:
        raise EvidenceMappingError("DetectifAI WebSocket message requires 'type'")

    if msg_type in {"ready", "provider_message", "pong", "started"}:
        return []

    strm_id = _opt_str(data.get("stream_id"), field_name="stream_id") or provider_stream_id
    req_id = _opt_str(data.get("request_id"), field_name="request_id")
    op_id = _opt_str(data.get("operation_id"), field_name="operation_id")
    seq = _opt_int(data.get("sequence"), field_name="sequence")
    obs_dt = _opt_observed_at(
        observed_at if observed_at is not None else (data.get("observed_at") or data.get("created_at")),
        field_name="observed_at",
    )

    if msg_type == "deepfake":
        result_raw = data.get("result")
        if result_raw is not None and not isinstance(result_raw, dict):
            raise EvidenceMappingError("WebSocket deepfake 'result' must be a JSON object")
        block = result_raw if isinstance(result_raw, dict) else data
        is_early = _opt_bool(
            block.get("early") if "early" in block else data.get("early"),
            field_name="early",
        )
        explicit_final = _opt_bool(
            block.get("final") if "final" in block else data.get("final"),
            field_name="final",
        )
        # Never infer is_final = not is_early on live stream updates.
        is_final = explicit_final if explicit_final is not None else False
        return [
            _build_aletheia_item(
                call_id=call_id,
                block=block,
                envelope=data,
                speaker_id=_opt_str(data.get("speaker_id"), field_name="speaker_id") or speaker_id,
                source_channel="websocket",
                source_event_key=None,
                provider_operation_id=_opt_str(block.get("operation_id"), field_name="operation_id") or op_id,
                provider_request_id=req_id,
                provider_stream_id=strm_id,
                sequence=seq,
                observed_at=obs_dt,
                is_early=is_early,
                is_final=is_final,
                extra_details={"message_type": "deepfake"},
            )
        ]

    if msg_type == "verification":
        result_raw = data.get("result")
        if result_raw is not None and not isinstance(result_raw, dict):
            raise EvidenceMappingError("WebSocket verification 'result' must be a JSON object")
        block = result_raw if isinstance(result_raw, dict) else data
        is_early = _opt_bool(
            block.get("early") if "early" in block else data.get("early"),
            field_name="early",
        )
        explicit_final = _opt_bool(
            block.get("final") if "final" in block else data.get("final"),
            field_name="final",
        )
        is_final = explicit_final if explicit_final is not None else False
        return [
            _build_eidos_item(
                call_id=call_id,
                block=block,
                envelope=data,
                speaker_id=speaker_id,
                source_channel="websocket",
                source_event_key=None,
                provider_operation_id=_opt_str(block.get("operation_id"), field_name="operation_id") or op_id,
                provider_request_id=req_id,
                provider_stream_id=strm_id,
                sequence=seq,
                observed_at=obs_dt,
                is_early=is_early,
                is_final=is_final,
                extra_details={"message_type": "verification"},
            )
        ]

    if msg_type == "completed":
        results = _require_dict(data.get("results"), context="WebSocket completed 'results'")
        stream_meta: dict[str, Any] = {}
        for key in ("seconds", "speech_seconds", "ended_by", "credits", "checks", "duration_seconds"):
            if key in data and data[key] is not None:
                stream_meta[key] = data[key]
        items: list[EvidenceItemCreate] = []

        deepfake_block = results.get("deepfake")
        if deepfake_block is not None:
            df_dict = _require_dict(deepfake_block, context="completed results.deepfake")
            df_early = _opt_bool(df_dict.get("early"), field_name="results.deepfake.early")
            df_final = _opt_bool(df_dict.get("final"), field_name="results.deepfake.final")
            items.append(
                _build_aletheia_item(
                    call_id=call_id,
                    block=df_dict,
                    envelope=data,
                    speaker_id=_opt_str(data.get("speaker_id"), field_name="speaker_id") or speaker_id,
                    source_channel="websocket",
                    source_event_key=None,
                    provider_operation_id=_opt_str(df_dict.get("operation_id"), field_name="operation_id") or op_id,
                    provider_request_id=req_id,
                    provider_stream_id=strm_id,
                    sequence=seq,
                    observed_at=obs_dt,
                    is_early=df_early,
                    is_final=True if df_final is None else df_final,
                    extra_details={"message_type": "completed", **stream_meta},
                    key_suffix="completed",
                )
            )

        verify_block = results.get("verify") if "verify" in results else results.get("verification")
        if verify_block is not None:
            ver_dict = _require_dict(verify_block, context="completed results.verify")
            ver_early = _opt_bool(ver_dict.get("early"), field_name="results.verify.early")
            ver_final = _opt_bool(ver_dict.get("final"), field_name="results.verify.final")
            items.append(
                _build_eidos_item(
                    call_id=call_id,
                    block=ver_dict,
                    envelope=data,
                    speaker_id=speaker_id,
                    source_channel="websocket",
                    source_event_key=None,
                    provider_operation_id=_opt_str(ver_dict.get("operation_id"), field_name="operation_id") or op_id,
                    provider_request_id=req_id,
                    provider_stream_id=strm_id,
                    sequence=seq,
                    observed_at=obs_dt,
                    is_early=ver_early,
                    is_final=True if ver_final is None else ver_final,
                    extra_details={"message_type": "completed", **stream_meta},
                    key_suffix="completed",
                )
            )

        if not items and data.get("error") is None:
            raise EvidenceMappingError("WebSocket 'completed' message contains no recognized check results")
        return items

    if msg_type == "error":
        check_hint = (_opt_str(data.get("check_type"), field_name="check_type") or _opt_str(data.get("check"), field_name="check"))
        error_payload = data.get("error") or {"code": data.get("code"), "message": data.get("message")}
        if check_hint == "deepfake":
            return [
                _build_aletheia_item(
                    call_id=call_id,
                    block={"status": "failed", "error": error_payload},
                    envelope=data,
                    speaker_id=speaker_id,
                    source_channel="websocket",
                    source_event_key=None,
                    provider_operation_id=op_id,
                    provider_request_id=req_id,
                    provider_stream_id=strm_id,
                    sequence=seq,
                    observed_at=obs_dt,
                    is_early=_opt_bool(data.get("early"), field_name="early"),
                    is_final=True,
                    extra_details={"message_type": "error"},
                )
            ]
        if check_hint in {"verify", "verification", "speaker_verification"}:
            return [
                _build_eidos_item(
                    call_id=call_id,
                    block={"status": "failed", "error": error_payload},
                    envelope=data,
                    speaker_id=speaker_id,
                    source_channel="websocket",
                    source_event_key=None,
                    provider_operation_id=op_id,
                    provider_request_id=req_id,
                    provider_stream_id=strm_id,
                    sequence=seq,
                    observed_at=obs_dt,
                    is_early=_opt_bool(data.get("early"), field_name="early"),
                    is_final=True,
                    extra_details={"message_type": "error"},
                )
            ]
        return []

    return []


def map_detectif_webhook_event(
    payload: dict[str, Any],
    *,
    call_id: str | None = None,
    delivery_id: str | None = None,
    speaker_id: str | None = None,
) -> list[EvidenceItemCreate]:
    """Normalize a signed DetectifAI webhook event into EvidenceItemCreate entries."""
    envelope = _require_dict(payload, context="DetectifAI webhook payload")
    event_type = _opt_str(envelope.get("type"), field_name="type")
    if event_type is None:
        raise EvidenceMappingError("DetectifAI webhook event requires 'type'")

    if event_type in {
        "webhook.test",
        "stream.started",
        "speaker.enrolled",
        "speaker.enrollment.completed",
        "enroll.completed",
    }:
        return []

    event_id = _opt_str(envelope.get("id"), field_name="id")
    observed_at = _opt_observed_at(envelope.get("created_at"), field_name="created_at")
    raw_data = envelope.get("data")
    if raw_data is None:
        raw_data = {}
    data = _require_dict(raw_data, context="webhook 'data'")

    resolved_call_id = call_id or _opt_str(data.get("reference"), field_name="data.reference")
    if not resolved_call_id:
        raise EvidenceMappingError(f"Webhook event '{event_type}' cannot be mapped without call_id/data.reference")

    stream_id = _opt_str(data.get("stream_id"), field_name="data.stream_id")
    req_id = _opt_str(data.get("request_id"), field_name="data.request_id")
    op_id = _opt_str(data.get("operation_id"), field_name="data.operation_id")
    resolved_speaker = _opt_str(data.get("speaker_id"), field_name="data.speaker_id") or speaker_id

    if event_type == "stream.deepfake.updated":
        # Priority 2/3 contract: stream.deepfake.updated is always provisional.
        sequence = _opt_int(data.get("sequence"), field_name="data.sequence")
        is_early = _opt_bool(data.get("early"), field_name="data.early")
        extra_meta = {
            k: data[k]
            for k in ("seconds", "speech_seconds")
            if k in data and data[k] is not None
        }
        return [
            _build_aletheia_item(
                call_id=resolved_call_id,
                block=data,
                envelope=envelope,
                speaker_id=resolved_speaker,
                source_channel="webhook",
                source_event_key=None,
                provider_operation_id=op_id,
                provider_request_id=req_id,
                provider_stream_id=stream_id,
                sequence=sequence,
                observed_at=observed_at,
                is_early=is_early,
                is_final=False,
                extra_details={"event_type": event_type, **extra_meta},
                event_id=event_id,
                delivery_id=delivery_id,
            )
        ]

    if event_type == "deepfake.completed":
        result_raw = data.get("result")
        if result_raw is not None and not isinstance(result_raw, dict):
            raise EvidenceMappingError("deepfake.completed 'data.result' must be a JSON object")
        block = result_raw if isinstance(result_raw, dict) else data
        is_early = _opt_bool(
            block.get("early") if "early" in block else data.get("early"),
            field_name="early",
        )
        explicit_final = _opt_bool(
            block.get("final") if "final" in block else data.get("final"),
            field_name="final",
        )
        is_final = True if explicit_final is None else explicit_final
        return [
            _build_aletheia_item(
                call_id=resolved_call_id,
                block=block,
                envelope=envelope,
                speaker_id=resolved_speaker,
                source_channel="webhook",
                source_event_key=None,
                provider_operation_id=_opt_str(block.get("operation_id"), field_name="operation_id") or op_id,
                provider_request_id=req_id,
                provider_stream_id=stream_id,
                sequence=_opt_int(block.get("sequence") if "sequence" in block else data.get("sequence"), field_name="sequence"),
                observed_at=observed_at,
                is_early=is_early,
                is_final=is_final,
                extra_details={"event_type": event_type, **({"object": data["object"]} if "object" in data else {})},
                event_id=event_id,
                delivery_id=delivery_id,
                key_suffix=(
                    f"deepfake_completed:{op_id}"
                    if op_id
                    else f"deepfake_completed:{stream_id}" if stream_id else None
                ),
            )
        ]

    if event_type == "stream.completed":
        results = _require_dict(data.get("results"), context="stream.completed 'data.results'")
        stream_meta = {
            k: data[k]
            for k in ("seconds", "speech_seconds", "ended_by", "ended_reason", "credits", "duration_seconds", "checks_requested")
            if k in data and data[k] is not None
        }
        items: list[EvidenceItemCreate] = []
        deepfake_block = results.get("deepfake")
        if deepfake_block is not None:
            df_dict = _require_dict(deepfake_block, context="stream.completed results.deepfake")
            df_early = _opt_bool(df_dict.get("early"), field_name="results.deepfake.early")
            df_final = _opt_bool(df_dict.get("final"), field_name="results.deepfake.final")
            items.append(
                _build_aletheia_item(
                    call_id=resolved_call_id,
                    block=df_dict,
                    envelope=envelope,
                    speaker_id=resolved_speaker,
                    source_channel="webhook",
                    source_event_key=None,
                    provider_operation_id=_opt_str(df_dict.get("operation_id"), field_name="operation_id") or op_id,
                    provider_request_id=req_id,
                    provider_stream_id=stream_id,
                    sequence=None,
                    observed_at=observed_at,
                    is_early=df_early,
                    is_final=True if df_final is None else df_final,
                    extra_details={"event_type": event_type, **stream_meta},
                    event_id=event_id,
                    delivery_id=delivery_id,
                    key_suffix=f"stream_completed:{stream_id}" if stream_id else None,
                )
            )
        verify_block = results.get("verify") if "verify" in results else results.get("verification")
        if verify_block is not None:
            ver_dict = _require_dict(verify_block, context="stream.completed results.verify")
            ver_early = _opt_bool(ver_dict.get("early"), field_name="results.verify.early")
            ver_final = _opt_bool(ver_dict.get("final"), field_name="results.verify.final")
            items.append(
                _build_eidos_item(
                    call_id=resolved_call_id,
                    block=ver_dict,
                    envelope=envelope,
                    speaker_id=resolved_speaker,
                    source_channel="webhook",
                    source_event_key=None,
                    provider_operation_id=_opt_str(ver_dict.get("operation_id"), field_name="operation_id") or op_id,
                    provider_request_id=req_id,
                    provider_stream_id=stream_id,
                    sequence=None,
                    observed_at=observed_at,
                    is_early=ver_early,
                    is_final=True if ver_final is None else ver_final,
                    extra_details={"event_type": event_type, **stream_meta},
                    event_id=event_id,
                    delivery_id=delivery_id,
                    key_suffix=f"stream_completed:{stream_id}" if stream_id else None,
                )
            )
        if not items:
            raise EvidenceMappingError("stream.completed webhook contains no recognized verification or deepfake results")
        return items

    if event_type in {
        "speaker.verification.completed",
        "speaker.verified",
        "verification.completed",
        "stream.verification.completed",
    }:
        result_raw = data.get("result")
        if result_raw is not None and not isinstance(result_raw, dict):
            raise EvidenceMappingError(f"{event_type} 'data.result' must be a JSON object")
        block = result_raw if isinstance(result_raw, dict) else data
        is_early = _opt_bool(
            block.get("early") if "early" in block else data.get("early"),
            field_name="early",
        )
        explicit_final = _opt_bool(
            block.get("final") if "final" in block else data.get("final"),
            field_name="final",
        )
        is_final = True if explicit_final is None else explicit_final
        eidos_item = _build_eidos_item(
            call_id=resolved_call_id,
            block=block,
            envelope=envelope,
            speaker_id=resolved_speaker,
            source_channel="webhook",
            source_event_key=None,
            provider_operation_id=_opt_str(block.get("operation_id"), field_name="operation_id") or op_id,
            provider_request_id=req_id,
            provider_stream_id=stream_id,
            sequence=_opt_int(block.get("sequence") if "sequence" in block else data.get("sequence"), field_name="sequence"),
            observed_at=observed_at,
            is_early=is_early,
            is_final=is_final,
            extra_details={"event_type": event_type},
            event_id=event_id,
            delivery_id=delivery_id,
        )
        items = [eidos_item]
        nested_df = block.get("deepfake") or block.get("deepfake_result") or data.get("deepfake")
        if nested_df is not None:
            df_dict = _require_dict(nested_df, context="webhook nested deepfake")
            items.append(
                _build_aletheia_item(
                    call_id=resolved_call_id,
                    block=df_dict,
                    envelope=envelope,
                    speaker_id=eidos_item.speaker_id,
                    source_channel="webhook",
                    source_event_key=None,
                    provider_operation_id=_opt_str(df_dict.get("operation_id"), field_name="operation_id") or op_id,
                    provider_request_id=req_id,
                    provider_stream_id=stream_id,
                    sequence=eidos_item.sequence,
                    observed_at=observed_at,
                    is_early=_opt_bool(df_dict.get("early"), field_name="deepfake.early")
                    if "early" in df_dict
                    else is_early,
                    is_final=_opt_bool(df_dict.get("final"), field_name="deepfake.final")
                    if "final" in df_dict
                    else is_final,
                    extra_details={"event_type": event_type, "embedded_in": event_type},
                    event_id=event_id,
                    delivery_id=delivery_id,
                )
            )
        return items

    return []


def map_sarvam_transcription(
    payload: dict[str, Any],
    *,
    call_id: str,
    model: str | None = None,
    speaker_id: str | None = None,
    source_channel: EvidenceSourceChannel = "internal",
    source_event_key: str | None = None,
    observed_at: datetime | str | int | float | None = None,
) -> EvidenceItemCreate:
    """Normalize a Sarvam transcription result supplied by Member 3 without inventing optional fields."""
    data = _require_dict(payload, context="Sarvam transcription payload")
    resolved_model = _opt_str(data.get("model"), field_name="model") or _opt_str(model, field_name="model")
    if not resolved_model:
        raise EvidenceMappingError("Sarvam transcription payload requires explicit 'model' identifier")

    transcript_supplied = "transcript" in data and data["transcript"] is not None
    transcript = _opt_str(data.get("transcript"), field_name="transcript", allow_blank=True)

    language = _opt_str(data.get("language"), field_name="language")
    language_code = _opt_str(data.get("language_code"), field_name="language_code")
    resolved_language = language or language_code

    lang_prob = _opt_finite_float(data.get("language_probability"), field_name="language_probability")
    if lang_prob is not None and not (0.0 <= lang_prob <= 1.0):
        raise EvidenceMappingError("'language_probability' must be between 0.0 and 1.0")

    timestamps = data.get("timestamps")
    if timestamps is not None and not isinstance(timestamps, (dict, list)):
        raise EvidenceMappingError("'timestamps' must be a JSON object or array when supplied")

    error_obj = data.get("error")
    explicit_status = _opt_str(data.get("status"), field_name="status")
    is_early = _opt_bool(
        data.get("is_early") if "is_early" in data else data.get("early"),
        field_name="is_early",
    )
    explicit_final = _opt_bool(
        data.get("is_final") if "is_final" in data else data.get("final"),
        field_name="is_final",
    )

    if explicit_status is None and error_obj is None and not transcript_supplied:
        raise EvidenceMappingError("Sarvam transcription payload must provide 'transcript', 'status', or 'error'")

    if explicit_final is not None:
        is_final = explicit_final
    elif explicit_status and explicit_status.lower() in _PENDING_STATUS_MARKERS:
        is_final = False
    else:
        is_final = True

    status = _derive_status(
        explicit_status=explicit_status,
        has_error=error_obj is not None,
        verdict=None,
        is_final=is_final,
    )

    req_id = _opt_str(data.get("provider_request_id") or data.get("request_id"), field_name="request_id")
    op_id = _opt_str(data.get("provider_operation_id") or data.get("operation_id"), field_name="operation_id")
    strm_id = _opt_str(data.get("provider_stream_id") or data.get("stream_id"), field_name="stream_id")
    seq = _opt_int(data.get("sequence"), field_name="sequence")
    obs_dt = _opt_observed_at(
        observed_at if observed_at is not None else (data.get("observed_at") or data.get("created_at")),
        field_name="observed_at",
    )

    details: dict[str, Any] = {}
    if transcript_supplied:
        details["transcript"] = transcript
    if resolved_language is not None:
        details["language"] = resolved_language
    if language_code is not None:
        details["language_code"] = language_code
    if lang_prob is not None:
        details["language_probability"] = lang_prob
    if timestamps is not None:
        details["timestamps"] = timestamps
    if error_obj is not None:
        details["error"] = error_obj
    for passthrough_key in ("mode", "duration_seconds", "chunk_id", "metadata"):
        if passthrough_key in data and data[passthrough_key] is not None:
            details[passthrough_key] = data[passthrough_key]

    resolved_key = (
        _opt_str(data.get("source_event_key"), field_name="source_event_key")
        or source_event_key
        or build_source_event_key(
            source_channel=source_channel,
            call_id=call_id,
            check_type="transcription",
            provider_operation_id=op_id,
            provider_request_id=req_id,
            provider_stream_id=strm_id,
            sequence=seq,
            is_final=is_final,
            payload=data,
        )
    )

    return EvidenceItemCreate(
        call_id=call_id,
        speaker_id=_opt_str(data.get("speaker_id"), field_name="speaker_id") or speaker_id,
        provider="sarvam",
        model=resolved_model,
        check_type="transcription",
        status=status,
        verdict=_opt_str(data.get("verdict"), field_name="verdict"),
        raw_score=lang_prob,
        score_type="language_probability" if lang_prob is not None else None,
        is_early=is_early,
        is_final=is_final,
        source_channel=source_channel,
        source_event_key=resolved_key,
        sequence=seq,
        provider_operation_id=op_id,
        provider_request_id=req_id,
        provider_stream_id=strm_id,
        observed_at=obs_dt,
        details=sanitize_evidence_details(details),
    )


def map_gemini_context(
    payload: dict[str, Any],
    *,
    call_id: str,
    model: str | None = None,
    speaker_id: str | None = None,
    source_channel: EvidenceSourceChannel = "internal",
    source_event_key: str | None = None,
    observed_at: datetime | str | int | float | None = None,
) -> EvidenceItemCreate:
    """Normalize Member 3's Gemini contextual analysis output without inventing fields."""
    data = _require_dict(payload, context="Gemini context payload")
    resolved_model = _opt_str(data.get("model"), field_name="model") or _opt_str(model, field_name="model")
    if not resolved_model:
        raise EvidenceMappingError("Gemini context payload requires explicit 'model' identifier")

    risk_label = (
        _opt_str(data.get("risk_label"), field_name="risk_label")
        or _opt_str(data.get("contextual_risk_label"), field_name="contextual_risk_label")
        or _opt_str(data.get("verdict"), field_name="verdict")
        or _opt_str(data.get("label"), field_name="label")
    )
    cues = data.get("cues")
    if cues is None and "risk_cues" in data:
        cues = data.get("risk_cues")
    if cues is not None and not isinstance(cues, list):
        raise EvidenceMappingError("'cues' must be a list when supplied")

    reasoning_summary = (
        _opt_str(data.get("reasoning_summary"), field_name="reasoning_summary")
        or _opt_str(data.get("reasoning"), field_name="reasoning")
        or _opt_str(data.get("summary"), field_name="summary")
    )
    error_obj = data.get("error")
    explicit_status = _opt_str(data.get("status"), field_name="status")

    if (
        explicit_status is None
        and error_obj is None
        and risk_label is None
        and cues is None
        and reasoning_summary is None
    ):
        raise EvidenceMappingError(
            "Gemini context payload must supply status, error, risk_label, cues, or reasoning_summary"
        )

    is_early = _opt_bool(
        data.get("is_early") if "is_early" in data else data.get("early"),
        field_name="is_early",
    )
    explicit_final = _opt_bool(
        data.get("is_final") if "is_final" in data else data.get("final"),
        field_name="is_final",
    )
    if explicit_final is not None:
        is_final = explicit_final
    elif explicit_status and explicit_status.lower() in _PENDING_STATUS_MARKERS:
        is_final = False
    else:
        is_final = True

    status = _derive_status(
        explicit_status=explicit_status,
        has_error=error_obj is not None,
        verdict=risk_label,
        is_final=is_final,
    )

    raw_score, score_type = _extract_first_score(
        data,
        (
            ("risk_score", "contextual_risk_score"),
            ("raw_score", _opt_str(data.get("score_type"), field_name="score_type") or "contextual_score"),
            ("confidence", "model_confidence"),
        ),
    )

    req_id = _opt_str(data.get("provider_request_id") or data.get("request_id"), field_name="request_id")
    op_id = _opt_str(data.get("provider_operation_id") or data.get("operation_id"), field_name="operation_id")
    strm_id = _opt_str(data.get("provider_stream_id") or data.get("stream_id"), field_name="stream_id")
    seq = _opt_int(data.get("sequence"), field_name="sequence")
    obs_dt = _opt_observed_at(
        observed_at if observed_at is not None else (data.get("observed_at") or data.get("created_at")),
        field_name="observed_at",
    )

    details: dict[str, Any] = {}
    if risk_label is not None:
        details["risk_label"] = risk_label
    if cues is not None:
        details["cues"] = cues
    if reasoning_summary is not None:
        details["reasoning_summary"] = reasoning_summary
    if error_obj is not None:
        details["error"] = error_obj
    for meta_key in ("model_metadata", "prompt_version", "finish_reason", "usage_metadata", "latency_ms", "transcript_ref"):
        if meta_key in data and data[meta_key] is not None:
            details[meta_key] = data[meta_key]

    resolved_key = (
        _opt_str(data.get("source_event_key"), field_name="source_event_key")
        or source_event_key
        or build_source_event_key(
            source_channel=source_channel,
            call_id=call_id,
            check_type="context",
            provider_operation_id=op_id,
            provider_request_id=req_id,
            provider_stream_id=strm_id,
            sequence=seq,
            is_final=is_final,
            payload=data,
        )
    )

    return EvidenceItemCreate(
        call_id=call_id,
        speaker_id=_opt_str(data.get("speaker_id"), field_name="speaker_id") or speaker_id,
        provider="gemini",
        model=resolved_model,
        check_type="context",
        status=status,
        verdict=risk_label,
        raw_score=raw_score,
        score_type=score_type,
        is_early=is_early,
        is_final=is_final,
        source_channel=source_channel,
        source_event_key=resolved_key,
        sequence=seq,
        provider_operation_id=op_id,
        provider_request_id=req_id,
        provider_stream_id=strm_id,
        observed_at=obs_dt,
        details=sanitize_evidence_details(details),
    )


def map_provider_evidence(
    *,
    provider: str,
    payload: dict[str, Any],
    call_id: str,
    source_channel: EvidenceSourceChannel = "internal",
    speaker_id: str | None = None,
    provider_stream_id: str | None = None,
    delivery_id: str | None = None,
    model: str | None = None,
    source_event_key: str | None = None,
    observed_at: datetime | str | int | float | None = None,
) -> list[EvidenceItemCreate]:
    """Unified provider normalization dispatcher across DetectifAI, Sarvam, and Gemini."""
    normalized_provider = provider.strip().lower()
    if normalized_provider == "detectifai":
        if source_channel == "webhook":
            return map_detectif_webhook_event(
                payload,
                call_id=call_id,
                delivery_id=delivery_id,
                speaker_id=speaker_id,
            )
        if source_channel == "websocket":
            return map_detectif_websocket_message(
                payload,
                call_id=call_id,
                speaker_id=speaker_id,
                provider_stream_id=provider_stream_id,
                observed_at=observed_at,
            )
        unwrapped = _unwrap_provider_raw(_require_dict(payload, context="DetectifAI REST payload"))
        result_block = unwrapped.get("result") if isinstance(unwrapped.get("result"), dict) else unwrapped
        obj_type = (_opt_str(unwrapped.get("object"), field_name="object") or "").lower()
        if (
            "verification" in obj_type
            or "decision" in result_block
            or "similarity" in result_block
            or "similarity_score" in result_block
            or "match" in result_block
        ):
            return map_eidos_verify_rest_results(
                unwrapped,
                call_id=call_id,
                speaker_id=speaker_id,
                source_channel=source_channel,
                source_event_key=source_event_key,
                provider_stream_id=provider_stream_id,
                observed_at=observed_at,
            )
        return [
            map_aletheia_rest_result(
                unwrapped,
                call_id=call_id,
                speaker_id=speaker_id,
                source_channel=source_channel,
                source_event_key=source_event_key,
                provider_stream_id=provider_stream_id,
                observed_at=observed_at,
            )
        ]

    if normalized_provider == "sarvam":
        return [
            map_sarvam_transcription(
                payload,
                call_id=call_id,
                model=model,
                speaker_id=speaker_id,
                source_channel=source_channel,
                source_event_key=source_event_key,
                observed_at=observed_at,
            )
        ]

    if normalized_provider == "gemini":
        return [
            map_gemini_context(
                payload,
                call_id=call_id,
                model=model,
                speaker_id=speaker_id,
                source_channel=source_channel,
                source_event_key=source_event_key,
                observed_at=observed_at,
            )
        ]

    raise EvidenceMappingError(f"Unsupported evidence provider '{provider}'")

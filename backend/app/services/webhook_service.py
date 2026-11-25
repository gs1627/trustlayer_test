from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
import logging
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import (
    CallSession,
    SpeakerProfile,
    WebhookEvent,
    safe_parse_utc_datetime,
    utc_now,
)
from app.schemas.contracts import EvidenceItemRead, WebhookReconcileResponse
from app.services.events import get_event_publisher, publish_evidence_added, publish_status_changed
from app.services.evidence_mapper import EvidenceMappingError, map_detectif_webhook_event
from app.services.evidence_repository import EvidenceRepository
from app.services.provider_operation_repository import ProviderOperationRepository

logger = logging.getLogger(__name__)

_WEBHOOK_EVIDENCE_EVENTS = frozenset(
    {
        "stream.deepfake.updated",
        "deepfake.completed",
        "stream.completed",
        "speaker.verification.completed",
        "speaker.verified",
        "verification.completed",
        "stream.verification.completed",
    }
)
_SUPPORTED_LIFECYCLE_EVENTS = _WEBHOOK_EVIDENCE_EVENTS | {
    "webhook.test",
    "stream.started",
    "speaker.enrolled",
    "speaker.enrollment.completed",
    "enroll.completed",
}


@dataclass
class WebhookIngestResult:
    duplicate: bool
    status: str
    call_id: str | None
    event: WebhookEvent
    created_evidence: list[EvidenceItemRead] = field(default_factory=list)
    status_transition: tuple[str, str] | None = None


def _extract_reference_and_stream(data: dict[str, Any]) -> tuple[str | None, str | None, str | None, str | None]:
    ref = data.get("reference")
    stream_id = data.get("stream_id")
    op_id = data.get("operation_id")
    speaker_id = data.get("speaker_id")
    return (
        ref.strip() if isinstance(ref, str) and ref.strip() else None,
        stream_id.strip() if isinstance(stream_id, str) and stream_id.strip() else None,
        op_id.strip() if isinstance(op_id, str) and op_id.strip() else None,
        speaker_id.strip() if isinstance(speaker_id, str) and speaker_id.strip() else None,
    )


async def _find_target_call_session(
    db: AsyncSession,
    *,
    reference: str | None,
    stream_id: str | None,
) -> CallSession | None:
    if reference:
        session = await db.get(CallSession, reference)
        if session is not None:
            return session
    if stream_id:
        return await db.scalar(select(CallSession).where(CallSession.provider_stream_id == stream_id))
    return None


def _update_session_state_from_webhook(
    session: CallSession,
    *,
    event_type: str,
    data: dict[str, Any],
    incoming_dt,
) -> tuple[str, str] | None:
    prior_status = session.status
    current_dt = safe_parse_utc_datetime(session.last_provider_event_at)
    is_newer = True
    if incoming_dt is not None and current_dt is not None:
        is_newer = incoming_dt >= current_dt

    if data.get("stream_id") and (is_newer or not session.provider_stream_id):
        session.provider_stream_id = str(data["stream_id"])

    if event_type == "stream.started":
        # Out-of-order guard: never regress completed/ended sessions back to active.
        if session.status not in {"completed", "ended", "disconnected"}:
            session.status = "active"
    elif event_type == "stream.completed":
        if session.status != "ended":
            session.status = "completed"
    elif event_type == "stream.deepfake.updated":
        raw_seq = data.get("sequence")
        if type(raw_seq) is int and raw_seq > session.last_deepfake_sequence:
            session.last_deepfake_sequence = raw_seq

    if is_newer and incoming_dt is not None:
        session.last_provider_event_at = incoming_dt
    elif current_dt is None:
        session.last_provider_event_at = utc_now()

    if session.status != prior_status:
        return (prior_status, session.status)
    return None


async def _sync_speaker_enrollment_from_webhook(
    db: AsyncSession,
    *,
    speaker_id: str | None,
    call_session: CallSession | None,
    data: dict[str, Any],
) -> None:
    resolved_speaker = speaker_id or (call_session.speaker_id if call_session is not None else None)
    if not resolved_speaker:
        return
    profile = await db.get(SpeakerProfile, resolved_speaker)
    if profile is None:
        return
    result_block = data.get("result") if isinstance(data.get("result"), dict) else data
    raw_status = str(result_block.get("status") or data.get("status") or "enrolled").strip().lower()
    now = utc_now()
    if raw_status in {"failed", "error"}:
        if profile.enrollment_status != "enrolled":
            profile.enrollment_status = "failed"
    else:
        profile.enrollment_status = "enrolled"
        sample_cnt = result_block.get("sample_count")
        if type(sample_cnt) is int and sample_cnt >= 0:
            profile.sample_count = max(profile.sample_count, sample_cnt)
        else:
            profile.sample_count = max(profile.sample_count, 1)
    profile.updated_at = now


async def _process_webhook_inner(
    db: AsyncSession,
    *,
    event: WebhookEvent,
    payload: dict[str, Any],
    incoming_dt,
) -> tuple[str, str | None, list[EvidenceItemRead], tuple[str, str] | None, str | None]:
    """Process event inside caller transaction/savepoint; returns outcome metadata."""
    event_type = str(payload.get("type") or "unknown")
    raw_data = payload.get("data")
    data = raw_data if isinstance(raw_data, dict) else {}
    reference, stream_id, op_id, speaker_id = _extract_reference_and_stream(data)
    call_session = await _find_target_call_session(db, reference=reference, stream_id=stream_id)
    resolved_call_id = call_session.call_id if call_session is not None else reference

    if event_type == "webhook.test":
        return "processed", resolved_call_id, [], None, None

    created_evidence: list[EvidenceItemRead] = []
    status_transition: tuple[str, str] | None = None

    if call_session is not None:
        if event_type in {"stream.started", "stream.completed", "stream.deepfake.updated"}:
            status_transition = _update_session_state_from_webhook(
                call_session,
                event_type=event_type,
                data=data,
                incoming_dt=incoming_dt,
            )

        has_evidence_fields = event_type != "stream.deepfake.updated" or any(
            k in data
            for k in (
                "verdict",
                "score",
                "synthetic_score",
                "synthetic_risk_score",
                "confidence",
                "status",
                "error",
                "result",
            )
        )
        if event_type in _WEBHOOK_EVIDENCE_EVENTS and has_evidence_fields:
            mapped_items = map_detectif_webhook_event(
                payload,
                call_id=call_session.call_id,
                delivery_id=event.delivery_id,
                speaker_id=call_session.speaker_id,
            )
            for mapped in mapped_items:
                saved_item, created = await EvidenceRepository.create(
                    db,
                    call_id=call_session.call_id,
                    payload=mapped,
                    commit=False,
                )
                if created:
                    created_evidence.append(EvidenceItemRead.model_validate(saved_item))

        if event_type in {"speaker.enrolled", "speaker.enrollment.completed", "enroll.completed"}:
            await _sync_speaker_enrollment_from_webhook(
                db,
                speaker_id=speaker_id,
                call_session=call_session,
                data=data,
            )
        elif event_type == "stream.completed":
            results = data.get("results") if isinstance(data.get("results"), dict) else {}
            if isinstance(results.get("enroll"), dict):
                await _sync_speaker_enrollment_from_webhook(
                    db,
                    speaker_id=speaker_id,
                    call_session=call_session,
                    data=results["enroll"],
                )

    if op_id:
        op_payload: dict[str, Any] = {
            **data,
            "operation_id": op_id,
            "status": (
                "failed"
                if str(data.get("status") or "").lower() in {"failed", "error"}
                else "succeeded"
            ),
        }
        await ProviderOperationRepository.sync_from_provider_payload(
            db,
            operation_id=op_id,
            payload=op_payload,
            commit=False,
        )

    if event_type in _WEBHOOK_EVIDENCE_EVENTS and call_session is None:
        if reference is not None:
            return (
                "unmatched",
                reference,
                [],
                None,
                f"Call session '{reference}' does not exist yet",
            )
        # Standalone non-stream operation webhook without a call reference.
        if op_id:
            return "processed", None, [], None, None
        return "unmatched", None, [], None, f"No call reference available for '{event_type}'"

    if event_type in {"stream.started", "speaker.enrolled", "speaker.enrollment.completed", "enroll.completed"} and call_session is None:
        if event_type in {"speaker.enrolled", "speaker.enrollment.completed", "enroll.completed"} and speaker_id:
            profile = await db.get(SpeakerProfile, speaker_id)
            if profile is not None:
                await _sync_speaker_enrollment_from_webhook(
                    db,
                    speaker_id=speaker_id,
                    call_session=None,
                    data=data,
                )
                return "processed", reference, [], None, None
        if reference or speaker_id:
            return (
                "unmatched",
                reference,
                [],
                None,
                f"Target session/profile not found for '{event_type}'",
            )

    return "processed", resolved_call_id, created_evidence, status_transition, None


async def _publish_post_commit(
    *,
    call_id: str | None,
    status_transition: tuple[str, str] | None,
    created_evidence: list[EvidenceItemRead],
) -> None:
    publisher = get_event_publisher()
    if status_transition is not None and call_id:
        await publish_status_changed(
            publisher,
            call_id=call_id,
            previous_status=status_transition[0],
            status=status_transition[1],
        )
    for read_item in created_evidence:
        await publish_evidence_added(publisher, item=read_item)


async def ingest_webhook_event(
    db: AsyncSession,
    *,
    delivery_id: str,
    payload: dict[str, Any],
) -> WebhookIngestResult:
    """Persist, verify idempotency, reconcile, and normalize a DetectifAI webhook safely."""
    settings = get_settings()
    now = utc_now()
    incoming_dt = safe_parse_utc_datetime(payload.get("created_at"))
    event_id = payload.get("id")
    raw_data = payload.get("data")
    data = raw_data if isinstance(raw_data, dict) else {}
    reference, _, _, _ = _extract_reference_and_stream(data)

    existing = await db.scalar(
        select(WebhookEvent).where(WebhookEvent.delivery_id == delivery_id)
    )
    if existing is None and isinstance(event_id, str) and event_id.strip():
        processed_same_event = await db.scalar(
            select(WebhookEvent).where(
                WebhookEvent.event_id == event_id.strip(),
                WebhookEvent.status == "processed",
            )
        )
        if processed_same_event is not None:
            return WebhookIngestResult(
                duplicate=True,
                status=processed_same_event.status,
                call_id=processed_same_event.call_id,
                event=processed_same_event,
            )

    if existing is not None:
        if existing.status in {"processed", "unmatched", "dead_letter"}:
            return WebhookIngestResult(
                duplicate=True,
                status=existing.status,
                call_id=existing.call_id,
                event=existing,
            )
        # Retryable `failed` or stale `received` delivery: re-attempt safely.
        event = existing
        event.attempt_count += 1
        event.last_attempt_at = now
    else:
        event = WebhookEvent(
            delivery_id=delivery_id,
            event_id=event_id.strip() if isinstance(event_id, str) and event_id.strip() else None,
            event_type=str(payload.get("type") or "unknown"),
            call_id=reference,
            event_created_at=incoming_dt,
            payload=payload,
            status="received",
            attempt_count=1,
            received_at=now,
            last_attempt_at=now,
        )
        db.add(event)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            winner = await db.scalar(select(WebhookEvent).where(WebhookEvent.delivery_id == delivery_id))
            assert winner is not None
            return WebhookIngestResult(
                duplicate=True,
                status=winner.status,
                call_id=winner.call_id,
                event=winner,
            )

    created_evidence: list[EvidenceItemRead] = []
    status_transition: tuple[str, str] | None = None
    resolved_call_id: str | None = reference

    try:
        async with db.begin_nested():
            outcome, resolved_call_id, created_evidence, status_transition, error_note = (
                await _process_webhook_inner(
                    db,
                    event=event,
                    payload=payload,
                    incoming_dt=incoming_dt,
                )
            )
            event.call_id = resolved_call_id or event.call_id
            if outcome == "processed":
                event.status = "processed"
                event.processed_at = now
                event.processing_error = None
                event.next_retry_at = None
            elif outcome == "unmatched":
                event.status = "unmatched"
                event.processing_error = error_note
                delay = settings.webhook_retry_base_seconds * (2 ** min(event.attempt_count - 1, 5))
                event.next_retry_at = now + timedelta(seconds=delay)
    except (EvidenceMappingError, Exception) as exc:
        logger.warning(
            "Webhook processing failed delivery_id=%s type=%s attempt=%d: %s",
            delivery_id,
            event.event_type,
            event.attempt_count,
            exc,
        )
        created_evidence = []
        status_transition = None
        event.processing_error = f"{type(exc).__name__}: {exc}"[:2000]
        if event.attempt_count >= settings.webhook_max_attempts:
            event.status = "dead_letter"
            event.dead_lettered_at = now
            event.next_retry_at = None
        else:
            event.status = "failed"
            delay = settings.webhook_retry_base_seconds * (2 ** min(event.attempt_count - 1, 5))
            event.next_retry_at = now + timedelta(seconds=delay)

    await db.commit()
    await db.refresh(event)

    if event.status == "processed":
        await _publish_post_commit(
            call_id=resolved_call_id,
            status_transition=status_transition,
            created_evidence=created_evidence,
        )

    return WebhookIngestResult(
        duplicate=False,
        status=event.status,
        call_id=event.call_id,
        event=event,
        created_evidence=created_evidence,
        status_transition=status_transition,
    )


async def store_webhook_event(
    db: AsyncSession,
    *,
    delivery_id: str,
    payload: dict[str, Any],
) -> bool:
    """Backward-compatible wrapper returning True when delivery was already recorded."""
    result = await ingest_webhook_event(db, delivery_id=delivery_id, payload=payload)
    return result.duplicate


async def reprocess_webhook_event(
    db: AsyncSession,
    *,
    event: WebhookEvent,
    force: bool = False,
) -> tuple[str, list[EvidenceItemRead], tuple[str, str] | None]:
    """Re-attempt processing for an existing WebhookEvent safely under a savepoint."""
    settings = get_settings()
    if event.status == "processed" and not force:
        return "processed", [], None
    if event.status == "dead_letter" and not force:
        return "dead_letter", [], None

    now = utc_now()
    event.attempt_count += 1
    event.last_attempt_at = now
    payload = event.payload or {}
    incoming_dt = event.event_created_at or safe_parse_utc_datetime(payload.get("created_at"))
    created_evidence: list[EvidenceItemRead] = []
    status_transition: tuple[str, str] | None = None
    resolved_call_id = event.call_id

    try:
        async with db.begin_nested():
            outcome, resolved_call_id, created_evidence, status_transition, error_note = (
                await _process_webhook_inner(
                    db,
                    event=event,
                    payload=payload,
                    incoming_dt=incoming_dt,
                )
            )
            event.call_id = resolved_call_id or event.call_id
            if outcome == "processed":
                event.status = "processed"
                event.processed_at = now
                event.processing_error = None
                event.next_retry_at = None
                event.dead_lettered_at = None
            else:
                event.processing_error = error_note
                if event.attempt_count >= settings.webhook_max_attempts and not force:
                    event.status = "dead_letter"
                    event.dead_lettered_at = now
                    event.next_retry_at = None
                else:
                    event.status = "unmatched"
                    delay = settings.webhook_retry_base_seconds * (2 ** min(event.attempt_count - 1, 5))
                    event.next_retry_at = now + timedelta(seconds=delay)
    except Exception as exc:
        created_evidence = []
        status_transition = None
        event.processing_error = f"{type(exc).__name__}: {exc}"[:2000]
        if event.attempt_count >= settings.webhook_max_attempts and not force:
            event.status = "dead_letter"
            event.dead_lettered_at = now
            event.next_retry_at = None
        else:
            event.status = "failed"
            delay = settings.webhook_retry_base_seconds * (2 ** min(event.attempt_count - 1, 5))
            event.next_retry_at = now + timedelta(seconds=delay)

    return event.status, created_evidence, status_transition


async def reconcile_pending_webhooks(
    db: AsyncSession,
    *,
    call_id: str | None = None,
    limit: int = 50,
) -> WebhookReconcileResponse:
    """Reconcile unmatched and failed (non-dead-lettered) webhook deliveries."""
    conditions = [
        or_(WebhookEvent.status == "unmatched", WebhookEvent.status == "failed"),
        WebhookEvent.dead_lettered_at.is_(None),
    ]
    if call_id is not None:
        conditions.append(WebhookEvent.call_id == call_id)

    rows = (
        await db.scalars(
            select(WebhookEvent)
            .where(and_(*conditions))
            .order_by(WebhookEvent.received_at.asc(), WebhookEvent.id.asc())
            .limit(limit)
        )
    ).all()

    summary = WebhookReconcileResponse()
    pending_publications: list[tuple[str | None, tuple[str, str] | None, list[EvidenceItemRead]]] = []

    for row in rows:
        summary.attempted += 1
        outcome, created_ev, transition = await reprocess_webhook_event(db, event=row, force=False)
        if outcome == "processed":
            summary.processed += 1
            pending_publications.append((row.call_id, transition, created_ev))
        elif outcome == "unmatched":
            summary.still_unmatched += 1
        elif outcome == "dead_letter":
            summary.dead_lettered += 1
        else:
            summary.failed += 1

    await db.commit()

    for cid, trans, ev_list in pending_publications:
        await _publish_post_commit(call_id=cid, status_transition=trans, created_evidence=ev_list)

    return summary


async def reprocess_and_publish_webhook_event(
    db: AsyncSession,
    *,
    event: WebhookEvent,
    force: bool = True,
) -> WebhookEvent:
    """Reprocess a single WebhookEvent, commit, and publish resulting domain events."""
    outcome, created_evidence, transition = await reprocess_webhook_event(db, event=event, force=force)
    await db.commit()
    await db.refresh(event)
    if outcome == "processed":
        await _publish_post_commit(
            call_id=event.call_id,
            status_transition=transition,
            created_evidence=created_evidence,
        )
    return event


async def list_webhook_events(
    db: AsyncSession,
    *,
    status: str | None = None,
    call_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[WebhookEvent], int]:
    conditions = []
    if status is not None:
        conditions.append(WebhookEvent.status == status)
    if call_id is not None:
        conditions.append(WebhookEvent.call_id == call_id)
    where_clause = and_(*conditions) if conditions else None

    count_stmt = select(func.count()).select_from(WebhookEvent)
    list_stmt = select(WebhookEvent)
    if where_clause is not None:
        count_stmt = count_stmt.where(where_clause)
        list_stmt = list_stmt.where(where_clause)

    total = int(await db.scalar(count_stmt) or 0)
    rows = (
        await db.scalars(
            list_stmt.order_by(WebhookEvent.received_at.desc(), WebhookEvent.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return list(rows), total

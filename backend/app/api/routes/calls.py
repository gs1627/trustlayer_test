import asyncio
import logging

from fastapi import APIRouter, Body, Depends, Query, Response, WebSocket, WebSocketDisconnect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    AuthPrincipal,
    authorize_call_access,
    require_backend_access,
    require_roles,
    resolve_websocket_principal,
)
from app.core.config import get_settings
from app.core.errors import AppAPIError
from app.core.rate_limit import (
    get_rate_limiter,
    get_ws_connection_tracker,
    rate_limit,
)
from app.db.models import CallSession, SpeakerProfile, utc_now
from app.db.session import AsyncSessionLocal, get_db
from app.schemas.contracts import (
    CallSessionCreate,
    CallSessionDetailRead,
    CallSessionEndRequest,
    CallSessionRead,
    ErrorResponse,
    EvidenceCheckType,
    EvidenceItemCreate,
    EvidenceItemRead,
    PaginatedCallSessionsResponse,
    PaginatedEvidenceResponse,
    PaginatedTrustAssessmentsResponse,
    SimulatedTransactionRequest,
    SimulatedTransactionResponse,
    TrustAssessmentCreate,
    TrustAssessmentRead,
)
from app.services.call_session_service import CallSessionService
from app.services.detectif_stream import DetectifStreamError, relay_browser_audio_to_detectif
from app.services.events import (
    EventPublisher,
    get_event_publisher,
    publish_evidence_added,
    publish_status_changed,
    publish_trust_updated,
)
from app.services.evidence_mapper import EvidenceMappingError, map_detectif_websocket_message
from app.services.evidence_repository import EvidenceRepository
from app.services.transaction_policy import simulate_transaction_for_call
from app.services.trust_assessment_repository import TrustAssessmentRepository
from app.services.webhook_service import reconcile_pending_webhooks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calls", tags=["calls"])

StartCallRequest = CallSessionCreate


def _upsert_enrollment_consent(
    profile: SpeakerProfile | None,
    *,
    speaker_id: str,
    owner_id: str | None,
    display_name: str | None,
    now,
) -> SpeakerProfile | None:
    if profile is None:
        return SpeakerProfile(
            speaker_id=speaker_id,
            owner_id=owner_id,
            display_name=display_name,
            consent_confirmed=True,
            consent_recorded_at=now,
            enrollment_status="pending",
        )
    profile.consent_confirmed = True
    profile.consent_recorded_at = now
    if profile.enrollment_status == "deleted":
        profile.enrollment_status = "pending"
        profile.sample_count = 0
    if display_name is not None:
        profile.display_name = display_name
    return None


def _build_call_session(payload: StartCallRequest, *, owner_id: str | None, now) -> CallSession:
    return CallSession(
        call_id=payload.call_id,
        owner_id=owner_id,
        speaker_id=payload.speaker_id,
        checks_mode=payload.checks_mode,
        consent_confirmed=payload.consent_confirmed,
        consent_recorded_at=now if payload.consent_confirmed else None,
        status="created",
    )


async def _get_authorized_call_session(
    db: AsyncSession,
    *,
    call_id: str,
    principal: AuthPrincipal,
) -> CallSession:
    session = await db.get(CallSession, call_id)
    if session is None:
        raise AppAPIError(
            status_code=404,
            code="call_session_not_found",
            message=f"Call session '{call_id}' not found",
            details={"call_id": call_id},
        )
    authorize_call_access(session, principal)
    return session


@router.post(
    "/sessions",
    dependencies=[Depends(rate_limit("call_create", lambda s: s.rate_limit_call_create_requests))],
)
async def create_call_session(
    payload: StartCallRequest,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(require_backend_access),
    publisher: EventPublisher = Depends(get_event_publisher),
):
    now = utc_now()
    owner_id = principal.subject if principal.role == "user" else None

    for attempt in range(2):
        existing = await db.get(CallSession, payload.call_id)
        if existing:
            raise AppAPIError(
                status_code=409,
                code="call_session_already_exists",
                message="call_id already exists",
                details={"call_id": payload.call_id},
            )

        if payload.checks_mode == "deepfake,enroll" and payload.speaker_id and payload.consent_confirmed:
            profile = await db.get(SpeakerProfile, payload.speaker_id)
            if profile is not None and principal.role == "user" and profile.owner_id != principal.subject:
                raise AppAPIError(
                    status_code=403,
                    code="speaker_access_forbidden",
                    message="You are not authorized to enroll this speaker profile",
                    details={"speaker_id": payload.speaker_id},
                )
            created_profile = _upsert_enrollment_consent(
                profile,
                speaker_id=payload.speaker_id,
                owner_id=owner_id,
                display_name=payload.display_name,
                now=now,
            )
            if created_profile is not None:
                db.add(created_profile)

        db.add(_build_call_session(payload, owner_id=owner_id, now=now))
        try:
            await db.commit()
            break
        except IntegrityError as exc:
            await db.rollback()
            if await db.get(CallSession, payload.call_id) is not None:
                raise AppAPIError(
                    status_code=409,
                    code="call_session_already_exists",
                    message="call_id already exists",
                    details={"call_id": payload.call_id},
                ) from exc
            # Retry once if simultaneous new SpeakerProfile creation caused the conflict.
            if (
                attempt == 0
                and payload.checks_mode == "deepfake,enroll"
                and payload.speaker_id
                and await db.get(SpeakerProfile, payload.speaker_id) is not None
            ):
                continue
            raise

    await publish_status_changed(
        publisher,
        call_id=payload.call_id,
        previous_status=None,
        status="created",
    )
    # Reconcile any early/unmatched webhook deliveries received prior to session creation.
    await reconcile_pending_webhooks(db, call_id=payload.call_id)
    return {
        "call_id": payload.call_id,
        "speaker_id": payload.speaker_id,
        "checks_mode": payload.checks_mode,
        "status": "created",
    }


@router.get(
    "/sessions",
    response_model=PaginatedCallSessionsResponse,
)
async def list_call_sessions(
    status: str | None = Query(default=None),
    speaker_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(require_backend_access),
):
    owner_filter = principal.subject if principal.role == "user" else None
    rows, total = await CallSessionService.list_sessions(
        db,
        status=status,
        speaker_id=speaker_id,
        owner_id=owner_filter,
        limit=limit,
        offset=offset,
    )
    return PaginatedCallSessionsResponse(
        items=[CallSessionRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/sessions/{call_id}",
    response_model=CallSessionDetailRead,
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_call_session(
    call_id: str,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(require_backend_access),
):
    await _get_authorized_call_session(db, call_id=call_id, principal=principal)
    return await CallSessionService.get_session_detail(db, call_id=call_id)


@router.post(
    "/sessions/{call_id}/end",
    response_model=CallSessionRead,
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def end_call_session(
    call_id: str,
    payload: CallSessionEndRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(require_backend_access),
    publisher: EventPublisher = Depends(get_event_publisher),
):
    await _get_authorized_call_session(db, call_id=call_id, principal=principal)
    reason = payload.reason if payload is not None else None
    session, previous_status = await CallSessionService.end_session(
        db,
        call_id=call_id,
        reason=reason,
    )
    if previous_status is not None:
        await publish_status_changed(
            publisher,
            call_id=session.call_id,
            previous_status=previous_status,
            status=session.status,
            ended_reason=session.ended_reason,
        )
    return CallSessionRead.model_validate(session)


@router.get(
    "/sessions/{call_id}/evidence",
    response_model=PaginatedEvidenceResponse,
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def list_call_evidence(
    call_id: str,
    check_type: EvidenceCheckType | None = Query(default=None),
    provider: str | None = Query(default=None),
    is_final: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(require_backend_access),
):
    await _get_authorized_call_session(db, call_id=call_id, principal=principal)
    rows, total = await EvidenceRepository.list_for_call(
        db,
        call_id=call_id,
        check_type=check_type,
        provider=provider,
        is_final=is_final,
        limit=limit,
        offset=offset,
    )
    return PaginatedEvidenceResponse(
        items=[EvidenceItemRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/sessions/{call_id}/evidence",
    response_model=EvidenceItemRead,
    status_code=201,
    responses={
        200: {"model": EvidenceItemRead, "description": "Duplicate source_event_key returned existing evidence"},
        201: {"model": EvidenceItemRead, "description": "Evidence created"},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
    },
    dependencies=[
        Depends(rate_limit("evidence_submit", lambda s: s.rate_limit_evidence_requests)),
        Depends(require_roles("admin", "service")),
    ],
)
async def append_call_evidence(
    call_id: str,
    payload: EvidenceItemCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    publisher: EventPublisher = Depends(get_event_publisher),
):
    item, created = await EvidenceRepository.create(
        db,
        call_id=call_id,
        payload=payload,
        commit=True,
    )
    read_item = EvidenceItemRead.model_validate(item)
    if created:
        response.status_code = 201
        await publish_evidence_added(publisher, item=read_item)
    else:
        response.status_code = 200
    return read_item


@router.post(
    "/sessions/{call_id}/trust-assessments",
    response_model=TrustAssessmentRead,
    status_code=201,
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
    },
    dependencies=[
        Depends(rate_limit("assessment_submit", lambda s: s.rate_limit_assessment_requests)),
        Depends(require_roles("admin", "service")),
    ],
)
async def create_trust_assessment(
    call_id: str,
    payload: TrustAssessmentCreate,
    db: AsyncSession = Depends(get_db),
    publisher: EventPublisher = Depends(get_event_publisher),
):
    assessment = await TrustAssessmentRepository.create(
        db,
        call_id=call_id,
        payload=payload,
        commit=True,
    )
    read_assessment = TrustAssessmentRead.model_validate(assessment)
    await publish_trust_updated(publisher, assessment=read_assessment)
    return read_assessment


@router.get(
    "/sessions/{call_id}/trust-assessments/latest",
    response_model=TrustAssessmentRead,
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_latest_trust_assessment(
    call_id: str,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(require_backend_access),
):
    await _get_authorized_call_session(db, call_id=call_id, principal=principal)
    assessment = await TrustAssessmentRepository.get_latest_for_call(db, call_id=call_id)
    return TrustAssessmentRead.model_validate(assessment)


@router.get(
    "/sessions/{call_id}/trust-assessments",
    response_model=PaginatedTrustAssessmentsResponse,
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def list_trust_assessments(
    call_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(require_backend_access),
):
    await _get_authorized_call_session(db, call_id=call_id, principal=principal)
    rows, total = await TrustAssessmentRepository.list_for_call(
        db,
        call_id=call_id,
        limit=limit,
        offset=offset,
    )
    return PaginatedTrustAssessmentsResponse(
        items=[TrustAssessmentRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/sessions/{call_id}/transactions/simulate",
    response_model=SimulatedTransactionResponse,
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def simulate_transaction(
    call_id: str,
    payload: SimulatedTransactionRequest,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(require_backend_access),
):
    """Evaluate banking transaction policy over persisted trust and evidence (simulated only)."""
    session = await _get_authorized_call_session(db, call_id=call_id, principal=principal)
    return await simulate_transaction_for_call(
        db,
        call_session=session,
        request=payload,
        actor_subject=principal.subject,
    )


async def _authorize_ws_handshake(
    websocket: WebSocket,
    *,
    call_id: str,
    bucket: str,
) -> tuple[AuthPrincipal | None, CallSession | None]:
    settings = get_settings()
    if settings.rate_limit_enabled:
        client_host = websocket.client.host if websocket.client and websocket.client.host else "unknown"
        allowed, _, _ = await get_rate_limiter().check_and_consume(
            f"{bucket}:{client_host}",
            limit=settings.rate_limit_ws_connect_requests,
            window_seconds=settings.rate_limit_window_seconds,
        )
        if not allowed:
            await websocket.send_json({"type": "error", "code": "rate_limited"})
            await websocket.close(code=4429)
            return None, None

    principal = await resolve_websocket_principal(websocket)
    if principal is None:
        await websocket.send_json({"type": "error", "code": "unauthorized"})
        await websocket.close(code=4401)
        return None, None

    async with AsyncSessionLocal() as db:
        session = await db.get(CallSession, call_id)
        if session is None:
            await websocket.send_json({"type": "error", "code": "call_session_not_found"})
            await websocket.close(code=4404)
            return None, None
        try:
            authorize_call_access(session, principal)
        except AppAPIError:
            await websocket.send_json({"type": "error", "code": "forbidden"})
            await websocket.close(code=4403)
            return None, None
        return principal, session


@router.websocket("/ws/{call_id}")
async def live_call_websocket(websocket: WebSocket, call_id: str):
    await websocket.accept()
    principal, session = await _authorize_ws_handshake(
        websocket,
        call_id=call_id,
        bucket="ws_audio_connect",
    )
    if principal is None or session is None:
        return

    settings = get_settings()
    tracker = get_ws_connection_tracker()
    acquired = await tracker.acquire(
        f"audio:{call_id}",
        max_connections=settings.detectif_ws_max_connections_per_call,
    )
    if not acquired:
        await websocket.send_json({"type": "error", "code": "too_many_connections"})
        await websocket.close(code=4429)
        return

    publisher = get_event_publisher()
    speaker_id = session.speaker_id
    checks_mode = session.checks_mode
    consent_confirmed = session.consent_confirmed

    try:
        async with AsyncSessionLocal() as db:
            current_session = await db.get(CallSession, call_id)
            if current_session is None:
                await websocket.send_json({"type": "error", "code": "call_session_not_found"})
                await websocket.close(code=4404)
                return
            previous_status = current_session.status
            current_session.status = "connecting"
            await db.commit()
        if previous_status != "connecting":
            await publish_status_changed(
                publisher,
                call_id=call_id,
                previous_status=previous_status,
                status="connecting",
            )

        async def persist_provider_message(payload: dict) -> None:
            created_evidence: list[EvidenceItemRead] = []
            status_transition: tuple[str, str] | None = None
            async with AsyncSessionLocal() as db:
                current = await db.get(CallSession, call_id)
                if not current:
                    return
                prior_status = current.status
                message_type = payload.get("type")
                if payload.get("stream_id"):
                    current.provider_stream_id = payload["stream_id"]
                if message_type == "ready" and current.status not in {"completed", "ended"}:
                    current.status = "active"
                elif message_type == "completed":
                    current.status = "completed"
                seq_val = payload.get("sequence")
                if type(seq_val) is int and seq_val > current.last_deepfake_sequence:
                    current.last_deepfake_sequence = seq_val
                current.last_provider_event_at = utc_now()
                if current.status != prior_status:
                    status_transition = (prior_status, current.status)

                if message_type == "completed" and current.checks_mode == "deepfake,enroll" and current.speaker_id:
                    profile = await db.get(SpeakerProfile, current.speaker_id)
                    results = payload.get("results") if isinstance(payload.get("results"), dict) else {}
                    enroll_res = results.get("enroll") if isinstance(results.get("enroll"), dict) else {}
                    if profile is not None:
                        enroll_status = str(enroll_res.get("status") or "enrolled").lower()
                        profile.enrollment_status = "failed" if enroll_status in {"failed", "error"} else "enrolled"
                        if profile.enrollment_status == "enrolled":
                            sample_cnt = enroll_res.get("sample_count")
                            profile.sample_count = (
                                sample_cnt
                                if type(sample_cnt) is int and sample_cnt >= 0
                                else max(profile.sample_count, 1)
                            )
                        profile.updated_at = utc_now()

                try:
                    mapped_items = map_detectif_websocket_message(
                        payload,
                        call_id=call_id,
                        speaker_id=current.speaker_id,
                        provider_stream_id=current.provider_stream_id,
                    )
                except EvidenceMappingError as exc:
                    logger.warning("Skipping unmapped WS message for call %s: %s", call_id, exc)
                    mapped_items = []

                for mapped in mapped_items:
                    saved_item, created = await EvidenceRepository.create(
                        db,
                        call_id=call_id,
                        payload=mapped,
                        commit=False,
                    )
                    if created:
                        created_evidence.append(EvidenceItemRead.model_validate(saved_item))

                await db.commit()

            if status_transition is not None:
                await publish_status_changed(
                    publisher,
                    call_id=call_id,
                    previous_status=status_transition[0],
                    status=status_transition[1],
                )
            for read_item in created_evidence:
                await publish_evidence_added(publisher, item=read_item)

        try:
            await relay_browser_audio_to_detectif(
                browser_ws=websocket,
                call_id=call_id,
                speaker_id=speaker_id,
                checks_mode=checks_mode,
                consent_confirmed=consent_confirmed,
                on_provider_message=persist_provider_message,
            )
            ended_transition: tuple[str, str] | None = None
            async with AsyncSessionLocal() as db:
                current = await db.get(CallSession, call_id)
                if current and current.status not in {"completed", "ended"}:
                    ended_transition = (current.status, "ended")
                    current.status = "ended"
                    if current.ended_at is None:
                        current.ended_at = utc_now()
                    await db.commit()
            if ended_transition is not None:
                await publish_status_changed(
                    publisher,
                    call_id=call_id,
                    previous_status=ended_transition[0],
                    status=ended_transition[1],
                )
        except DetectifStreamError as exc:
            try:
                await websocket.send_json({"type": "error", "code": "detectif_stream_error", "message": str(exc)})
                await websocket.close(code=1011)
            except RuntimeError:
                pass
        except WebSocketDisconnect:
            disc_transition: tuple[str, str] | None = None
            async with AsyncSessionLocal() as db:
                current = await db.get(CallSession, call_id)
                if current and current.status not in {"completed", "ended", "disconnected"}:
                    disc_transition = (current.status, "disconnected")
                    current.status = "disconnected"
                    await db.commit()
            if disc_transition is not None:
                await publish_status_changed(
                    publisher,
                    call_id=call_id,
                    previous_status=disc_transition[0],
                    status=disc_transition[1],
                )
    finally:
        await tracker.release(f"audio:{call_id}")


@router.websocket("/ws/{call_id}/events")
async def live_dashboard_events_websocket(websocket: WebSocket, call_id: str):
    """Stream real-time `evidence.added`, `trust.updated`, and `call.status_changed` dashboard events."""
    await websocket.accept()
    principal, session = await _authorize_ws_handshake(
        websocket,
        call_id=call_id,
        bucket="ws_events_connect",
    )
    if principal is None or session is None:
        return

    publisher = get_event_publisher()
    subscribe_fn = getattr(publisher, "subscribe", None)
    if subscribe_fn is None:
        await websocket.send_json(
            {"type": "error", "code": "event_stream_unavailable", "message": "Event bus subscription not available"}
        )
        await websocket.close(code=1011)
        return

    await websocket.send_json({"type": "subscribed", "call_id": call_id, "status": session.status})

    async def watch_disconnect() -> None:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                return

    try:
        async with subscribe_fn(call_id=call_id) as queue:
            disconnect_task = asyncio.create_task(watch_disconnect())
            queue_task = asyncio.create_task(queue.get())
            try:
                while True:
                    done, _ = await asyncio.wait(
                        {disconnect_task, queue_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if disconnect_task in done:
                        break
                    domain_event = queue_task.result()
                    await websocket.send_json(domain_event.model_dump(mode="json"))
                    queue_task = asyncio.create_task(queue.get())
            finally:
                for task in (disconnect_task, queue_task):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(disconnect_task, queue_task, return_exceptions=True)
    except WebSocketDisconnect:
        return
    except RuntimeError:
        return

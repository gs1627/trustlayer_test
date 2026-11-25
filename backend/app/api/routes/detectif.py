import re
import uuid

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    AuthPrincipal,
    authorize_call_access,
    authorize_speaker_access,
    require_backend_access,
    require_roles,
)
from app.api.audio import read_audio
from app.core.config import get_settings
from app.core.rate_limit import rate_limit
from app.db.models import CallSession, SpeakerProfile, utc_now
from app.db.session import get_db
from app.schemas.contracts import (
    ErrorResponse,
    EvidenceItemRead,
    PaginatedProviderOperationsResponse,
    ProviderOperationRead,
    ProviderOperationResponse,
)
from app.services.detectif_client import (
    DetectifAPIError,
    DetectifClient,
    DetectifNotConfiguredError,
)
from app.services.events import EventPublisher, get_event_publisher, publish_evidence_added
from app.services.evidence_mapper import (
    EvidenceMappingError,
    map_aletheia_rest_result,
    map_eidos_verify_rest_results,
)
from app.services.evidence_repository import EvidenceRepository
from app.services.provider_operation_repository import ProviderOperationRepository

router = APIRouter(
    prefix="/detectif",
    tags=["DetectifAI"],
    dependencies=[Depends(require_backend_access)],
)
client = DetectifClient()

_SPEAKER_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")

ALLOWED_CONTENT_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp4",
    "audio/m4a",
    "audio/flac",
    "audio/ogg",
    "audio/webm",
    "audio/aiff",
    "application/octet-stream",
}


async def read_audio(file: UploadFile) -> bytes:
    settings = get_settings()
    normalized_type = (file.content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
    if normalized_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported audio content type")
    content = await file.read(settings.max_upload_bytes + 1)
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded audio file is empty")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Audio exceeds the application limit of {settings.max_upload_mb} MB",
        )
    return content


def provider_error(exc: DetectifAPIError) -> HTTPException:
    # Preserve provider HTTP status and error metadata without exposing credentials.
    status_code = exc.status_code if 400 <= exc.status_code < 600 else 502
    return HTTPException(
        status_code=status_code,
        detail={
            "provider": "detectifai",
            "code": exc.code,
            "retryable": exc.retryable,
            "request_id": exc.provider_request_id,
            "error": exc.detail,
        },
    )


async def _validate_optional_call_access(
    db: AsyncSession,
    *,
    call_id: str | None,
    principal: AuthPrincipal,
) -> CallSession | None:
    if not call_id:
        return None
    call_session = await db.get(CallSession, call_id)
    if call_session is None:
        raise HTTPException(status_code=404, detail=f"Call session '{call_id}' not found")
    authorize_call_access(call_session, principal)
    return call_session


@router.post(
    "/deepfake",
    response_model=ProviderOperationResponse,
    dependencies=[Depends(rate_limit("detectif_deepfake", lambda s: s.rate_limit_evidence_requests))],
)
async def detect_deepfake(
    file: UploadFile = File(...),
    call_id: str | None = Form(default=None, min_length=3, max_length=128),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(require_backend_access),
    publisher: EventPublisher = Depends(get_event_publisher),
):
    call_session = await _validate_optional_call_access(db, call_id=call_id, principal=principal)
    content = await read_audio(file)
    idem_key = idempotency_key or str(uuid.uuid4())
    correlation_id = f"corr_{uuid.uuid4().hex}"

    op_row, _ = await ProviderOperationRepository.create_started(
        db,
        operation_type="deepfake.detect",
        call_id=call_session.call_id if call_session else None,
        idempotency_key=idem_key,
        correlation_id=correlation_id,
        commit=True,
    )

    try:
        result, meta = await client.detect_deepfake_with_meta(
            filename=file.filename or "audio-upload",
            content=content,
            content_type=file.content_type or "application/octet-stream",
            idempotency_key=idem_key,
            correlation_id=correlation_id,
        )
    except DetectifNotConfiguredError as exc:
        await ProviderOperationRepository.mark_failed(
            db,
            op_row,
            error_code="provider_not_configured",
            error_message=str(exc),
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DetectifAPIError as exc:
        await ProviderOperationRepository.mark_failed(
            db,
            op_row,
            error_code=exc.code,
            error_message=str(exc),
            retry_count=exc.retry_attempts,
            failure_details=exc.detail if isinstance(exc.detail, dict) else {"raw": str(exc.detail)},
            request_id=exc.provider_request_id,
        )
        raise provider_error(exc) from exc

    await ProviderOperationRepository.mark_succeeded(
        db,
        op_row,
        payload=result,
        retry_count=meta["retry_count"],
        commit=False,
    )

    created_evidence: list[EvidenceItemRead] = []
    if call_session is not None:
        try:
            mapped = map_aletheia_rest_result(
                result,
                call_id=call_session.call_id,
                speaker_id=call_session.speaker_id,
            )
            saved, created = await EvidenceRepository.create(
                db,
                call_id=call_session.call_id,
                payload=mapped,
                commit=False,
            )
            if created:
                created_evidence.append(EvidenceItemRead.model_validate(saved))
        except EvidenceMappingError:
            pass

    await db.commit()
    for ev_item in created_evidence:
        await publish_evidence_added(publisher, item=ev_item)

    return ProviderOperationResponse(
        operation="deepfake_detection",
        request_id=result.get("request_id"),
        operation_id=result.get("operation_id"),
        correlation_id=correlation_id,
        status=op_row.status,
        raw=result,
    )


@router.post(
    "/speakers/enroll",
    response_model=ProviderOperationResponse,
    dependencies=[Depends(rate_limit("detectif_enroll", lambda s: s.rate_limit_call_create_requests))],
)
async def enroll_speaker(
    speaker_id: str = Form(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]{1,64}$"),
    display_name: str | None = Form(default=None, max_length=128),
    consent_confirmed: bool = Form(...),
    call_id: str | None = Form(default=None, min_length=3, max_length=128),
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(require_backend_access),
):
    if not consent_confirmed:
        raise HTTPException(status_code=400, detail="Explicit speaker consent is required before enrollment")
    call_session = await _validate_optional_call_access(db, call_id=call_id, principal=principal)
    existing_profile = await db.get(SpeakerProfile, speaker_id)
    if existing_profile is not None:
        authorize_speaker_access(existing_profile, principal)

    content = await read_audio(file)
    idem_key = idempotency_key or str(uuid.uuid4())
    correlation_id = f"corr_{uuid.uuid4().hex}"

    op_row, _ = await ProviderOperationRepository.create_started(
        db,
        operation_type="speaker.enroll",
        call_id=call_session.call_id if call_session else None,
        speaker_id=existing_profile.speaker_id if existing_profile else None,
        idempotency_key=idem_key,
        correlation_id=correlation_id,
        commit=True,
    )

    try:
        result, meta = await client.enroll_speaker_with_meta(
            speaker_id=speaker_id,
            display_name=display_name,
            filename=file.filename or "enrollment-audio",
            content=content,
            content_type=file.content_type or "application/octet-stream",
            idempotency_key=idem_key,
            correlation_id=correlation_id,
        )
    except DetectifNotConfiguredError as exc:
        await ProviderOperationRepository.mark_failed(
            db,
            op_row,
            error_code="provider_not_configured",
            error_message=str(exc),
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DetectifAPIError as exc:
        await ProviderOperationRepository.mark_failed(
            db,
            op_row,
            error_code=exc.code,
            error_message=str(exc),
            retry_count=exc.retry_attempts,
            failure_details=exc.detail if isinstance(exc.detail, dict) else {"raw": str(exc.detail)},
            request_id=exc.provider_request_id,
        )
        raise provider_error(exc) from exc

    now = utc_now()
    profile = await db.get(SpeakerProfile, speaker_id)
    result_block = result.get("result") if isinstance(result.get("result"), dict) else result
    raw_enroll_status = str(result_block.get("status") or result.get("status") or "enrolled").lower()
    mapped_enroll_status = "pending" if raw_enroll_status in {"pending", "processing", "queued"} else "enrolled"

    if profile is None:
        profile = SpeakerProfile(
            speaker_id=speaker_id,
            owner_id=principal.subject if principal.role == "user" else None,
            display_name=display_name,
            consent_confirmed=True,
            consent_recorded_at=now,
            enrollment_status=mapped_enroll_status,
            sample_count=1 if mapped_enroll_status == "enrolled" else 0,
            provider="detectifai",
            created_at=now,
            updated_at=now,
        )
        db.add(profile)
        await db.flush()
    else:
        profile.consent_confirmed = True
        profile.consent_recorded_at = now
        if profile.enrollment_status == "deleted":
            profile.sample_count = 0
        if mapped_enroll_status == "enrolled":
            sample_cnt = result_block.get("sample_count")
            profile.sample_count = sample_cnt if type(sample_cnt) is int and sample_cnt >= 0 else profile.sample_count + 1
        profile.enrollment_status = mapped_enroll_status
        if display_name is not None:
            profile.display_name = display_name
        profile.updated_at = now

    op_row.speaker_id = profile.speaker_id
    await ProviderOperationRepository.mark_succeeded(
        db,
        op_row,
        payload=result,
        retry_count=meta["retry_count"],
        commit=True,
    )

    return ProviderOperationResponse(
        operation="speaker_enrollment",
        request_id=result.get("request_id"),
        operation_id=result.get("operation_id"),
        correlation_id=correlation_id,
        status=op_row.status,
        raw=result,
    )


@router.post(
    "/speakers/verify",
    response_model=ProviderOperationResponse,
    dependencies=[Depends(rate_limit("detectif_verify", lambda s: s.rate_limit_evidence_requests))],
)
async def verify_speaker(
    speaker_id: str = Form(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]{1,64}$"),
    detect_deepfake: bool = Form(default=True),
    call_id: str | None = Form(default=None, min_length=3, max_length=128),
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(require_backend_access),
    publisher: EventPublisher = Depends(get_event_publisher),
):
    call_session = await _validate_optional_call_access(db, call_id=call_id, principal=principal)
    existing_profile = await db.get(SpeakerProfile, speaker_id)
    if existing_profile is not None:
        authorize_speaker_access(existing_profile, principal)

    content = await read_audio(file)
    idem_key = idempotency_key or str(uuid.uuid4())
    correlation_id = f"corr_{uuid.uuid4().hex}"

    op_row, _ = await ProviderOperationRepository.create_started(
        db,
        operation_type="speaker.verify",
        call_id=call_session.call_id if call_session else None,
        speaker_id=existing_profile.speaker_id if existing_profile else None,
        idempotency_key=idem_key,
        correlation_id=correlation_id,
        commit=True,
    )

    try:
        result, meta = await client.verify_speaker_with_meta(
            speaker_id=speaker_id,
            detect_deepfake=detect_deepfake,
            filename=file.filename or "verification-audio",
            content=content,
            content_type=file.content_type or "application/octet-stream",
            idempotency_key=idem_key,
            correlation_id=correlation_id,
        )
    except DetectifNotConfiguredError as exc:
        await ProviderOperationRepository.mark_failed(
            db,
            op_row,
            error_code="provider_not_configured",
            error_message=str(exc),
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DetectifAPIError as exc:
        await ProviderOperationRepository.mark_failed(
            db,
            op_row,
            error_code=exc.code,
            error_message=str(exc),
            retry_count=exc.retry_attempts,
            failure_details=exc.detail if isinstance(exc.detail, dict) else {"raw": str(exc.detail)},
            request_id=exc.provider_request_id,
        )
        raise provider_error(exc) from exc

    await ProviderOperationRepository.mark_succeeded(
        db,
        op_row,
        payload=result,
        retry_count=meta["retry_count"],
        commit=False,
    )

    created_evidence: list[EvidenceItemRead] = []
    if call_session is not None:
        try:
            mapped_items = map_eidos_verify_rest_results(
                result,
                call_id=call_session.call_id,
                speaker_id=speaker_id,
            )
            for mapped in mapped_items:
                saved, created = await EvidenceRepository.create(
                    db,
                    call_id=call_session.call_id,
                    payload=mapped,
                    commit=False,
                )
                if created:
                    created_evidence.append(EvidenceItemRead.model_validate(saved))
        except EvidenceMappingError:
            pass

    await db.commit()
    for ev_item in created_evidence:
        await publish_evidence_added(publisher, item=ev_item)

    return ProviderOperationResponse(
        operation="speaker_verification",
        request_id=result.get("request_id"),
        operation_id=result.get("operation_id"),
        correlation_id=correlation_id,
        status=op_row.status,
        raw=result,
    )


@router.get(
    "/operations",
    response_model=PaginatedProviderOperationsResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    dependencies=[Depends(require_roles("admin", "service", "operator"))],
)
async def list_tracked_operations(
    call_id: str | None = Query(default=None),
    speaker_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    operation_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await ProviderOperationRepository.list_operations(
        db,
        call_id=call_id,
        speaker_id=speaker_id,
        status=status,
        operation_type=operation_type,
        limit=limit,
        offset=offset,
    )
    return PaginatedProviderOperationsResponse(
        items=[ProviderOperationRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/operations/{operation_id}")
async def get_operation(
    operation_id: str,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(require_backend_access),
):
    tracked = await ProviderOperationRepository.find_by_operation_id(db, operation_id=operation_id)
    if tracked is not None and tracked.call_id:
        call_session = await db.get(CallSession, tracked.call_id)
        if call_session is not None:
            authorize_call_access(call_session, principal)
    elif tracked is not None and tracked.speaker_id:
        profile = await db.get(SpeakerProfile, tracked.speaker_id)
        if profile is not None:
            authorize_speaker_access(profile, principal)
    elif principal.role == "user":
        raise HTTPException(status_code=403, detail="Not permitted to query unowned provider operations")

    try:
        payload = await client.get_operation(operation_id)
    except DetectifNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DetectifAPIError as exc:
        raise provider_error(exc) from exc

    await ProviderOperationRepository.sync_from_provider_payload(
        db,
        operation_id=operation_id,
        payload=payload,
        commit=True,
    )
    return payload


@router.get("/speakers")
async def list_speakers(limit: int = 20, cursor: str | None = None):
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
    try:
        return await client.list_speakers(limit=limit, cursor=cursor)
    except DetectifNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DetectifAPIError as exc:
        raise provider_error(exc) from exc


@router.delete("/speakers/{speaker_id}")
async def delete_speaker(
    speaker_id: str,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(require_backend_access),
):
    if not _SPEAKER_ID_RE.fullmatch(speaker_id):
        raise HTTPException(status_code=422, detail="Invalid speaker_id format")
    profile = await db.get(SpeakerProfile, speaker_id)
    if profile is not None:
        authorize_speaker_access(profile, principal)

    try:
        res = await client.delete_speaker(speaker_id)
    except DetectifNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DetectifAPIError as exc:
        raise provider_error(exc) from exc

    if profile is not None:
        profile.enrollment_status = "deleted"
        profile.sample_count = 0
        profile.updated_at = utc_now()
        await db.commit()
    return res


@router.get("/streams/{stream_id}")
async def get_stream(
    stream_id: str,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(require_backend_access),
):
    if not stream_id or len(stream_id) > 64:
        raise HTTPException(status_code=422, detail="Invalid stream_id")
    from sqlalchemy import select

    session = await db.scalar(select(CallSession).where(CallSession.provider_stream_id == stream_id))
    if session is not None:
        authorize_call_access(session, principal)
    elif principal.role == "user":
        raise HTTPException(status_code=403, detail="Not permitted to access unowned streams")

    try:
        return await client.get_stream(stream_id)
    except DetectifNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DetectifAPIError as exc:
        raise provider_error(exc) from exc

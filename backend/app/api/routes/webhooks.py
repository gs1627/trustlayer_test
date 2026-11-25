import json

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_roles
from app.core.config import get_settings
from app.core.errors import AppAPIError
from app.core.rate_limit import rate_limit
from app.core.security import WebhookSignatureError, verify_detectif_webhook_signature
from app.db.models import WebhookEvent
from app.db.session import get_db
from app.schemas.contracts import (
    ErrorResponse,
    PaginatedWebhookEventsResponse,
    WebhookAcceptedResponse,
    WebhookEventRead,
    WebhookReconcileResponse,
)
from app.services.webhook_service import (
    ingest_webhook_event,
    list_webhook_events,
    reconcile_pending_webhooks,
    reprocess_and_publish_webhook_event,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post(
    "/detectifai",
    response_model=WebhookAcceptedResponse,
    status_code=202,
    dependencies=[Depends(rate_limit("webhooks", lambda s: s.rate_limit_webhook_requests))],
)
async def receive_detectifai_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    webhook_id: str | None = Header(default=None, alias="webhook-id"),
    webhook_timestamp: str | None = Header(default=None, alias="webhook-timestamp"),
    webhook_signature: str | None = Header(default=None, alias="webhook-signature"),
):
    settings = get_settings()
    if not settings.detectif_webhook_secret:
        raise HTTPException(status_code=503, detail="DETECTIF_WEBHOOK_SECRET is not configured")

    raw_body = await request.body()
    signature_headers = {
        "webhook-id": webhook_id or "",
        "webhook-timestamp": webhook_timestamp or "",
        "webhook-signature": webhook_signature or "",
    }
    previous_secrets = (
        (settings.detectif_webhook_secret_previous,) if settings.detectif_webhook_secret_previous else ()
    )
    try:
        verify_detectif_webhook_signature(
            secret=settings.detectif_webhook_secret,
            headers=signature_headers,
            raw_body=raw_body,
            tolerance_seconds=settings.webhook_tolerance_seconds,
            previous_secrets=previous_secrets,
        )
    except WebhookSignatureError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Webhook body must be valid JSON") from exc

    if not isinstance(payload, dict) or not payload.get("type"):
        raise HTTPException(status_code=400, detail="Webhook event must be a JSON object containing type")

    result = await ingest_webhook_event(db, delivery_id=webhook_id or "", payload=payload)
    return WebhookAcceptedResponse(
        accepted=True,
        duplicate=result.duplicate,
        delivery_id=webhook_id or "",
        status=result.status,
        call_id=result.call_id,
    )


@router.get(
    "/events",
    response_model=PaginatedWebhookEventsResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    dependencies=[Depends(require_roles("admin"))],
)
async def list_recorded_webhook_events(
    status: str | None = Query(default=None),
    call_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await list_webhook_events(
        db,
        status=status,
        call_id=call_id,
        limit=limit,
        offset=offset,
    )
    return PaginatedWebhookEventsResponse(
        items=[WebhookEventRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/reconcile",
    response_model=WebhookReconcileResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    dependencies=[Depends(require_roles("admin"))],
)
async def trigger_webhook_reconciliation(
    call_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    return await reconcile_pending_webhooks(db, call_id=call_id, limit=limit)


@router.post(
    "/events/{delivery_id}/reprocess",
    response_model=WebhookEventRead,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    dependencies=[Depends(require_roles("admin"))],
)
async def replay_single_webhook_event(
    delivery_id: str,
    db: AsyncSession = Depends(get_db),
):
    event = await db.scalar(select(WebhookEvent).where(WebhookEvent.delivery_id == delivery_id))
    if event is None:
        raise AppAPIError(
            status_code=404,
            code="webhook_event_not_found",
            message=f"Webhook delivery '{delivery_id}' not found",
            details={"delivery_id": delivery_id},
        )
    updated = await reprocess_and_publish_webhook_event(db, event=event, force=True)
    return WebhookEventRead.model_validate(updated)

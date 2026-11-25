from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CallSession, ProviderOperation, SpeakerProfile, parse_utc_datetime, utc_now
from app.services.evidence_mapper import sanitize_evidence_details


def _extract_credits(payload: dict[str, Any]) -> int | None:
    for key in ("credits_charged", "credits"):
        val = payload.get(key)
        if type(val) is int:
            return val
    return None


class ProviderOperationRepository:
    """Repository managing ProviderOperation lifecycle, idempotency, retries, and failures."""

    @staticmethod
    async def find_by_idempotency(
        db: AsyncSession,
        *,
        provider: str,
        operation_type: str,
        idempotency_key: str,
    ) -> ProviderOperation | None:
        return await db.scalar(
            select(ProviderOperation).where(
                and_(
                    ProviderOperation.provider == provider,
                    ProviderOperation.operation_type == operation_type,
                    ProviderOperation.idempotency_key == idempotency_key,
                )
            )
        )

    @staticmethod
    async def find_by_operation_id(
        db: AsyncSession,
        *,
        operation_id: str,
    ) -> ProviderOperation | None:
        return await db.scalar(
            select(ProviderOperation).where(ProviderOperation.operation_id == operation_id)
        )

    @staticmethod
    async def create_started(
        db: AsyncSession,
        *,
        provider: str = "detectifai",
        operation_type: str,
        call_id: str | None = None,
        speaker_id: str | None = None,
        stream_id: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        commit: bool = True,
    ) -> tuple[ProviderOperation, bool]:
        """Start tracking an operation or return an existing row matching idempotency_key."""
        if idempotency_key:
            existing = await ProviderOperationRepository.find_by_idempotency(
                db,
                provider=provider,
                operation_type=operation_type,
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                return existing, False

        resolved_call_id = call_id if (call_id and await db.get(CallSession, call_id)) else None
        resolved_speaker_id = (
            speaker_id if (speaker_id and await db.get(SpeakerProfile, speaker_id)) else None
        )

        now = utc_now()
        op = ProviderOperation(
            call_id=resolved_call_id,
            speaker_id=resolved_speaker_id,
            provider=provider,
            operation_type=operation_type,
            stream_id=stream_id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            status="pending",
            retry_count=0,
            started_at=now,
            created_at=now,
            updated_at=now,
        )

        if commit:
            db.add(op)
            try:
                await db.commit()
                await db.refresh(op)
                return op, True
            except IntegrityError:
                await db.rollback()
                if idempotency_key:
                    existing = await ProviderOperationRepository.find_by_idempotency(
                        db,
                        provider=provider,
                        operation_type=operation_type,
                        idempotency_key=idempotency_key,
                    )
                    if existing is not None:
                        return existing, False
                raise

        try:
            async with db.begin_nested():
                db.add(op)
                await db.flush()
            return op, True
        except IntegrityError:
            if idempotency_key:
                existing = await ProviderOperationRepository.find_by_idempotency(
                    db,
                    provider=provider,
                    operation_type=operation_type,
                    idempotency_key=idempotency_key,
                )
                if existing is not None:
                    return existing, False
            raise

    @staticmethod
    async def mark_succeeded(
        db: AsyncSession,
        op: ProviderOperation,
        *,
        payload: dict[str, Any],
        retry_count: int = 0,
        commit: bool = True,
    ) -> ProviderOperation:
        now = utc_now()
        op_id = payload.get("operation_id")
        if op_id:
            collision = await ProviderOperationRepository.find_by_operation_id(db, operation_id=op_id)
            if collision is not None and collision.id != op.id:
                op = collision

        raw_status = str(payload.get("status") or "").strip().lower()
        resolved_status = (
            raw_status
            if raw_status in {"pending", "reserved", "running", "succeeded", "completed", "failed"}
            else "succeeded"
        )
        op.request_id = payload.get("request_id") or op.request_id
        op.operation_id = op_id or op.operation_id
        op.stream_id = payload.get("stream_id") or op.stream_id
        op.status = resolved_status
        op.retry_count = max(op.retry_count, retry_count)
        credits = _extract_credits(payload)
        if credits is not None:
            op.credits = credits
        op.error_code = None
        op.error_message = None
        op.failure_details = None
        op.raw_response = sanitize_evidence_details(payload)
        if resolved_status in {"succeeded", "completed"}:
            op.completed_at = parse_utc_datetime(payload.get("completed_at")) or now
        op.updated_at = now
        if commit:
            await db.commit()
            await db.refresh(op)
        return op

    @staticmethod
    async def mark_failed(
        db: AsyncSession,
        op: ProviderOperation,
        *,
        error_code: str | None,
        error_message: str,
        retry_count: int = 0,
        failure_details: dict[str, Any] | None = None,
        request_id: str | None = None,
        commit: bool = True,
    ) -> ProviderOperation:
        now = utc_now()
        op.request_id = request_id or op.request_id
        op.status = "failed"
        op.retry_count = max(op.retry_count, retry_count)
        op.error_code = error_code[:100] if error_code else None
        op.error_message = error_message[:2000]
        op.failure_details = sanitize_evidence_details(failure_details) if failure_details else None
        op.completed_at = now
        op.updated_at = now
        if commit:
            await db.commit()
            await db.refresh(op)
        return op

    @staticmethod
    async def sync_from_provider_payload(
        db: AsyncSession,
        *,
        operation_id: str,
        payload: dict[str, Any],
        correlation_id: str | None = None,
        commit: bool = True,
    ) -> ProviderOperation:
        """Upsert or synchronize a ProviderOperation from `GET /v1/operations/{id}` or webhook data."""
        op = await ProviderOperationRepository.find_by_operation_id(db, operation_id=operation_id)
        now = utc_now()
        raw_status = str(payload.get("status") or "succeeded").strip().lower()
        if op is None:
            op = ProviderOperation(
                provider="detectifai",
                operation_type=str(payload.get("type") or "unknown"),
                operation_id=operation_id,
                request_id=payload.get("request_id"),
                correlation_id=correlation_id,
                status=raw_status,
                started_at=parse_utc_datetime(payload.get("created_at")) or now,
                created_at=now,
                updated_at=now,
            )
            db.add(op)
        else:
            op.status = raw_status
            op.request_id = payload.get("request_id") or op.request_id
            op.correlation_id = correlation_id or op.correlation_id

        credits = _extract_credits(payload)
        if credits is not None:
            op.credits = credits
        op.raw_response = sanitize_evidence_details(payload)

        error_obj = payload.get("error")
        if isinstance(error_obj, dict):
            op.error_code = str(error_obj.get("code") or error_obj.get("type") or "")[:100] or None
            op.error_message = str(error_obj.get("message") or "")[:2000] or None
            op.failure_details = sanitize_evidence_details(error_obj)
        elif raw_status in {"succeeded", "completed"}:
            op.error_code = None
            op.error_message = None
            op.failure_details = None

        completed_ts = parse_utc_datetime(payload.get("completed_at"))
        if completed_ts is not None:
            op.completed_at = completed_ts
        elif raw_status in {"succeeded", "completed", "failed"} and op.completed_at is None:
            op.completed_at = now

        op.updated_at = now
        if commit:
            await db.commit()
            await db.refresh(op)
        return op

    @staticmethod
    async def list_operations(
        db: AsyncSession,
        *,
        call_id: str | None = None,
        speaker_id: str | None = None,
        status: str | None = None,
        operation_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ProviderOperation], int]:
        conditions = []
        if call_id is not None:
            conditions.append(ProviderOperation.call_id == call_id)
        if speaker_id is not None:
            conditions.append(ProviderOperation.speaker_id == speaker_id)
        if status is not None:
            conditions.append(ProviderOperation.status == status)
        if operation_type is not None:
            conditions.append(ProviderOperation.operation_type == operation_type)
        where_clause = and_(*conditions) if conditions else None

        count_stmt = select(func.count()).select_from(ProviderOperation)
        list_stmt = select(ProviderOperation)
        if where_clause is not None:
            count_stmt = count_stmt.where(where_clause)
            list_stmt = list_stmt.where(where_clause)

        total = int(await db.scalar(count_stmt) or 0)
        rows = (
            await db.scalars(
                list_stmt.order_by(ProviderOperation.created_at.desc(), ProviderOperation.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return list(rows), total

from __future__ import annotations

import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppAPIError
from app.db.models import CallSession, EvidenceItem, utc_now
from app.schemas.contracts import EvidenceItemCreate, EvidenceSummary
from app.services.evidence_mapper import sanitize_evidence_details


class EvidenceRepository:
    """Append-only repository for persisted EvidenceItem records."""

    @staticmethod
    async def get_by_source_event_key(
        db: AsyncSession,
        *,
        call_id: str,
        provider: str,
        check_type: str,
        source_event_key: str,
    ) -> EvidenceItem | None:
        return await db.scalar(
            select(EvidenceItem).where(
                and_(
                    EvidenceItem.call_id == call_id,
                    EvidenceItem.provider == provider,
                    EvidenceItem.check_type == check_type,
                    EvidenceItem.source_event_key == source_event_key,
                )
            )
        )

    @staticmethod
    async def find_by_id(
        db: AsyncSession,
        *,
        evidence_id: str,
        call_id: str | None = None,
    ) -> EvidenceItem | None:
        item = await db.get(EvidenceItem, evidence_id)
        if item is None:
            return None
        if call_id is not None and item.call_id != call_id:
            raise AppAPIError(
                status_code=422,
                code="cross_call_evidence_not_allowed",
                message=f"Evidence '{evidence_id}' belongs to a different call session",
                details={
                    "call_id": call_id,
                    "evidence_id": evidence_id,
                    "evidence_call_id": item.call_id,
                },
            )
        return item

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        *,
        evidence_id: str,
        call_id: str | None = None,
    ) -> EvidenceItem:
        item = await EvidenceRepository.find_by_id(db, evidence_id=evidence_id, call_id=call_id)
        if item is None:
            raise AppAPIError(
                status_code=404,
                code="evidence_not_found",
                message=f"Evidence '{evidence_id}' not found",
                details={"evidence_id": evidence_id},
            )
        return item

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        call_id: str,
        payload: EvidenceItemCreate,
        commit: bool = True,
    ) -> tuple[EvidenceItem, bool]:
        """Append evidence idempotently; returns `(item, created)` without overwriting final items."""
        if payload.call_id != call_id:
            raise AppAPIError(
                status_code=422,
                code="cross_call_mismatch",
                message="Payload call_id does not match URL call_id",
                details={"path_call_id": call_id, "payload_call_id": payload.call_id},
            )

        session = await db.get(CallSession, call_id)
        if session is None:
            raise AppAPIError(
                status_code=404,
                code="call_session_not_found",
                message=f"Call session '{call_id}' not found",
                details={"call_id": call_id},
            )

        if payload.source_event_key is not None:
            existing = await EvidenceRepository.get_by_source_event_key(
                db,
                call_id=call_id,
                provider=payload.provider,
                check_type=payload.check_type,
                source_event_key=payload.source_event_key,
            )
            if existing is not None:
                return existing, False

        item = EvidenceItem(
            evidence_id=f"ev_{uuid.uuid4().hex}",
            call_id=call_id,
            speaker_id=payload.speaker_id,
            provider=payload.provider,
            model=payload.model,
            check_type=payload.check_type,
            status=payload.status,
            verdict=payload.verdict,
            raw_score=payload.raw_score,
            score_type=payload.score_type,
            is_early=payload.is_early,
            is_final=payload.is_final,
            source_channel=payload.source_channel,
            source_event_key=payload.source_event_key,
            sequence=payload.sequence,
            provider_operation_id=payload.provider_operation_id,
            provider_request_id=payload.provider_request_id,
            provider_stream_id=payload.provider_stream_id,
            observed_at=payload.observed_at,
            details=sanitize_evidence_details(payload.details),
            created_at=utc_now(),
        )

        if commit:
            db.add(item)
            try:
                await db.commit()
                await db.refresh(item)
                return item, True
            except IntegrityError:
                await db.rollback()
                if payload.source_event_key is not None:
                    existing = await EvidenceRepository.get_by_source_event_key(
                        db,
                        call_id=call_id,
                        provider=payload.provider,
                        check_type=payload.check_type,
                        source_event_key=payload.source_event_key,
                    )
                    if existing is not None:
                        return existing, False
                if await db.get(CallSession, call_id) is None:
                    raise AppAPIError(
                        status_code=404,
                        code="call_session_not_found",
                        message=f"Call session '{call_id}' not found",
                        details={"call_id": call_id},
                    )
                raise

        try:
            async with db.begin_nested():
                db.add(item)
                await db.flush()
            return item, True
        except IntegrityError:
            if payload.source_event_key is not None:
                existing = await EvidenceRepository.get_by_source_event_key(
                    db,
                    call_id=call_id,
                    provider=payload.provider,
                    check_type=payload.check_type,
                    source_event_key=payload.source_event_key,
                )
                if existing is not None:
                    return existing, False
            raise

    @staticmethod
    async def list_for_call(
        db: AsyncSession,
        *,
        call_id: str,
        check_type: str | None = None,
        provider: str | None = None,
        is_final: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[EvidenceItem], int]:
        if await db.get(CallSession, call_id) is None:
            raise AppAPIError(
                status_code=404,
                code="call_session_not_found",
                message=f"Call session '{call_id}' not found",
                details={"call_id": call_id},
            )

        conditions = [EvidenceItem.call_id == call_id]
        if check_type is not None:
            conditions.append(EvidenceItem.check_type == check_type)
        if provider is not None:
            conditions.append(EvidenceItem.provider == provider)
        if is_final is not None:
            conditions.append(EvidenceItem.is_final.is_(is_final))

        where_clause = and_(*conditions)
        total = int(
            await db.scalar(select(func.count()).select_from(EvidenceItem).where(where_clause)) or 0
        )
        rows = (
            await db.scalars(
                select(EvidenceItem)
                .where(where_clause)
                .order_by(EvidenceItem.created_at.asc(), EvidenceItem.evidence_id.asc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return list(rows), total

    @staticmethod
    async def summarize_for_call(db: AsyncSession, *, call_id: str) -> EvidenceSummary:
        rows = (
            await db.execute(
                select(
                    EvidenceItem.check_type,
                    EvidenceItem.status,
                    EvidenceItem.provider,
                    EvidenceItem.is_final,
                    func.count().label("cnt"),
                )
                .where(EvidenceItem.call_id == call_id)
                .group_by(
                    EvidenceItem.check_type,
                    EvidenceItem.status,
                    EvidenceItem.provider,
                    EvidenceItem.is_final,
                )
            )
        ).all()

        total = 0
        final_count = 0
        provisional_count = 0
        by_check_type: dict[str, int] = {}
        by_status: dict[str, int] = {}
        by_provider: dict[str, int] = {}

        for check_type, status, provider, is_final, count in rows:
            cnt = int(count)
            total += cnt
            if is_final:
                final_count += cnt
            else:
                provisional_count += cnt
            by_check_type[check_type] = by_check_type.get(check_type, 0) + cnt
            by_status[status] = by_status.get(status, 0) + cnt
            by_provider[provider] = by_provider.get(provider, 0) + cnt

        return EvidenceSummary(
            total=total,
            final_count=final_count,
            provisional_count=provisional_count,
            by_check_type=by_check_type,
            by_status=by_status,
            by_provider=by_provider,
        )

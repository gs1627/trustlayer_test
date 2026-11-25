from __future__ import annotations

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppAPIError
from app.db.models import CallSession, utc_now
from app.schemas.contracts import CallSessionDetailRead, CallSessionRead, TrustAssessmentRead
from app.services.evidence_repository import EvidenceRepository
from app.services.trust_assessment_repository import TrustAssessmentRepository


class CallSessionService:
    """Service operations for querying and managing persisted CallSession records."""

    @staticmethod
    async def list_sessions(
        db: AsyncSession,
        *,
        status: str | None = None,
        speaker_id: str | None = None,
        owner_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CallSession], int]:
        conditions = []
        if status is not None:
            conditions.append(CallSession.status == status)
        if speaker_id is not None:
            conditions.append(CallSession.speaker_id == speaker_id)
        if owner_id is not None:
            conditions.append(CallSession.owner_id == owner_id)

        where_clause = and_(*conditions) if conditions else None

        count_stmt = select(func.count()).select_from(CallSession)
        list_stmt = select(CallSession)
        if where_clause is not None:
            count_stmt = count_stmt.where(where_clause)
            list_stmt = list_stmt.where(where_clause)

        total = int(await db.scalar(count_stmt) or 0)
        rows = (
            await db.scalars(
                list_stmt.order_by(CallSession.created_at.desc(), CallSession.call_id.asc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return list(rows), total

    @staticmethod
    async def get_session_detail(db: AsyncSession, *, call_id: str) -> CallSessionDetailRead:
        session = await db.get(CallSession, call_id)
        if session is None:
            raise AppAPIError(
                status_code=404,
                code="call_session_not_found",
                message=f"Call session '{call_id}' not found",
                details={"call_id": call_id},
            )

        summary = await EvidenceRepository.summarize_for_call(db, call_id=call_id)
        latest_ta = await TrustAssessmentRepository.find_latest_for_call(db, call_id=call_id)

        base = CallSessionRead.model_validate(session).model_dump()
        return CallSessionDetailRead(
            **base,
            evidence_summary=summary,
            latest_trust_assessment=(
                TrustAssessmentRead.model_validate(latest_ta) if latest_ta is not None else None
            ),
        )

    @staticmethod
    async def end_session(
        db: AsyncSession,
        *,
        call_id: str,
        reason: str | None = None,
    ) -> tuple[CallSession, str | None]:
        """Idempotently terminate a CallSession; returns `(session, previous_status_if_changed)`."""
        session = await db.get(CallSession, call_id)
        if session is None:
            raise AppAPIError(
                status_code=404,
                code="call_session_not_found",
                message=f"Call session '{call_id}' not found",
                details={"call_id": call_id},
            )

        if session.ended_at is not None or session.status == "ended":
            if session.ended_at is None:
                session.ended_at = utc_now()
                session.updated_at = session.ended_at
                await db.commit()
                await db.refresh(session)
            return session, None

        previous_status = session.status
        now = utc_now()
        session.status = "ended"
        session.ended_at = now
        session.ended_reason = reason
        session.updated_at = now
        await db.commit()
        await db.refresh(session)
        return session, previous_status

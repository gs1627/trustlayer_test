from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppAPIError
from app.db.models import (
    CallSession,
    EvidenceItem,
    TrustAssessment,
    TrustAssessmentEvidence,
    utc_now,
)
from app.schemas.contracts import TrustAssessmentCreate


class TrustAssessmentRepository:
    """Repository for immutable Trust Engine evaluation snapshots."""

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        call_id: str,
        payload: TrustAssessmentCreate,
        commit: bool = True,
    ) -> TrustAssessment:
        if payload.call_id is not None and payload.call_id != call_id:
            raise AppAPIError(
                status_code=422,
                code="cross_call_mismatch",
                message="Payload call_id does not match URL call_id",
                details={"path_call_id": call_id, "payload_call_id": payload.call_id},
            )

        if await db.get(CallSession, call_id) is None:
            raise AppAPIError(
                status_code=404,
                code="call_session_not_found",
                message=f"Call session '{call_id}' not found",
                details={"call_id": call_id},
            )

        evidence_by_id: dict[str, EvidenceItem] = {}
        if payload.evidence_ids:
            rows = (
                await db.scalars(
                    select(EvidenceItem).where(EvidenceItem.evidence_id.in_(payload.evidence_ids))
                )
            ).all()
            evidence_by_id = {row.evidence_id: row for row in rows}

            missing_ids = [ev_id for ev_id in payload.evidence_ids if ev_id not in evidence_by_id]
            if missing_ids:
                raise AppAPIError(
                    status_code=422,
                    code="evidence_not_found",
                    message="One or more referenced evidence IDs do not exist",
                    details={"call_id": call_id, "missing_evidence_ids": missing_ids},
                )

            cross_call_ids = [
                ev_id for ev_id in payload.evidence_ids if evidence_by_id[ev_id].call_id != call_id
            ]
            if cross_call_ids:
                raise AppAPIError(
                    status_code=422,
                    code="cross_call_evidence_not_allowed",
                    message="Referenced evidence IDs must belong to the target call session",
                    details={"call_id": call_id, "cross_call_evidence_ids": cross_call_ids},
                )

        assessment = TrustAssessment(
            assessment_id=f"ta_{uuid.uuid4().hex}",
            call_id=call_id,
            trust_score=payload.trust_score,
            risk_level=payload.risk_level,
            recommended_action=payload.recommended_action,
            summary=payload.summary,
            reasons=list(payload.reasons),
            is_final=payload.is_final,
            model_version=payload.model_version,
            created_at=utc_now(),
        )
        db.add(assessment)
        await db.flush()

        for evidence_id in payload.evidence_ids:
            ev_row = evidence_by_id[evidence_id]
            db.add(
                TrustAssessmentEvidence(
                    assessment_id=assessment.assessment_id,
                    evidence_id=evidence_id,
                    call_id=call_id,
                    created_at=ev_row.created_at,
                )
            )

        if commit:
            await db.commit()
        else:
            await db.flush()

        loaded = await db.scalar(
            select(TrustAssessment)
            .options(selectinload(TrustAssessment.evidence_links))
            .where(TrustAssessment.assessment_id == assessment.assessment_id)
        )
        assert loaded is not None
        return loaded

    @staticmethod
    async def find_latest_for_call(db: AsyncSession, *, call_id: str) -> TrustAssessment | None:
        return await db.scalar(
            select(TrustAssessment)
            .options(selectinload(TrustAssessment.evidence_links))
            .where(TrustAssessment.call_id == call_id)
            .order_by(TrustAssessment.created_at.desc(), TrustAssessment.assessment_id.desc())
            .limit(1)
        )

    @staticmethod
    async def get_latest_for_call(db: AsyncSession, *, call_id: str) -> TrustAssessment:
        if await db.get(CallSession, call_id) is None:
            raise AppAPIError(
                status_code=404,
                code="call_session_not_found",
                message=f"Call session '{call_id}' not found",
                details={"call_id": call_id},
            )
        latest = await TrustAssessmentRepository.find_latest_for_call(db, call_id=call_id)
        if latest is None:
            raise AppAPIError(
                status_code=404,
                code="trust_assessment_not_found",
                message=f"No trust assessment exists yet for call session '{call_id}'",
                details={"call_id": call_id},
            )
        return latest

    @staticmethod
    async def list_for_call(
        db: AsyncSession,
        *,
        call_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[TrustAssessment], int]:
        if await db.get(CallSession, call_id) is None:
            raise AppAPIError(
                status_code=404,
                code="call_session_not_found",
                message=f"Call session '{call_id}' not found",
                details={"call_id": call_id},
            )
        total = int(
            await db.scalar(
                select(func.count())
                .select_from(TrustAssessment)
                .where(TrustAssessment.call_id == call_id)
            )
            or 0
        )
        rows = (
            await db.scalars(
                select(TrustAssessment)
                .options(selectinload(TrustAssessment.evidence_links))
                .where(TrustAssessment.call_id == call_id)
                .order_by(TrustAssessment.created_at.desc(), TrustAssessment.assessment_id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return list(rows), total

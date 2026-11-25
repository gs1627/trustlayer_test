import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    JSON,
    Integer,
    Numeric,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc_datetime(value: datetime | str | None) -> datetime | None:
    """Strictly parse a datetime or ISO-8601 string into a UTC-aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Timestamp string cannot be blank")
        if cleaned.endswith(("Z", "z")):
            cleaned = cleaned[:-1] + "+00:00"
        parsed = datetime.fromisoformat(cleaned)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    raise TypeError(f"Expected datetime, ISO-8601 string, or None, got {type(value).__name__}")


def safe_parse_utc_datetime(value: datetime | str | None) -> datetime | None:
    """Permissively parse a datetime or ISO-8601 string, returning None when invalid."""
    try:
        return parse_utc_datetime(value)
    except (TypeError, ValueError):
        return None


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware DateTime storing UTC and validating binds strictly."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | str | None, dialect: Any) -> datetime | None:
        return parse_utc_datetime(value)

    def process_result_value(self, value: datetime | str | None, dialect: Any) -> datetime | None:
        return parse_utc_datetime(value)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("delivery_id", name="uq_webhook_delivery_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    delivery_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    event_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    call_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    event_created_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="received", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class SpeakerProfile(Base):
    __tablename__ = "speaker_profiles"
    __table_args__ = (
        CheckConstraint("sample_count >= 0", name="ck_speaker_profiles_sample_count"),
    )

    speaker_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    consent_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consent_recorded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    enrollment_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="detectifai")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    operations: Mapped[list["ProviderOperation"]] = relationship(
        back_populates="speaker_profile",
        passive_deletes=True,
    )


class CallSession(Base):
    __tablename__ = "call_sessions"
    __table_args__ = (
        CheckConstraint(
            "checks_mode IN ('deepfake,verify', 'deepfake', 'deepfake,enroll')",
            name="ck_call_sessions_checks_mode",
        ),
        CheckConstraint(
            "checks_mode = 'deepfake' OR speaker_id IS NOT NULL",
            name="ck_call_sessions_speaker_required",
        ),
    )

    call_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    speaker_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    checks_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="deepfake,verify",
        server_default="deepfake,verify",
    )
    consent_confirmed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    consent_recorded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    provider_stream_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="created")
    last_deepfake_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_provider_event_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    ended_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    operations: Mapped[list["ProviderOperation"]] = relationship(
        back_populates="call_session",
        passive_deletes=True,
    )
    evidence_items: Mapped[list["EvidenceItem"]] = relationship(
        back_populates="call_session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    trust_assessments: Mapped[list["TrustAssessment"]] = relationship(
        back_populates="call_session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    simulated_transactions: Mapped[list["SimulatedTransaction"]] = relationship(
        back_populates="call_session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    speaker_profile: Mapped["SpeakerProfile | None"] = relationship(
        primaryjoin=lambda: foreign(CallSession.speaker_id) == SpeakerProfile.speaker_id,
        viewonly=True,
    )


class ProviderOperation(Base):
    __tablename__ = "provider_operations"
    __table_args__ = (
        UniqueConstraint("operation_id", name="uq_provider_operations_operation_id"),
        UniqueConstraint(
            "provider",
            "operation_type",
            "idempotency_key",
            name="uq_provider_operations_idempotency",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[str | None] = mapped_column(
        String(128),
        ForeignKey("call_sessions.call_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    speaker_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("speaker_profiles.speaker_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="detectifai", index=True)
    operation_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    request_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    operation_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    stream_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    credits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    call_session: Mapped["CallSession | None"] = relationship(back_populates="operations")
    speaker_profile: Mapped["SpeakerProfile | None"] = relationship(back_populates="operations")


class EvidenceItem(Base):
    __tablename__ = "evidence_items"
    __table_args__ = (
        UniqueConstraint("evidence_id", "call_id", name="uq_evidence_items_id_call"),
        UniqueConstraint(
            "call_id",
            "provider",
            "check_type",
            "source_event_key",
            name="uq_evidence_items_source_event",
        ),
        CheckConstraint(
            "check_type IN ('deepfake', 'speaker_verification', 'transcription', 'context')",
            name="ck_evidence_items_check_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'completed', 'failed', 'inconclusive')",
            name="ck_evidence_items_status",
        ),
    )

    evidence_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=lambda: f"ev_{uuid.uuid4().hex}",
    )
    call_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("call_sessions.call_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    speaker_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    check_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    verdict: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_early: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    source_channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_event_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_operation_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    provider_stream_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)

    call_session: Mapped["CallSession"] = relationship(back_populates="evidence_items")
    assessment_links: Mapped[list["TrustAssessmentEvidence"]] = relationship(
        back_populates="evidence_item",
        cascade="all, delete-orphan",
        passive_deletes=True,
        overlaps="evidence_links,evidence_items",
    )


class TrustAssessment(Base):
    """Immutable Trust Engine evaluation snapshot."""

    __tablename__ = "trust_assessments"
    __table_args__ = (
        UniqueConstraint("assessment_id", "call_id", name="uq_trust_assessments_id_call"),
        CheckConstraint(
            "trust_score >= 0.0 AND trust_score <= 1.0",
            name="ck_trust_assessments_score_bounds",
        ),
        CheckConstraint(
            "risk_level IN ('low', 'medium', 'high', 'critical', 'inconclusive')",
            name="ck_trust_assessments_risk_level",
        ),
        CheckConstraint(
            "recommended_action IN ('allow', 'step_up_verify', 'hold', 'block')",
            name="ck_trust_assessments_action",
        ),
    )

    assessment_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=lambda: f"ta_{uuid.uuid4().hex}",
    )
    call_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("call_sessions.call_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trust_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    recommended_action: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)

    call_session: Mapped["CallSession"] = relationship(back_populates="trust_assessments")
    evidence_links: Mapped[list["TrustAssessmentEvidence"]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by=lambda: (TrustAssessmentEvidence.created_at, TrustAssessmentEvidence.evidence_id),
        overlaps="assessment_links,evidence_items",
    )
    evidence_items: Mapped[list["EvidenceItem"]] = relationship(
        secondary="trust_assessment_evidence",
        primaryjoin="and_(TrustAssessment.assessment_id == TrustAssessmentEvidence.assessment_id, TrustAssessment.call_id == TrustAssessmentEvidence.call_id)",
        secondaryjoin="and_(EvidenceItem.evidence_id == TrustAssessmentEvidence.evidence_id, EvidenceItem.call_id == TrustAssessmentEvidence.call_id)",
        order_by=lambda: (EvidenceItem.created_at, EvidenceItem.evidence_id),
        overlaps="assessment_links,evidence_links,evidence_item,assessment",
        viewonly=True,
    )

    @property
    def evidence_ids(self) -> list[str]:
        return [link.evidence_id for link in self.evidence_links]


class TrustAssessmentEvidence(Base):
    """Relational join table binding trust assessments to evidence from the same call."""

    __tablename__ = "trust_assessment_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["assessment_id", "call_id"],
            ["trust_assessments.assessment_id", "trust_assessments.call_id"],
            ondelete="CASCADE",
            name="fk_tae_assessment_call",
        ),
        ForeignKeyConstraint(
            ["evidence_id", "call_id"],
            ["evidence_items.evidence_id", "evidence_items.call_id"],
            ondelete="CASCADE",
            name="fk_tae_evidence_call",
        ),
    )

    assessment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    call_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)

    assessment: Mapped["TrustAssessment"] = relationship(
        back_populates="evidence_links",
        overlaps="evidence_items,assessment_links,evidence_item",
    )
    evidence_item: Mapped["EvidenceItem"] = relationship(
        back_populates="assessment_links",
        overlaps="evidence_items,evidence_links,assessment",
    )


class SimulatedTransaction(Base):
    """Persisted simulated transaction policy evaluation record (no real banking execution)."""

    __tablename__ = "simulated_transactions"
    __table_args__ = (
        CheckConstraint(
            "action_type IN ('fund_transfer', 'beneficiary_add', 'credential_reset', 'limit_change')",
            name="ck_simulated_transactions_action_type",
        ),
        CheckConstraint("amount > 0", name="ck_simulated_transactions_amount_positive"),
        CheckConstraint(
            "decision IN ('allow', 'step_up_verify', 'hold', 'block')",
            name="ck_simulated_transactions_decision",
        ),
    )

    transaction_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=lambda: f"tx_{uuid.uuid4().hex}",
    )
    call_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("call_sessions.call_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assessment_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("trust_assessments.assessment_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_subject: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Any] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    recipient_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decision: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    policy_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False, default="policy-v1")
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)

    call_session: Mapped["CallSession"] = relationship(back_populates="simulated_transactions")
    last_provider_event_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class DemoTransactionRecord(Base):
    __tablename__ = "demo_transaction_records"

    action_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    call_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_text: Mapped[str | None] = mapped_column(String(40), nullable=True)
    beneficiary_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="simulated")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

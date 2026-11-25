from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SPEAKER_ID_PATTERN = r"^[A-Za-z0-9_.:-]{1,64}$"

ChecksMode = Literal["deepfake,verify", "deepfake", "deepfake,enroll"]
EvidenceCheckType = Literal["deepfake", "speaker_verification", "transcription", "context"]
EvidenceStatus = Literal["pending", "completed", "failed", "inconclusive"]
EvidenceSourceChannel = Literal["rest", "websocket", "webhook", "internal"]
TrustRiskLevel = Literal["low", "medium", "high", "critical", "inconclusive"]
TrustRecommendedAction = Literal["allow", "step_up_verify", "hold", "block"]
DomainEventType = Literal["evidence.added", "trust.updated", "call.status_changed"]
SimulatedTransactionAction = Literal[
    "fund_transfer",
    "beneficiary_add",
    "credential_reset",
    "limit_change",
]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    app: str
    environment: str
    database: Literal["connected", "unavailable"]
    detectif_configured: bool


class ProviderOperationResponse(BaseModel):
    provider: Literal["detectifai"] = "detectifai"
    operation: str
    request_id: str | None = None
    operation_id: str | None = None
    correlation_id: str | None = None
    status: str | None = None
    raw: dict[str, Any]


class WebhookAcceptedResponse(BaseModel):
    accepted: bool = True
    duplicate: bool = False
    delivery_id: str
    status: str | None = None
    call_id: str | None = None


class ErrorDetail(BaseModel):
    """Structured error payload for standardized TRUSTLAYER API errors."""

    code: str
    message: str
    provider: str | None = None
    request_id: str | None = None
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Error envelope preserving FastAPI's `detail` alongside structured metadata."""

    detail: str | dict[str, Any]
    error: ErrorDetail


class CallSessionCreate(BaseModel):
    call_id: str = Field(min_length=3, max_length=128)
    speaker_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=SPEAKER_ID_PATTERN,
    )
    checks_mode: ChecksMode = "deepfake,verify"
    consent_confirmed: bool = False
    display_name: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _validate_mode_requirements(self) -> "CallSessionCreate":
        if self.checks_mode in {"deepfake,verify", "deepfake,enroll"} and not self.speaker_id:
            raise ValueError(f"speaker_id is required when checks_mode is '{self.checks_mode}'")
        if self.checks_mode == "deepfake,enroll" and not self.consent_confirmed:
            raise ValueError("consent_confirmed=true is required when checks_mode is 'deepfake,enroll'")
        return self


class CallSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    call_id: str
    owner_id: str | None = None
    speaker_id: str | None = None
    checks_mode: ChecksMode = "deepfake,verify"
    consent_confirmed: bool = False
    consent_recorded_at: datetime | None = None
    provider_stream_id: str | None = None
    status: str
    last_deepfake_sequence: int = 0
    last_provider_event_at: datetime | None = None
    ended_at: datetime | None = None
    ended_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class CallSessionEndRequest(BaseModel):
    """Optional payload when explicitly ending a call session."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=64)

    @field_validator("reason")
    @classmethod
    def _normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class SpeakerProfileCreate(BaseModel):
    speaker_id: str = Field(min_length=1, max_length=64, pattern=SPEAKER_ID_PATTERN)
    display_name: str | None = Field(default=None, max_length=128)
    consent_confirmed: bool
    provider: str = Field(default="detectifai", min_length=1, max_length=32)

    @model_validator(mode="after")
    def _require_consent(self) -> "SpeakerProfileCreate":
        if not self.consent_confirmed:
            raise ValueError("Explicit speaker consent is required before creating a speaker profile")
        return self


class SpeakerProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    speaker_id: str
    owner_id: str | None = None
    display_name: str | None = None
    consent_confirmed: bool
    consent_recorded_at: datetime | None = None
    enrollment_status: str
    sample_count: int
    provider: str
    created_at: datetime
    updated_at: datetime


class ProviderOperationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    call_id: str | None = None
    speaker_id: str | None = None
    provider: str
    operation_type: str
    request_id: str | None = None
    operation_id: str | None = None
    stream_id: str | None = None
    idempotency_key: str | None = None
    correlation_id: str | None = None
    status: str
    retry_count: int = 0
    credits: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    failure_details: dict[str, Any] | None = None
    raw_response: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class _EvidenceBase(BaseModel):
    """Provider-neutral evidence base fields shared across Member 1 and Member 3.

    `is_early` and `is_final` represent distinct provider semantics and must never
    be conflated (e.g., a live update with `early=False` may still have `final=False`).
    """

    model_config = ConfigDict(extra="allow")

    call_id: str = Field(min_length=3, max_length=128)
    provider: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=64)
    check_type: EvidenceCheckType
    status: EvidenceStatus
    verdict: str | None = Field(default=None, max_length=64)
    raw_score: float | None = Field(default=None, allow_inf_nan=False)
    score_type: str | None = Field(default=None, max_length=64)
    is_early: bool | None = None
    is_final: bool = False
    speaker_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=SPEAKER_ID_PATTERN,
    )
    source_channel: EvidenceSourceChannel | None = None
    source_event_key: str | None = Field(default=None, min_length=1, max_length=200)
    sequence: int | None = Field(default=None, ge=0)
    provider_operation_id: str | None = Field(default=None, max_length=160)
    provider_request_id: str | None = Field(default=None, max_length=160)
    provider_stream_id: str | None = Field(default=None, max_length=160)
    observed_at: datetime | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class EvidenceItemCreate(_EvidenceBase):
    """Input contract for appending new evidence; server generates `evidence_id`."""

    @model_validator(mode="after")
    def _disallow_server_generated_fields(self) -> "EvidenceItemCreate":
        extras = self.model_extra or {}
        if "evidence_id" in extras or "created_at" in extras:
            raise ValueError("evidence_id and created_at are generated by the backend")
        return self


class EvidenceItemRead(_EvidenceBase):
    """Persisted append-only evidence record returned by backend APIs."""

    model_config = ConfigDict(extra="allow", from_attributes=True)

    evidence_id: str
    created_at: datetime


class EvidenceItem(_EvidenceBase):
    """Internal, provider-neutral evidence contract shared with Member 3."""

    model_config = ConfigDict(extra="allow", from_attributes=True)

    evidence_id: str | None = None
    created_at: datetime | None = None


class TrustAssessmentCreate(BaseModel):
    """Input contract for immutable Trust Engine evaluation snapshots."""

    model_config = ConfigDict(extra="forbid")

    call_id: str | None = Field(default=None, min_length=3, max_length=128)
    trust_score: float = Field(
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
        description="Bounded Trust Engine model score in [0.0, 1.0]; not automatically a calibrated probability.",
    )
    risk_level: TrustRiskLevel
    recommended_action: TrustRecommendedAction
    summary: str = Field(min_length=1, max_length=2000)
    reasons: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    is_final: bool = False
    model_version: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def _validate_evidence_ids(self) -> "TrustAssessmentCreate":
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in self.evidence_ids:
            value = item.strip()
            if not value:
                raise ValueError("evidence_ids must not contain empty values")
            if value in seen:
                raise ValueError(f"Duplicate evidence_id '{value}' in evidence_ids")
            seen.add(value)
            cleaned.append(value)
        self.evidence_ids = cleaned
        return self


class TrustAssessmentRead(BaseModel):
    """Persisted immutable Trust Engine assessment snapshot."""

    model_config = ConfigDict(from_attributes=True)

    assessment_id: str
    call_id: str
    trust_score: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    risk_level: TrustRiskLevel
    recommended_action: TrustRecommendedAction
    summary: str
    reasons: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    is_final: bool = False
    model_version: str
    created_at: datetime


class EvidenceSummary(BaseModel):
    """Aggregate evidence counts for a call session."""

    total: int = Field(default=0, ge=0)
    final_count: int = Field(default=0, ge=0)
    provisional_count: int = Field(default=0, ge=0)
    by_check_type: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
    by_provider: dict[str, int] = Field(default_factory=dict)


class CallSessionDetailRead(CallSessionRead):
    """Detailed call session snapshot including evidence counts and latest assessment."""

    evidence_summary: EvidenceSummary = Field(default_factory=EvidenceSummary)
    latest_trust_assessment: TrustAssessmentRead | None = None


class PaginatedCallSessionsResponse(BaseModel):
    """Paginated list of call sessions."""

    items: list[CallSessionRead]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class PaginatedEvidenceResponse(BaseModel):
    """Paginated list of append-only evidence items."""

    items: list[EvidenceItemRead]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class PaginatedTrustAssessmentsResponse(BaseModel):
    """Paginated list of immutable trust assessments."""

    items: list[TrustAssessmentRead]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class DomainEvent(BaseModel):
    """Internal domain event envelope for Priority 4/5 real-time subscribers."""

    event_id: str
    event_type: DomainEventType
    call_id: str
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class SimulatedTransactionRequest(BaseModel):
    """Proposed simulated transaction request contract (no real execution)."""

    action_type: SimulatedTransactionAction
    amount: Decimal = Field(gt=Decimal("0"), max_digits=14, decimal_places=2)
    currency: str = Field(default="INR", min_length=3, max_length=8, pattern=r"^[A-Z]{3,8}$")
    recipient_ref: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=500)


class SimulatedTransactionResponse(BaseModel):
    """Persisted simulated transaction evaluation response contract."""

    model_config = ConfigDict(from_attributes=True)

    transaction_id: str
    call_id: str
    assessment_id: str | None = None
    action_type: SimulatedTransactionAction
    amount: Decimal
    currency: str
    decision: TrustRecommendedAction
    policy_reasons: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    policy_version: str | None = None
    simulated: Literal[True] = True
    created_at: datetime


AuthRole = Literal["admin", "service", "operator", "user"]


class AuthTokenRequest(BaseModel):
    """Request to mint a short-lived signed JWT using backend service credentials."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=128)
    role: AuthRole = "user"
    scopes: list[str] = Field(default_factory=list)
    expires_in_seconds: int | None = Field(default=None, ge=60, le=86400)


class AuthTokenResponse(BaseModel):
    """Issued JWT bearer token metadata."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    subject: str
    role: AuthRole
    scopes: list[str] = Field(default_factory=list)


class AuthPrincipalRead(BaseModel):
    """Resolved authentication principal for the current request."""

    subject: str
    role: str
    auth_type: str
    scopes: list[str] = Field(default_factory=list)


class WebhookEventRead(BaseModel):
    """Webhook delivery lifecycle and reconciliation record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    delivery_id: str
    event_id: str | None = None
    event_type: str
    call_id: str | None = None
    status: str
    attempt_count: int = 1
    processing_error: str | None = None
    event_created_at: datetime | None = None
    received_at: datetime
    last_attempt_at: datetime | None = None
    next_retry_at: datetime | None = None
    processed_at: datetime | None = None
    dead_lettered_at: datetime | None = None


class PaginatedWebhookEventsResponse(BaseModel):
    """Paginated list of webhook delivery records."""

    items: list[WebhookEventRead]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class PaginatedProviderOperationsResponse(BaseModel):
    """Paginated list of tracked provider operations."""

    items: list[ProviderOperationRead]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class WebhookReconcileResponse(BaseModel):
    """Summary of webhook reconciliation execution."""

    attempted: int = 0
    processed: int = 0
    still_unmatched: int = 0
    failed: int = 0
    dead_lettered: int = 0

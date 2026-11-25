from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.contracts import (
    CallSessionCreate,
    CallSessionDetailRead,
    CallSessionEndRequest,
    DomainEvent,
    ErrorDetail,
    ErrorResponse,
    EvidenceItem,
    EvidenceItemCreate,
    EvidenceItemRead,
    EvidenceSummary,
    HealthResponse,
    PaginatedCallSessionsResponse,
    PaginatedEvidenceResponse,
    PaginatedTrustAssessmentsResponse,
    ProviderOperationResponse,
    SimulatedTransactionRequest,
    SimulatedTransactionResponse,
    SpeakerProfileCreate,
    TrustAssessmentCreate,
    TrustAssessmentRead,
    WebhookAcceptedResponse,
)


def test_existing_response_contracts_preserved():
    health = HealthResponse(
        status="ok",
        app="TRUSTLAYER Backend",
        environment="test",
        database="connected",
        detectif_configured=False,
    )
    assert health.status == "ok"

    op = ProviderOperationResponse(
        operation="deepfake_detection",
        request_id="req_1",
        operation_id="op_1",
        raw={"ok": True},
    )
    assert op.provider == "detectifai"

    wh = WebhookAcceptedResponse(delivery_id="msg_1")
    assert wh.accepted is True and wh.duplicate is False


def test_evidence_finality_preserves_is_early_and_is_final_independently():
    # Live update with early=False can still have final=False
    live_non_early_non_final = EvidenceItemCreate(
        call_id="CALL_001",
        provider="detectifai",
        model="aletheia",
        check_type="deepfake",
        status="pending",
        verdict="real",
        raw_score=0.05,
        score_type="synthetic_score",
        is_early=False,
        is_final=False,
        source_channel="websocket",
        source_event_key="str_1:deepfake:seq_2",
        sequence=2,
    )
    assert live_non_early_non_final.is_early is False
    assert live_non_early_non_final.is_final is False
    assert live_non_early_non_final.provider_operation_id is None

    # Compat EvidenceItem retains extra="allow"
    compat = EvidenceItem(
        call_id="CALL_001",
        provider="sarvam",
        model="saarika:v2",
        check_type="transcription",
        status="completed",
        is_final=True,
        custom_extension="preserved",
    )
    assert compat.custom_extension == "preserved"


def test_evidence_create_rejects_server_generated_fields():
    with pytest.raises(ValidationError):
        EvidenceItemCreate(
            call_id="CALL_001",
            provider="detectifai",
            model="aletheia",
            check_type="deepfake",
            status="completed",
            evidence_id="client_forged_id",
        )

    read = EvidenceItemRead(
        evidence_id="ev_123",
        call_id="CALL_001",
        provider="detectifai",
        model="aletheia",
        check_type="deepfake",
        status="completed",
        is_final=True,
        created_at=datetime.now(timezone.utc),
    )
    assert read.evidence_id == "ev_123"


def test_call_session_create_checks_mode_and_consent_rules():
    # Backward compatibility: defaults to deepfake,verify
    default_call = CallSessionCreate(call_id="CALL_001", speaker_id="CUSTOMER_001")
    assert default_call.checks_mode == "deepfake,verify"

    # Deepfake-only allows nullable speaker_id
    deepfake_only = CallSessionCreate(call_id="CALL_002", checks_mode="deepfake")
    assert deepfake_only.speaker_id is None

    # Verify requires speaker_id
    with pytest.raises(ValidationError):
        CallSessionCreate(call_id="CALL_003", checks_mode="deepfake,verify")

    # Enroll requires both speaker_id and consent_confirmed=True
    with pytest.raises(ValidationError):
        CallSessionCreate(call_id="CALL_004", speaker_id="SPK_1", checks_mode="deepfake,enroll")

    enrolled = CallSessionCreate(
        call_id="CALL_005",
        speaker_id="SPK_1",
        checks_mode="deepfake,enroll",
        consent_confirmed=True,
        display_name="Alice",
    )
    assert enrolled.consent_confirmed is True


def test_speaker_profile_create_requires_consent():
    with pytest.raises(ValidationError):
        SpeakerProfileCreate(speaker_id="SPK_1", consent_confirmed=False)


def test_trust_assessment_create_bounds_and_evidence_ids():
    ok = TrustAssessmentCreate(
        trust_score=0.75,
        risk_level="low",
        recommended_action="allow",
        summary="Voice verified and natural.",
        reasons=["eidos:match", "aletheia:real"],
        evidence_ids=["ev_1", "ev_2"],
        is_final=True,
        model_version="trust-v1",
    )
    assert ok.trust_score == 0.75

    with pytest.raises(ValidationError):
        TrustAssessmentCreate(
            trust_score=1.2,
            risk_level="low",
            recommended_action="allow",
            summary="Out of range",
            model_version="trust-v1",
        )

    with pytest.raises(ValidationError):
        TrustAssessmentCreate(
            trust_score=0.5,
            risk_level="medium",
            recommended_action="hold",
            summary="Duplicate evidence",
            evidence_ids=["ev_1", "ev_1"],
            model_version="trust-v1",
        )


def test_simulated_transaction_uses_decimal_and_error_envelope():
    tx_req = SimulatedTransactionRequest(
        action_type="fund_transfer",
        amount=Decimal("25000.50"),
        currency="INR",
        recipient_ref="DEMO_01",
    )
    assert tx_req.amount == Decimal("25000.50")

    with pytest.raises(ValidationError):
        SimulatedTransactionRequest(
            action_type="fund_transfer",
            amount=Decimal("0.00"),
            currency="INR",
        )

    tx_resp = SimulatedTransactionResponse(
        transaction_id="tx_1",
        call_id="CALL_001",
        assessment_id="ta_1",
        action_type="fund_transfer",
        amount=Decimal("25000.50"),
        currency="INR",
        decision="step_up_verify",
        policy_reasons=["provisional_trust_score"],
        created_at=datetime.now(timezone.utc),
    )
    assert tx_resp.simulated is True

    err = ErrorResponse(
        detail="Not found",
        error=ErrorDetail(code="call_session_not_found", message="Not found", retryable=False),
    )
    assert err.error.code == "call_session_not_found"


@pytest.mark.parametrize("bad_score", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_scores_rejected_for_trust_and_evidence(bad_score: float):
    with pytest.raises(ValidationError):
        EvidenceItemCreate(
            call_id="CALL_001",
            provider="detectifai",
            model="aletheia",
            check_type="deepfake",
            status="completed",
            raw_score=bad_score,
        )

    with pytest.raises(ValidationError):
        TrustAssessmentCreate(
            trust_score=bad_score,
            risk_level="inconclusive",
            recommended_action="hold",
            summary="Non-finite score",
            model_version="trust-v1",
        )

    with pytest.raises(ValidationError):
        TrustAssessmentRead(
            assessment_id="ta_1",
            call_id="CALL_001",
            trust_score=bad_score,
            risk_level="inconclusive",
            recommended_action="hold",
            summary="Non-finite score",
            model_version="trust-v1",
            created_at=datetime.now(timezone.utc),
        )


def test_trust_assessment_create_protects_generated_ids():
    with pytest.raises(ValidationError):
        TrustAssessmentCreate(
            assessment_id="client_forged_ta",
            trust_score=0.8,
            risk_level="low",
            recommended_action="allow",
            summary="Attempted ID injection",
            model_version="trust-v1",
        )

    with pytest.raises(ValidationError):
        TrustAssessmentCreate(
            created_at=datetime.now(timezone.utc),
            trust_score=0.8,
            risk_level="low",
            recommended_action="allow",
            summary="Attempted timestamp injection",
            model_version="trust-v1",
        )


def test_priority3_response_and_event_contracts():
    end_req = CallSessionEndRequest(reason="   caller_hangup   ")
    assert end_req.reason == "caller_hangup"
    assert CallSessionEndRequest(reason="   ").reason is None

    now = datetime.now(timezone.utc)
    detail = CallSessionDetailRead(
        call_id="CALL_DETAIL",
        speaker_id="SPK_1",
        checks_mode="deepfake,verify",
        consent_confirmed=True,
        status="active",
        created_at=now,
        updated_at=now,
        evidence_summary=EvidenceSummary(total=1, final_count=1, provisional_count=0),
    )
    assert detail.evidence_summary.total == 1

    ev = EvidenceItemRead(
        evidence_id="ev_1",
        call_id="CALL_DETAIL",
        provider="detectifai",
        model="aletheia",
        check_type="deepfake",
        status="completed",
        is_final=True,
        created_at=now,
    )
    assert PaginatedEvidenceResponse(items=[ev], total=1, limit=50, offset=0).total == 1
    assert PaginatedCallSessionsResponse(items=[], total=0, limit=50, offset=0).offset == 0
    assert PaginatedTrustAssessmentsResponse(items=[], total=0, limit=50, offset=0).limit == 50

    domain_evt = DomainEvent(
        event_id="evpub_1",
        event_type="evidence.added",
        call_id="CALL_DETAIL",
        occurred_at=now,
        payload={"evidence_id": "ev_1"},
    )
    assert domain_evt.event_type == "evidence.added"

from __future__ import annotations

from decimal import Decimal
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppAPIError
from app.db.models import (
    CallSession,
    EvidenceItem,
    ProviderOperation,
    SimulatedTransaction,
    TrustAssessment,
    utc_now,
)
from app.schemas.contracts import (
    SimulatedTransactionRequest,
    SimulatedTransactionResponse,
    TrustRecommendedAction,
)
from app.services.evidence_repository import EvidenceRepository
from app.services.trust_assessment_repository import TrustAssessmentRepository

POLICY_VERSION = "policy-v1"
_ACTION_PRECEDENCE: dict[TrustRecommendedAction, int] = {
    "allow": 0,
    "step_up_verify": 1,
    "hold": 2,
    "block": 3,
}
_RISK_VERDICT_CONTEXT_MARKERS = frozenset(
    {
        "high_risk",
        "critical_risk",
        "social_engineering",
        "high_urgency_credential_reset",
        "scam",
        "fraud",
        "coercion",
        "impersonation",
        "suspicious",
    }
)


def _elevate(
    current: TrustRecommendedAction,
    candidate: TrustRecommendedAction,
    reasons: list[str],
    reason: str,
) -> TrustRecommendedAction:
    if reason not in reasons:
        reasons.append(reason)
    if _ACTION_PRECEDENCE[candidate] > _ACTION_PRECEDENCE[current]:
        return candidate
    return current


def _pick_authoritative_check(items: list[EvidenceItem], check_type: str) -> EvidenceItem | None:
    matching = [item for item in items if item.check_type == check_type]
    if not matching:
        return None
    finals = [item for item in matching if item.is_final]
    if finals:
        return finals[-1]
    return matching[-1]


def evaluate_transaction_policy(
    *,
    call_session: CallSession,
    latest_assessment: TrustAssessment | None,
    evidence_items: list[EvidenceItem],
    failed_operations_count: int,
    request: SimulatedTransactionRequest,
    settings: Settings | None = None,
) -> tuple[TrustRecommendedAction, list[str], list[str]]:
    """Evaluate a conservative banking transaction policy over persisted trust and evidence.

    Scores are treated as bounded model indicators, never calibrated probabilities.
    Decision precedence: `block` > `hold` > `step_up_verify` > `allow`.
    """
    cfg = settings or get_settings()
    decision: TrustRecommendedAction = "allow"
    reasons: list[str] = []

    deepfake_item = _pick_authoritative_check(evidence_items, "deepfake")
    verify_item = _pick_authoritative_check(evidence_items, "speaker_verification")
    context_item = _pick_authoritative_check(evidence_items, "context")

    is_high_value = Decimal(request.amount) >= Decimal(cfg.tx_policy_high_value_amount)

    # 1. Explicit hard-stop signals -> block
    if deepfake_item is not None and deepfake_item.verdict == "fake":
        if deepfake_item.is_final:
            decision = _elevate(decision, "block", reasons, "final_deepfake_detected")
        else:
            target: TrustRecommendedAction = "block" if is_high_value else "step_up_verify"
            decision = _elevate(decision, target, reasons, "provisional_deepfake_anomaly")

    if (
        call_session.checks_mode == "deepfake,verify"
        and verify_item is not None
        and verify_item.verdict == "no_match"
    ):
        if verify_item.is_final:
            decision = _elevate(decision, "block", reasons, "final_speaker_verification_mismatch")
        else:
            decision = _elevate(decision, "step_up_verify", reasons, "provisional_speaker_mismatch")

    if call_session.status == "ended":
        decision = _elevate(decision, "block", reasons, "call_session_already_ended")

    # 2. Assessment signals
    if latest_assessment is None:
        decision = _elevate(decision, "hold", reasons, "missing_trust_assessment")
    else:
        if latest_assessment.recommended_action == "block" or latest_assessment.risk_level == "critical":
            decision = _elevate(decision, "block", reasons, f"trust_assessment_{latest_assessment.risk_level}")
        elif latest_assessment.trust_score < cfg.tx_policy_block_trust_score:
            decision = _elevate(decision, "block", reasons, "trust_score_below_block_threshold")
        elif latest_assessment.recommended_action == "hold" or latest_assessment.risk_level == "inconclusive":
            decision = _elevate(decision, "hold", reasons, "trust_assessment_requires_hold")
        elif latest_assessment.recommended_action == "step_up_verify" or latest_assessment.risk_level in {
            "medium",
            "high",
        }:
            if is_high_value and latest_assessment.risk_level == "high":
                decision = _elevate(decision, "block", reasons, "high_risk_high_value_transaction")
            else:
                decision = _elevate(decision, "step_up_verify", reasons, f"trust_risk_{latest_assessment.risk_level}")

        if latest_assessment.trust_score < cfg.tx_policy_min_allow_trust_score and decision != "block":
            decision = _elevate(decision, "step_up_verify", reasons, "trust_score_below_allow_threshold")

        if not latest_assessment.is_final:
            decision = _elevate(decision, "step_up_verify", reasons, "provisional_trust_assessment")

    # 3. Completeness & error checks for deepfake, verification, context, and operations
    if cfg.tx_policy_require_final_deepfake:
        if deepfake_item is None:
            decision = _elevate(decision, "hold", reasons, "missing_deepfake_evidence")
        elif deepfake_item.status in {"failed", "inconclusive"}:
            decision = _elevate(decision, "hold", reasons, f"deepfake_{deepfake_item.status}")
        elif not deepfake_item.is_final:
            decision = _elevate(decision, "step_up_verify", reasons, "provisional_deepfake_only")

    if (
        call_session.checks_mode == "deepfake,verify"
        and cfg.tx_policy_require_final_verification_when_configured
    ):
        if verify_item is None:
            decision = _elevate(decision, "hold", reasons, "missing_speaker_verification_evidence")
        elif verify_item.status in {"failed", "inconclusive"}:
            decision = _elevate(decision, "hold", reasons, f"speaker_verification_{verify_item.status}")
        elif not verify_item.is_final:
            decision = _elevate(decision, "step_up_verify", reasons, "provisional_verification_only")

    if context_item is not None:
        if context_item.status in {"failed", "inconclusive"}:
            decision = _elevate(decision, "step_up_verify", reasons, f"context_analysis_{context_item.status}")
        elif context_item.verdict and context_item.verdict.lower() in _RISK_VERDICT_CONTEXT_MARKERS:
            target = "block" if is_high_value else "step_up_verify"
            decision = _elevate(decision, target, reasons, f"context_risk_{context_item.verdict.lower()}")

    if failed_operations_count > 0:
        decision = _elevate(decision, "hold", reasons, "failed_provider_operation_recorded")

    if is_high_value and (context_item is None or not context_item.is_final):
        decision = _elevate(decision, "step_up_verify", reasons, "high_value_missing_final_context")

    if not reasons and decision == "allow":
        reasons.append("all_checks_verified_within_policy")

    referenced_evidence = (
        list(latest_assessment.evidence_ids)
        if latest_assessment is not None and latest_assessment.evidence_ids
        else [item.evidence_id for item in evidence_items]
    )
    return decision, reasons, referenced_evidence


async def simulate_transaction_for_call(
    db: AsyncSession,
    *,
    call_session: CallSession,
    request: SimulatedTransactionRequest,
    actor_subject: str | None = None,
    settings: Settings | None = None,
) -> SimulatedTransactionResponse:
    """Evaluate policy and persist a simulated-only transaction audit record."""
    latest_ta = await TrustAssessmentRepository.find_latest_for_call(db, call_id=call_session.call_id)
    evidence_items, _ = await EvidenceRepository.list_for_call(
        db,
        call_id=call_session.call_id,
        limit=200,
        offset=0,
    )
    failed_ops = int(
        await db.scalar(
            select(func.count())
            .select_from(ProviderOperation)
            .where(
                ProviderOperation.call_id == call_session.call_id,
                ProviderOperation.status == "failed",
            )
        )
        or 0
    )

    decision, reasons, evidence_ids = evaluate_transaction_policy(
        call_session=call_session,
        latest_assessment=latest_ta,
        evidence_items=evidence_items,
        failed_operations_count=failed_ops,
        request=request,
        settings=settings,
    )

    tx = SimulatedTransaction(
        transaction_id=f"tx_{uuid.uuid4().hex}",
        call_id=call_session.call_id,
        assessment_id=latest_ta.assessment_id if latest_ta is not None else None,
        actor_subject=actor_subject,
        action_type=request.action_type,
        amount=request.amount,
        currency=request.currency,
        recipient_ref=request.recipient_ref,
        notes=request.notes,
        decision=decision,
        policy_reasons=reasons,
        evidence_ids=evidence_ids,
        policy_version=POLICY_VERSION,
        simulated=True,
        created_at=utc_now(),
    )
    db.add(tx)
    await db.commit()
    await db.refresh(tx)

    return SimulatedTransactionResponse(
        transaction_id=tx.transaction_id,
        call_id=tx.call_id,
        assessment_id=tx.assessment_id,
        action_type=tx.action_type,  # type: ignore[arg-type]
        amount=tx.amount,
        currency=tx.currency,
        decision=tx.decision,  # type: ignore[arg-type]
        policy_reasons=list(tx.policy_reasons),
        evidence_ids=list(tx.evidence_ids),
        policy_version=tx.policy_version,
        simulated=True,
        created_at=tx.created_at,
    )

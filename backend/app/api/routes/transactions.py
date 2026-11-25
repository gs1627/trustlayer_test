from decimal import Decimal
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_backend_access, require_demo_mode
from app.db.models import CallSession, DemoTransactionRecord
from app.db.session import get_db
from app.security.challenge_manager import ChallengeGrant, ChallengeManager
from app.security.policy_engine import PolicyDecision, PolicyEngine
from app.security.transaction_guard import GuardResult, TransactionGuard
from app.services.trust_engine import TrustDecision


router = APIRouter(
    prefix="/transactions",
    tags=["demo transactions"],
    dependencies=[Depends(require_demo_mode), Depends(require_backend_access)],
)
policy_engine = PolicyEngine()
challenge_manager = ChallengeManager()
transaction_guard = TransactionGuard(
    policy_engine=policy_engine,
    challenge_manager=challenge_manager,
)


class DemoActionRequest(BaseModel):
    customer_id: str = Field(min_length=1, max_length=128)
    call_id: str = Field(min_length=3, max_length=128)
    trust_decision: TrustDecision
    intent: str = Field(min_length=1, max_length=64)
    amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    beneficiary_ref: str | None = Field(default=None, max_length=256)


class SimulateActionRequest(DemoActionRequest):
    challenge_id: str | None = Field(default=None, max_length=64)
    challenge_token: str | None = Field(default=None, max_length=128)


class SimulationResponse(BaseModel):
    guard: GuardResult
    simulated_action_recorded: bool
    action_id: str | None = None
    note: str = "Demo only. No real financial transaction was executed."


async def _require_call_session(db: AsyncSession, call_id: str) -> None:
    if await db.get(CallSession, call_id) is None:
        raise HTTPException(status_code=404, detail="Call session not found")


def _validate_demo_identity(payload: DemoActionRequest) -> None:
    if not payload.customer_id.strip() or not payload.call_id.strip():
        raise HTTPException(status_code=422, detail="customer_id and call_id cannot be blank")


def _policy_for(payload: DemoActionRequest) -> PolicyDecision:
    _validate_demo_identity(payload)
    return policy_engine.evaluate(
        trust_decision=payload.trust_decision,
        intent=payload.intent,
        amount=float(payload.amount) if payload.amount is not None else None,
        beneficiary_ref=payload.beneficiary_ref,
    )


@router.post(
    "/challenges",
    response_model=ChallengeGrant,
    description=(
        "Development-only challenge issuance. Customer identity and trust evidence "
        "are caller-supplied; the returned token is not suitable for real banking."
    ),
)
async def issue_challenge(
    payload: DemoActionRequest,
    db: AsyncSession = Depends(get_db),
) -> ChallengeGrant:
    policy = _policy_for(payload)
    if policy.outcome != "REQUIRE_APPROVAL":
        raise HTTPException(
            status_code=409,
            detail={"outcome": policy.outcome, "reasons": policy.reasons},
        )
    await _require_call_session(db, payload.call_id)
    try:
        grant = await challenge_manager.issue(
            db,
            customer_id=payload.customer_id,
            call_id=payload.call_id,
            action=policy.action,
            amount=payload.amount,
            beneficiary_ref=payload.beneficiary_ref,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.commit()
    return grant


@router.post(
    "/simulate",
    response_model=SimulationResponse,
    description=(
        "Development-only simulated action. Supplied trust decisions and customer "
        "IDs are not authenticated; no real financial operation is performed."
    ),
)
async def simulate_action(
    payload: SimulateActionRequest,
    db: AsyncSession = Depends(get_db),
) -> SimulationResponse:
    _validate_demo_identity(payload)
    await _require_call_session(db, payload.call_id)
    result = await transaction_guard.authorize(
        db=db,
        customer_id=payload.customer_id,
        call_id=payload.call_id,
        trust_decision=payload.trust_decision,
        intent=payload.intent,
        amount=payload.amount,
        beneficiary_ref=payload.beneficiary_ref,
        challenge_id=payload.challenge_id,
        challenge_token=payload.challenge_token,
    )
    if not result.allowed:
        await db.rollback()
        return SimulationResponse(guard=result, simulated_action_recorded=False)

    action_id = secrets.token_urlsafe(24)
    db.add(
        DemoTransactionRecord(
            action_id=action_id,
            customer_id=payload.customer_id,
            call_id=payload.call_id,
            action=result.action,
            amount_text=format(payload.amount, "f") if payload.amount is not None else None,
            beneficiary_ref=payload.beneficiary_ref,
            status="simulated",
        )
    )
    await db.commit()
    return SimulationResponse(
        guard=result,
        simulated_action_recorded=True,
        action_id=action_id,
    )

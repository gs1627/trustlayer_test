"""Final pre-execution transaction guard for P1's transaction API.

This module authorises or rejects; it deliberately does not execute or connect
to a real banking/payment system.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.security.challenge_manager import ChallengeManager
from app.security.policy_engine import PolicyDecision, PolicyEngine


class GuardResult(BaseModel):
    allowed: bool
    outcome: Literal["ALLOW", "REQUIRE_APPROVAL", "REQUIRE_VERIFICATION", "BLOCK"]
    action: str
    reasons: list[str] = Field(default_factory=list)
    challenge_consumed: bool = False


class TransactionGuard:
    def __init__(
        self,
        policy_engine: PolicyEngine | None = None,
        challenge_manager: ChallengeManager | None = None,
    ):
        self.policy_engine = policy_engine or PolicyEngine()
        self.challenge_manager = challenge_manager or ChallengeManager()

    async def authorize(
        self,
        *,
        db: AsyncSession,
        customer_id: str,
        call_id: str,
        trust_decision: Any,
        intent: Any,
        amount: Decimal | float | int | str | None = None,
        beneficiary_ref: str | None = None,
        challenge_id: str | None = None,
        challenge_token: str | None = None,
    ) -> GuardResult:
        """Check policy and atomically mark any matching challenge as consumed.

        P1's transaction endpoint should execute the simulated operation in the
        same DB transaction and commit only after the operation record is saved.
        Do not commit inside this guard; transaction + one-time challenge should
        share the caller's SQLAlchemy transaction.
        """
        policy: PolicyDecision = self.policy_engine.evaluate(
            trust_decision=trust_decision,
            intent=intent,
            amount=float(amount) if amount is not None else None,
            beneficiary_ref=beneficiary_ref,
        )

        if policy.outcome == "ALLOW":
            return GuardResult(
                allowed=True, outcome="ALLOW", action=policy.action,
                reasons=policy.reasons,
            )
        if policy.outcome != "REQUIRE_APPROVAL":
            return GuardResult(
                allowed=False, outcome=policy.outcome, action=policy.action,
                reasons=policy.reasons,
            )

        if not challenge_id or not challenge_token:
            return GuardResult(
                allowed=False, outcome="REQUIRE_APPROVAL", action=policy.action,
                reasons=policy.reasons + ["A valid independent approval challenge is required"],
            )

        consumed = await self.challenge_manager.consume(
            db,
            challenge_id=challenge_id,
            challenge_token=challenge_token,
            customer_id=customer_id,
            call_id=call_id,
            action=policy.action,
            amount=amount,
            beneficiary_ref=beneficiary_ref,
        )
        if not consumed:
            return GuardResult(
                allowed=False, outcome="REQUIRE_APPROVAL", action=policy.action,
                reasons=policy.reasons + ["Challenge is invalid, expired, already used, or bound to different transaction details"],
            )

        return GuardResult(
            allowed=True, outcome="REQUIRE_APPROVAL", action=policy.action,
            reasons=policy.reasons + ["Independent approval challenge validated"],
            challenge_consumed=True,
        )

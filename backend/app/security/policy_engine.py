"""Rules that decide whether an operation is allowed or needs step-up approval.

This policy module does not execute transactions. P1's transaction API must call
TransactionGuard before invoking any transaction adapter.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


PolicyOutcome = Literal["ALLOW", "REQUIRE_APPROVAL", "REQUIRE_VERIFICATION", "BLOCK"]


class PolicyDecision(BaseModel):
    outcome: PolicyOutcome
    action: str
    approval_required: bool = False
    reasons: list[str] = Field(default_factory=list)


class PolicyEngine:
    """Fail-closed policy rules for the hackathon's simulated transaction API."""

    SENSITIVE_ACTIONS = {
        "FINANCIAL_TRANSFER",
        "BENEFICIARY_CHANGE",
        "CREDENTIAL_RESET",
        "MOBILE_NUMBER_CHANGE",
        "ACCOUNT_INFORMATION_REQUEST",
    }

    @staticmethod
    def _value(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def evaluate(
        self,
        *,
        trust_decision: Any,
        intent: Any,
        amount: float | None = None,
        beneficiary_ref: str | None = None,
    ) -> PolicyDecision:
        action = str(self._value(intent, "intent", intent if isinstance(intent, str) else "UNKNOWN")).upper()
        trust = str(self._value(trust_decision, "decision", "INSUFFICIENT")).upper()
        reasons: list[str] = []

        # Never disclose a one-time secret, regardless of the voice result.
        if action == "OTP_REQUEST":
            return PolicyDecision(
                outcome="BLOCK", action=action,
                reasons=["Never disclose or read an OTP/one-time secret to a caller"],
            )

        # Voice identity is not sufficient to approve a sensitive operation.
        if trust == "HOLD":
            return PolicyDecision(outcome="BLOCK", action=action, reasons=["Trust Engine placed this call on HOLD"])
        if trust == "INSUFFICIENT":
            return PolicyDecision(outcome="REQUIRE_VERIFICATION", action=action, reasons=["Required evidence is missing, pending, or inconclusive"])
        if trust != "NORMAL":
            return PolicyDecision(outcome="REQUIRE_VERIFICATION", action=action, reasons=["Call must pass additional verification before an operation can proceed"])

        if action == "UNKNOWN":
            return PolicyDecision(outcome="REQUIRE_VERIFICATION", action=action, reasons=["Caller intent is unknown"])

        if action == "FINANCIAL_TRANSFER":
            if amount is None or amount <= 0:
                return PolicyDecision(outcome="BLOCK", action=action, reasons=["A positive transfer amount is required before approval can be requested"])
            if not beneficiary_ref or not beneficiary_ref.strip():
                return PolicyDecision(outcome="BLOCK", action=action, reasons=["A verified beneficiary reference is required before approval can be requested"])

        if action == "BENEFICIARY_CHANGE" and not beneficiary_ref:
            return PolicyDecision(outcome="BLOCK", action=action, reasons=["The exact destination beneficiary must be identified before approval"])

        if action in self.SENSITIVE_ACTIONS:
            reasons.append("Independent transaction approval is mandatory for this action")
            if action in {"CREDENTIAL_RESET", "MOBILE_NUMBER_CHANGE"} and not beneficiary_ref:
                reasons.append("Provide a stable target reference or payload fingerprint so approval is bound to the exact change")
                return PolicyDecision(outcome="BLOCK", action=action, reasons=reasons)
            return PolicyDecision(
                outcome="REQUIRE_APPROVAL", action=action,
                approval_required=True, reasons=reasons,
            )

        if action in {"BALANCE_ENQUIRY", "GENERAL_ENQUIRY"}:
            return PolicyDecision(outcome="ALLOW", action=action, reasons=["Low-risk enquiry and voice checks passed"])

        # Unknown future actions should never silently pass.
        return PolicyDecision(outcome="REQUIRE_VERIFICATION", action=action, reasons=["No explicit policy exists for this action"])

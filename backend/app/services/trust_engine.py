from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.contracts import EvidenceItem


DecisionName = Literal["NORMAL", "VERIFY", "HOLD", "INSUFFICIENT"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class TrustDecision(BaseModel):
    decision: DecisionName
    risk_level: RiskLevel
    reasons: list[str] = Field(default_factory=list)
    transaction_approval_required: bool = False
    intent: str = "UNKNOWN"


SYNTHETIC_VERDICTS = {
    "fake", "synthetic", "ai_generated", "deepfake", "manipulated", "spoofed"
}
GENUINE_VERDICTS = {"real", "genuine", "authentic", "not_fake", "bonafide"}
SPEAKER_MATCH_VERDICTS = {"match", "matched", "verified", "same_speaker", "speaker_match"}
SPEAKER_MISMATCH_VERDICTS = {"no_match", "mismatch", "not_match", "different_speaker", "unverified"}

SENSITIVE_INTENTS = {
    "FINANCIAL_TRANSFER",
    "BENEFICIARY_CHANGE",
    "CREDENTIAL_RESET",
    "MOBILE_NUMBER_CHANGE",
    "OTP_REQUEST",
    "ACCOUNT_INFORMATION_REQUEST",
}
HOLD_INTENTS = {"OTP_REQUEST", "CREDENTIAL_RESET"}
RECOGNIZED_INTENTS = SENSITIVE_INTENTS | {"BALANCE_ENQUIRY", "GENERAL_ENQUIRY"}


def _latest(items: Iterable[EvidenceItem], check_type: str) -> EvidenceItem | None:
    matches = [item for item in items if item.check_type == check_type]
    if not matches:
        return None
    def timestamp(item: EvidenceItem) -> float:
        observed = item.observed_at
        if observed is None:
            return 0.0
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        return observed.timestamp()

    # Use list order as a tie-breaker so a later-arriving event supersedes an
    # earlier one even when provider timestamps have only coarse precision.
    return max(enumerate(matches), key=lambda pair: (timestamp(pair[1]), pair[0]))[1]


def _token(value: str | None) -> str:
    return (value or "").strip().lower().replace("-", "_").replace(" ", "_")


class TrustEngine:
    """Deterministic policy over provider evidence. It never averages provider scores."""

    def evaluate(self, evidence: Iterable[EvidenceItem]) -> TrustDecision:
        items = list(evidence)
        deepfake = _latest(items, "deepfake")
        speaker = _latest(items, "speaker_verification")
        transcript = _latest(items, "transcription")
        context = _latest(items, "context")
        reasons: list[str] = []

        deepfake_verdict = _token(deepfake.verdict) if deepfake else ""
        speaker_verdict = _token(speaker.verdict) if speaker else ""

        # A strong explicit synthetic verdict can trigger a protective hold even
        # while the provider marks the event as provisional.
        if deepfake and deepfake_verdict in SYNTHETIC_VERDICTS:
            return TrustDecision(
                decision="HOLD",
                risk_level="CRITICAL",
                reasons=["Aletheia reported a synthetic or manipulated voice"],
                intent=self._intent(context),
            )

        if speaker and speaker.status == "completed" and speaker.is_final and speaker_verdict in SPEAKER_MISMATCH_VERDICTS:
            return TrustDecision(
                decision="HOLD",
                risk_level="HIGH",
                reasons=["Eidos did not match the enrolled speaker"],
                intent=self._intent(context),
            )

        # Missing, failed, provisional or unknown evidence never counts as a pass.
        for name, item in (
            ("Aletheia deepfake result", deepfake),
            ("Eidos speaker-verification result", speaker),
            ("final Sarvam transcript", transcript),
            ("final Gemini context analysis", context),
        ):
            if item is None:
                reasons.append(f"Missing {name}")
            elif item.status != "completed" or not item.is_final:
                reasons.append(f"{name} is not final and completed")

        if reasons:
            return TrustDecision(
                decision="INSUFFICIENT",
                risk_level="HIGH",
                reasons=reasons,
                intent=self._intent(context),
            )

        if deepfake_verdict not in GENUINE_VERDICTS:
            return TrustDecision(
                decision="VERIFY",
                risk_level="HIGH",
                reasons=["Aletheia verdict is not an explicitly recognized genuine result"],
                intent=self._intent(context),
            )

        if speaker_verdict not in SPEAKER_MATCH_VERDICTS:
            return TrustDecision(
                decision="VERIFY",
                risk_level="HIGH",
                reasons=["Eidos verdict is not an explicitly recognized speaker match"],
                intent=self._intent(context),
            )

        intent = self._intent(context)
        context_details = context.details if context else {}
        risk_indicators = context_details.get("risk_indicators", [])
        if not isinstance(risk_indicators, list):
            risk_indicators = []
        credential_request = bool(context_details.get("credential_request"))
        if intent not in RECOGNIZED_INTENTS:
            return TrustDecision(
                decision="VERIFY",
                risk_level="HIGH",
                reasons=["Caller intent is unknown or not recognized by policy"],
                intent=intent,
            )

        sensitive = (
            intent in SENSITIVE_INTENTS
            or credential_request
            or bool(context_details.get("beneficiary_change_requested"))
            or bool(context_details.get("requires_independent_approval"))
        )

        if intent in HOLD_INTENTS or credential_request:
            return TrustDecision(
                decision="HOLD",
                risk_level="CRITICAL",
                reasons=["The conversation includes an OTP or credential-related request"],
                transaction_approval_required=True,
                intent=intent,
            )

        if sensitive:
            return TrustDecision(
                decision="VERIFY",
                risk_level="HIGH",
                reasons=[
                    f"Sensitive intent detected: {intent}",
                    "Voice verification does not authorize a transaction; independent approval is required",
                ],
                transaction_approval_required=True,
                intent=intent,
            )

        if risk_indicators:
            return TrustDecision(
                decision="VERIFY",
                risk_level="MEDIUM",
                reasons=["Conversation risk indicators require human or step-up review"],
                transaction_approval_required=False,
                intent=intent,
            )

        return TrustDecision(
            decision="NORMAL",
            risk_level="LOW",
            reasons=["Final voice, speaker, transcript and context evidence passed policy checks"],
            transaction_approval_required=False,
            intent=intent,
        )

    @staticmethod
    def _intent(context: EvidenceItem | None) -> str:
        if not context:
            return "UNKNOWN"
        intent = context.details.get("intent") or context.verdict or "UNKNOWN"
        return str(intent).upper()

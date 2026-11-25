"""Synthetic, non-customer test scenarios for the Trust Engine."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.schemas.contracts import EvidenceItem


def _item(
    call_id: str,
    check_type: str,
    provider: str,
    verdict: str | None,
    details: dict[str, Any] | None = None,
    *,
    status: str = "completed",
    is_final: bool = True,
) -> EvidenceItem:
    return EvidenceItem(
        call_id=call_id,
        provider=provider,
        model="synthetic-test-fixture",
        check_type=check_type,
        status=status,
        verdict=verdict,
        is_final=is_final,
        observed_at=datetime.now(timezone.utc),
        details=details or {},
    )


def build_scenario(name: str, *, deepfake: str = "genuine", speaker: str = "match",
                   intent: str = "GENERAL_ENQUIRY", transcript: str = "Please tell me the branch timings.",
                   evidence_status: str = "completed", final: bool = True) -> dict[str, Any]:
    call_id = f"scenario-{name}"
    items = [
        _item(call_id, "deepfake", "detectifai", deepfake),
        _item(call_id, "speaker_verification", "detectifai", speaker),
        _item(call_id, "transcription", "sarvam", "transcribed", {"text": transcript, "language": "en-IN"}),
        _item(call_id, "context", "gemini", intent, {"intent": intent, "risk_indicators": []}),
    ]
    if evidence_status != "completed" or not final:
        items[0] = _item(
            call_id, "deepfake", "detectifai", deepfake,
            status=evidence_status, is_final=final,
        )
    return {
        "name": name,
        "call_id": call_id,
        "evidence": items,
    }


SCENARIOS: list[dict[str, Any]] = [
    build_scenario("genuine_enrolled_low_risk"),
    build_scenario("synthetic_voice", deepfake="synthetic"),
    build_scenario("wrong_speaker", speaker="no_match"),
    build_scenario("pending_deepfake", evidence_status="pending", final=False),
    build_scenario("sensitive_transfer", intent="FINANCIAL_TRANSFER", transcript="Transfer 500 rupees to my saved beneficiary."),
    build_scenario("unknown_intent", intent="UNKNOWN", transcript="I am not sure what I need."),
]

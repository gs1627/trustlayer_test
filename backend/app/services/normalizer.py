from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import ValidationError

from app.schemas.contracts import EvidenceItem


class EvidenceNormalizationError(ValueError):
    pass


def normalize_evidence(
    value: EvidenceItem | Mapping[str, Any],
    *,
    call_id: str,
) -> EvidenceItem:
    """Validate one item against P1's shared provider-neutral contract.

    This intentionally does not guess DetectifAI raw response field names. P1 should
    translate its provider response into EvidenceItem before passing it to P3.
    """
    try:
        item = value if isinstance(value, EvidenceItem) else EvidenceItem.model_validate(value)
    except ValidationError as exc:
        raise EvidenceNormalizationError("Evidence does not match contracts.EvidenceItem") from exc

    if item.call_id != call_id:
        raise EvidenceNormalizationError(
            f"Evidence call_id mismatch: expected {call_id!r}, received {item.call_id!r}"
        )

    if item.check_type == "transcription" and item.provider.lower() != "sarvam":
        raise EvidenceNormalizationError("transcription evidence must come from Sarvam")
    if item.check_type == "context" and item.provider.lower() != "gemini":
        raise EvidenceNormalizationError("context evidence must come from Gemini")
    if item.check_type in {"deepfake", "speaker_verification"} and item.provider.lower() not in {
        "detectifai", "detectif", "aletheia", "eidos"
    }:
        raise EvidenceNormalizationError("voice evidence must identify its DetectifAI provider")

    return item


def normalize_evidence_list(
    values: Iterable[EvidenceItem | Mapping[str, Any]],
    *,
    call_id: str,
) -> list[EvidenceItem]:
    """Normalize all evidence for one call, preserving event history/order."""
    normalized: list[EvidenceItem] = []
    for value in values:
        normalized.append(normalize_evidence(value, call_id=call_id))
    return normalized


def make_detectif_evidence(
    *,
    call_id: str,
    check_type: str,
    status: str,
    verdict: str | None,
    model: str,
    is_final: bool,
    provider_operation_id: str | None = None,
    raw_score: float | None = None,
    score_type: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> EvidenceItem:
    """Build the shared contract after P1 has interpreted a DetectifAI result.

    P1 must supply the verdict/status based on the actual DetectifAI response and
    its documented semantics; this helper does not infer them from raw payloads.
    """
    return EvidenceItem(
        call_id=call_id,
        provider="detectifai",
        model=model,
        check_type=check_type,  # validated by EvidenceItem's Literal
        status=status,
        verdict=verdict,
        raw_score=raw_score,
        score_type=score_type,
        is_final=is_final,
        provider_operation_id=provider_operation_id,
        details=dict(details or {}),
    )

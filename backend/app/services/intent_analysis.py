"""Run Gemini intent analysis only after a final Sarvam transcript exists."""
from __future__ import annotations

from datetime import datetime, timezone

from app.services.gemini_service import GeminiService
from app.schemas.contracts import EvidenceItem


class IntentAnalysisService:
    def __init__(self, service: GeminiService | None = None):
        self.service = service or GeminiService()

    async def analyze(self, transcript_evidence: EvidenceItem) -> EvidenceItem:
        if transcript_evidence.check_type != "transcription":
            raise ValueError("Intent analysis requires transcription evidence")
        if transcript_evidence.status != "completed":
            return self._failed_or_pending(transcript_evidence, "Transcript is not completed")
        if not transcript_evidence.is_final:
            return self._failed_or_pending(transcript_evidence, "Gemini is not run on partial transcripts", pending=True)

        text = str(transcript_evidence.details.get("text", "")).strip()
        if not text:
            return self._failed_or_pending(transcript_evidence, "Final transcript is empty")

        return await self.service.analyze_transcript(
            text,
            call_id=transcript_evidence.call_id,
        )

    def _failed_or_pending(
        self, transcript: EvidenceItem, reason: str, pending: bool = False
    ) -> EvidenceItem:
        return EvidenceItem(
            call_id=transcript.call_id,
            provider="gemini",
            model=self.service.settings.gemini_model,
            check_type="context",
            status="pending" if pending else "inconclusive",
            is_final=not pending,
            observed_at=datetime.now(timezone.utc),
            details={"reason": reason},
        )

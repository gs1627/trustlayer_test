from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Iterable, Mapping
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.contracts import EvidenceItem
from app.services.gemini_service import GeminiService
from app.services.normalizer import normalize_evidence_list
from app.services.sarvam_service import SarvamService
from app.services.trust_engine import TrustDecision, TrustEngine


class PipelineResult(BaseModel):
    call_id: str
    transcript: str | None = None
    language: str | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    decision: TrustDecision


class IntelligencePipeline:
    """Orchestrates P3 services with the P1 EvidenceItem contract."""

    def __init__(
        self,
        *,
        sarvam: SarvamService | None = None,
        gemini: GeminiService | None = None,
        trust_engine: TrustEngine | None = None,
    ) -> None:
        self.sarvam = sarvam or SarvamService()
        self.gemini = gemini or GeminiService()
        self.trust_engine = trust_engine or TrustEngine()

    async def analyze_clip(
        self,
        audio: bytes,
        *,
        call_id: str,
        voice_evidence: Iterable[EvidenceItem | Mapping[str, Any]],
        filename: str = "recording.wav",
        content_type: str = "audio/wav",
    ) -> PipelineResult:
        """End-to-end test path for short clips (Sarvam REST supports <=30 seconds)."""
        transcript_item = await self.sarvam.transcribe_clip(
            audio,
            call_id=call_id,
            filename=filename,
            content_type=content_type,
            language_code="unknown",
        )
        text = str(transcript_item.details.get("text") or "").strip()
        context_item = (
            await self.gemini.analyze_transcript(text, call_id=call_id)
            if transcript_item.status == "completed" and transcript_item.is_final and text
            else EvidenceItem(
                call_id=call_id,
                provider="gemini",
                model="not_run",
                check_type="context",
                status="inconclusive",
                verdict=None,
                is_final=True,
                details={"error": "context_analysis_skipped_no_final_transcript"},
            )
        )
        evidence = normalize_evidence_list(
            [*voice_evidence, transcript_item, context_item], call_id=call_id
        )
        decision = self.trust_engine.evaluate(evidence)
        return PipelineResult(
            call_id=call_id,
            transcript=text or None,
            language=transcript_item.details.get("language"),
            evidence=evidence,
            decision=decision,
        )

    async def analyze_live_stream(
        self,
        audio_chunks: AsyncIterable[bytes],
        *,
        call_id: str,
        voice_evidence: Iterable[EvidenceItem | Mapping[str, Any]],
        sample_rate: int = 16000,
    ) -> AsyncIterator[PipelineResult]:
        """Yield provisional and final decisions during a Sarvam realtime stream.

        Gemini is called only when Sarvam emits transcript.final, never for partials.
        P1 must pass the same mono PCM16 audio chunks to this method and its
        DetectifAI relay (audio fan-out/tee), rather than asking the browser to
        connect directly to Sarvam.
        """
        base_evidence = list(voice_evidence)
        all_evidence: list[EvidenceItem | Mapping[str, Any]] = list(base_evidence)
        final_segments: list[str] = []
        latest_language: str | None = None

        async for transcript_item in self.sarvam.stream_transcribe(
            audio_chunks,
            call_id=call_id,
            sample_rate=sample_rate,
        ):
            all_evidence.append(transcript_item)
            if transcript_item.details.get("language"):
                latest_language = str(transcript_item.details["language"])

            current_text = str(transcript_item.details.get("text") or "").strip()
            if transcript_item.is_final and transcript_item.status == "completed" and current_text:
                final_segments.append(current_text)
                combined_text = " ".join(final_segments)
                context_item = await self.gemini.analyze_transcript(
                    combined_text, call_id=call_id
                )
                all_evidence.append(context_item)
            else:
                combined_text = " ".join(final_segments) or current_text or None

            evidence = normalize_evidence_list(all_evidence, call_id=call_id)
            yield PipelineResult(
                call_id=call_id,
                transcript=combined_text,
                language=latest_language,
                evidence=evidence,
                decision=self.trust_engine.evaluate(evidence),
            )

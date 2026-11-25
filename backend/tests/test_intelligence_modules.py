import pytest

from app.evaluation.benchmark import benchmark_trust_engine
from app.evaluation.test_scenarios import build_scenario
from app.schemas.contracts import EvidenceItem
from app.services.intent_analysis import IntentAnalysisService
from app.services.trust_engine import TrustEngine


def _transcript(*, status="completed", is_final=True, text="Check my balance"):
    return EvidenceItem(
        call_id="call-test",
        provider="sarvam",
        model="test-model",
        check_type="transcription",
        status=status,
        is_final=is_final,
        details={"text": text},
    )


def test_trust_engine_benchmark_runs_synthetic_scenarios():
    result = benchmark_trust_engine()

    assert result["scenario_count"] == 6
    assert sum(result["decision_counts"].values()) == 6
    unknown_intent = next(
        scenario for scenario in result["results"] if scenario["scenario"] == "unknown_intent"
    )
    assert unknown_intent["decision"] == "VERIFY"
    assert result["note"].startswith("Synthetic deterministic scenarios")


def test_trust_engine_benchmark_rejects_empty_scenarios():
    with pytest.raises(ValueError, match="At least one scenario"):
        benchmark_trust_engine([])


def test_unrecognized_intent_fails_closed():
    scenario = build_scenario("future_action", intent="UNRECOGNIZED_ACTION")

    decision = TrustEngine().evaluate(scenario["evidence"])

    assert decision.decision == "VERIFY"
    assert decision.risk_level == "HIGH"


@pytest.mark.asyncio
async def test_intent_analysis_delegates_final_transcript_to_gemini_service():
    class GeminiStub:
        settings = type("SettingsStub", (), {"gemini_model": "test-gemini"})()

        def __init__(self):
            self.received = None

        async def analyze_transcript(self, transcript, *, call_id):
            self.received = (transcript, call_id)
            return EvidenceItem(
                call_id=call_id,
                provider="gemini",
                model="test-gemini",
                check_type="context",
                status="completed",
                verdict="BALANCE_ENQUIRY",
                is_final=True,
                details={"intent": "BALANCE_ENQUIRY"},
            )

    service = GeminiStub()
    result = await IntentAnalysisService(service=service).analyze(_transcript())

    assert service.received == ("Check my balance", "call-test")
    assert result.check_type == "context"
    assert result.verdict == "BALANCE_ENQUIRY"


@pytest.mark.asyncio
async def test_intent_analysis_does_not_send_partial_transcripts_to_gemini():
    class GeminiStub:
        settings = type("SettingsStub", (), {"gemini_model": "test-gemini"})()

        async def analyze_transcript(self, transcript, *, call_id):
            raise AssertionError("partial transcript must not be sent")

    result = await IntentAnalysisService(service=GeminiStub()).analyze(
        _transcript(is_final=False)
    )

    assert result.status == "pending"
    assert result.is_final is False

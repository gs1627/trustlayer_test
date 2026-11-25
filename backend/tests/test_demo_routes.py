import json
import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.auth import require_backend_access, require_demo_mode
from app.evaluation.test_scenarios import SCENARIOS
from app.main import app
from app.schemas.contracts import EvidenceItem
from app.services.intelligence_pipeline import IntelligencePipeline


@pytest.fixture
def demo_client(monkeypatch):
    monkeypatch.setitem(app.dependency_overrides, require_backend_access, lambda: None)
    monkeypatch.setitem(app.dependency_overrides, require_demo_mode, lambda: None)
    with TestClient(app) as client:
        yield client


def test_demo_mode_dependency_rejects_production(monkeypatch):
    monkeypatch.setattr(
        "app.core.auth.get_settings",
        lambda: type("SettingsStub", (), {"app_env": "production"})(),
    )

    with pytest.raises(HTTPException) as exc_info:
        require_demo_mode()

    assert exc_info.value.status_code == 403


def test_intelligence_route_runs_pipeline_with_validated_voice_evidence(
    demo_client, monkeypatch
):
    call_id = f"demo-{uuid.uuid4()}"
    evidence = [
        item.model_copy(update={"call_id": call_id})
        for item in SCENARIOS[0]["evidence"]
        if item.check_type in {"deepfake", "speaker_verification"}
    ]

    class SarvamStub:
        async def transcribe_clip(self, audio, **kwargs):
            return EvidenceItem(
                call_id=kwargs["call_id"],
                provider="sarvam",
                model="test-sarvam",
                check_type="transcription",
                status="completed",
                verdict="transcribed",
                is_final=True,
                details={"text": "Check my balance", "language": "en-IN"},
            )

    class GeminiStub:
        async def analyze_transcript(self, transcript, *, call_id):
            return EvidenceItem(
                call_id=call_id,
                provider="gemini",
                model="test-gemini",
                check_type="context",
                status="completed",
                verdict="GENERAL_ENQUIRY",
                is_final=True,
                details={"intent": "GENERAL_ENQUIRY", "risk_indicators": []},
            )

    from app.api.routes import intelligence

    monkeypatch.setattr(
        intelligence,
        "pipeline",
        IntelligencePipeline(sarvam=SarvamStub(), gemini=GeminiStub()),
    )
    response = demo_client.post(
        "/api/v1/intelligence/analyze",
        data={
            "call_id": call_id,
            "voice_evidence_json": json.dumps(
                [item.model_dump(mode="json") for item in evidence]
            ),
        },
        files={"file": ("sample.wav", b"sample-audio", "audio/wav")},
    )

    assert response.status_code == 200
    assert response.json()["decision"]["decision"] == "NORMAL"
    assert response.json()["transcript"] == "Check my balance"


def test_demo_transaction_requires_a_call_session_and_uses_one_time_challenge(
    demo_client,
):
    call_id = f"demo-{uuid.uuid4()}"
    created = demo_client.post(
        "/api/v1/calls/sessions",
        json={"call_id": call_id, "speaker_id": "demo-speaker"},
    )
    assert created.status_code == 200

    request = {
        "customer_id": "demo-customer",
        "call_id": call_id,
        "trust_decision": {"decision": "NORMAL", "risk_level": "LOW"},
        "intent": "FINANCIAL_TRANSFER",
        "amount": "25.00",
        "beneficiary_ref": "demo-beneficiary",
    }
    challenge = demo_client.post("/api/v1/transactions/challenges", json=request)
    assert challenge.status_code == 200

    simulation_payload = {
        **request,
        "challenge_id": challenge.json()["challenge_id"],
        "challenge_token": challenge.json()["challenge_token"],
    }
    result = demo_client.post("/api/v1/transactions/simulate", json=simulation_payload)

    assert result.status_code == 200
    assert result.json()["guard"]["allowed"] is True
    assert result.json()["simulated_action_recorded"] is True
    assert "No real financial transaction" in result.json()["note"]

    replay = demo_client.post("/api/v1/transactions/simulate", json=simulation_payload)
    assert replay.status_code == 200
    assert replay.json()["guard"]["allowed"] is False
    assert replay.json()["simulated_action_recorded"] is False

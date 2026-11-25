import pytest

from app.services.evidence_mapper import (
    EvidenceMappingError,
    map_aletheia_rest_result,
    map_detectif_webhook_event,
    map_detectif_websocket_message,
    map_eidos_verify_rest_results,
    map_gemini_context,
    map_provider_evidence,
    map_sarvam_transcription,
    sanitize_evidence_details,
)


def test_aletheia_rest_mapping_preserves_raw_score_and_ids():
    payload = {
        "request_id": "req_df_001",
        "operation_id": "op_df_001",
        "object": "deepfake.detection",
        "result": {
            "verdict": "fake",
            "score": 0.874,
            "duration_seconds": 8.2,
            "api_key": "should-never-leak",
        },
    }
    item = map_aletheia_rest_result(payload, call_id="CALL_001")

    assert item.provider == "detectifai"
    assert item.model == "aletheia"
    assert item.check_type == "deepfake"
    assert item.status == "completed"
    assert item.verdict == "fake"
    assert item.raw_score == 0.874
    assert item.score_type == "synthetic_score"
    assert item.is_final is True
    assert item.is_early is None
    assert item.source_channel == "rest"
    assert item.provider_request_id == "req_df_001"
    assert item.provider_operation_id == "op_df_001"
    assert item.details["api_key"] == "[REDACTED]"
    assert item.details["duration_seconds"] == 8.2

    # Pending async operation stays non-final without fabricating verdict or score.
    pending_item = map_aletheia_rest_result(
        {"operation_id": "op_df_pending", "status": "processing"},
        call_id="CALL_001",
    )
    assert pending_item.status == "pending"
    assert pending_item.is_final is False
    assert pending_item.verdict is None
    assert pending_item.raw_score is None
    assert pending_item.score_type is None


def test_eidos_verify_rest_with_nested_deepfake_produces_both_evidence_items():
    payload = {
        "request_id": "req_ver_1",
        "operation_id": "op_ver_1",
        "object": "speaker.verification",
        "result": {
            "decision": "match",
            "similarity": -0.15,
            "threshold": -0.2,
            "speaker_id": "CUST_42",
            "deepfake": {
                "verdict": "real",
                "score": 0.04,
            },
        },
    }
    items = map_eidos_verify_rest_results(payload, call_id="CALL_VER_1")
    assert len(items) == 2

    eidos_item, aletheia_item = items
    assert eidos_item.check_type == "speaker_verification"
    assert eidos_item.model == "eidos"
    assert eidos_item.verdict == "match"
    # Raw negative similarity preserved without probability conversion.
    assert eidos_item.raw_score == -0.15
    assert eidos_item.score_type == "cosine_similarity"
    assert eidos_item.speaker_id == "CUST_42"
    assert eidos_item.is_final is True

    assert aletheia_item.check_type == "deepfake"
    assert aletheia_item.model == "aletheia"
    assert aletheia_item.verdict == "real"
    assert aletheia_item.raw_score == 0.04
    assert aletheia_item.score_type == "synthetic_score"
    assert aletheia_item.speaker_id == "CUST_42"


def test_websocket_messages_preserve_early_and_final_independently():
    # Lifecycle message maps cleanly to no evidence.
    assert map_detectif_websocket_message({"type": "ready", "stream_id": "str_1"}, call_id="CALL_WS_1") == []

    # early=False with final=False must stay non-final!
    live_non_final = map_detectif_websocket_message(
        {
            "type": "deepfake",
            "stream_id": "str_1",
            "sequence": 2,
            "early": False,
            "final": False,
            "verdict": "real",
            "score": 0.11,
            "speech_seconds": 4.5,
        },
        call_id="CALL_WS_1",
    )
    assert len(live_non_final) == 1
    assert live_non_final[0].is_early is False
    assert live_non_final[0].is_final is False
    assert live_non_final[0].status == "pending"
    assert live_non_final[0].sequence == 2

    # early=False with omitted final must ALSO stay non-final.
    omitted_final = map_detectif_websocket_message(
        {"type": "deepfake", "stream_id": "str_1", "sequence": 3, "early": False, "verdict": "real"},
        call_id="CALL_WS_1",
    )
    assert omitted_final[0].is_early is False
    assert omitted_final[0].is_final is False

    # Verification supporting both early=True and final=True simultaneously.
    ver_early_final = map_detectif_websocket_message(
        {
            "type": "verification",
            "stream_id": "str_1",
            "operation_id": "op_ws_v1",
            "early": True,
            "final": True,
            "speaker_id": "SPK_9",
            "decision": "no_match",
            "similarity": 0.18,
        },
        call_id="CALL_WS_1",
    )
    assert len(ver_early_final) == 1
    assert ver_early_final[0].is_early is True
    assert ver_early_final[0].is_final is True
    assert ver_early_final[0].status == "completed"
    assert ver_early_final[0].verdict == "no_match"

    # Completed WS aggregate extracts both deepfake and verify results cleanly.
    completed_items = map_detectif_websocket_message(
        {
            "type": "completed",
            "stream_id": "str_1",
            "seconds": 25.0,
            "speech_seconds": 18.2,
            "credits": 2,
            "ended_by": "client_stop",
            "results": {
                "deepfake": {"verdict": "real", "score": 0.05},
                "verify": {"status": "match", "similarity_score": 91.5},
            },
        },
        call_id="CALL_WS_1",
        speaker_id="SPK_9",
    )
    assert len(completed_items) == 2
    assert all(item.is_final is True and item.status == "completed" for item in completed_items)
    assert {item.check_type for item in completed_items} == {"deepfake", "speaker_verification"}


def test_webhook_events_mapping_and_provisional_semantics():
    # stream.deepfake.updated is ALWAYS provisional even when early=False.
    upd_payload = {
        "id": "evt_upd_1",
        "type": "stream.deepfake.updated",
        "created_at": "2026-11-11T09:31:24.512Z",
        "data": {
            "stream_id": "str_wh_1",
            "reference": "CALL_WH_MAP",
            "sequence": 4,
            "early": False,
            "verdict": "real",
            "score": 0.08,
            "seconds": 10.0,
            "speech_seconds": 7.5,
        },
    }
    upd_items_1 = map_detectif_webhook_event(upd_payload, delivery_id="msg_del_1")
    upd_items_2 = map_detectif_webhook_event(upd_payload, delivery_id="msg_del_1")
    assert len(upd_items_1) == 1
    assert upd_items_1[0].is_early is False
    assert upd_items_1[0].is_final is False
    assert upd_items_1[0].status == "pending"
    assert upd_items_1[0].source_event_key == upd_items_2[0].source_event_key

    # deepfake.completed produces final deepfake record.
    df_completed = map_detectif_webhook_event(
        {
            "id": "evt_df_comp",
            "type": "deepfake.completed",
            "created_at": 1774600000,
            "data": {
                "reference": "CALL_WH_MAP",
                "operation_id": "op_df_final",
                "result": {"verdict": "fake", "score": 0.94, "duration_seconds": 12.0},
            },
        }
    )
    assert len(df_completed) == 1
    assert df_completed[0].is_final is True
    assert df_completed[0].status == "completed"
    assert df_completed[0].verdict == "fake"
    assert df_completed[0].observed_at is not None

    # stream.completed extracts combined results.
    stream_completed = map_detectif_webhook_event(
        {
            "id": "evt_str_comp",
            "type": "stream.completed",
            "created_at": 1774600010,
            "data": {
                "stream_id": "str_wh_1",
                "reference": "CALL_WH_MAP",
                "speaker_id": "SPK_WH",
                "results": {
                    "deepfake": {"verdict": "real", "synthetic_risk_score": 2.1},
                    "verify": {"status": "no_match", "similarity": 0.21},
                },
            },
        }
    )
    assert len(stream_completed) == 2
    assert all(item.is_final is True for item in stream_completed)

    # speaker.verification.completed webhook supported cleanly.
    ver_wh = map_detectif_webhook_event(
        {
            "id": "evt_ver_comp",
            "type": "speaker.verification.completed",
            "data": {
                "reference": "CALL_WH_MAP",
                "operation_id": "op_ver_wh_1",
                "speaker_id": "SPK_WH",
                "decision": "inconclusive",
                "status": "inconclusive",
            },
        }
    )
    assert len(ver_wh) == 1
    assert ver_wh[0].check_type == "speaker_verification"
    assert ver_wh[0].status == "inconclusive"
    assert ver_wh[0].is_final is True

    # Test & lifecycle webhook events return no evidence items.
    assert map_detectif_webhook_event({"id": "evt_t", "type": "webhook.test", "data": {}}) == []


def test_sarvam_and_gemini_mappings_without_inventing_missing_fields():
    sarvam_full = map_sarvam_transcription(
        {
            "model": "saaras:v4",
            "request_id": "req_srv_1",
            "transcript": "Please transfer funds urgently.",
            "language_code": "en-IN",
            "language_probability": 0.97,
            "timestamps": {"words": ["Please", "transfer"], "start_time_seconds": [0.1, 0.5]},
        },
        call_id="CALL_M3_1",
    )
    assert sarvam_full.provider == "sarvam"
    assert sarvam_full.check_type == "transcription"
    assert sarvam_full.raw_score == 0.97
    assert sarvam_full.score_type == "language_probability"
    assert sarvam_full.details["transcript"] == "Please transfer funds urgently."
    assert sarvam_full.details["language"] == "en-IN"
    assert "timestamps" in sarvam_full.details

    # Missing optional language_probability and timestamps must NOT be invented.
    sarvam_minimal = map_sarvam_transcription(
        {"model": "saarika:v2", "transcript": "Hello"},
        call_id="CALL_M3_1",
    )
    assert sarvam_minimal.raw_score is None
    assert sarvam_minimal.score_type is None
    assert "language" not in sarvam_minimal.details
    assert "language_probability" not in sarvam_minimal.details
    assert "timestamps" not in sarvam_minimal.details

    # Gemini structured result + inconclusive + failed handling.
    gem_ok = map_gemini_context(
        {
            "model": "gemini-2.5-flash",
            "risk_label": "social_engineering",
            "risk_score": 0.88,
            "cues": ["secrecy_demand", "urgency_pressure"],
            "reasoning_summary": "Caller instructed customer not to inform branch staff.",
            "model_metadata": {"prompt_version": "ctx-v1"},
            "usage_metadata": {"prompt_token_count": 210},
        },
        call_id="CALL_M3_1",
    )
    assert gem_ok.provider == "gemini"
    assert gem_ok.check_type == "context"
    assert gem_ok.status == "completed"
    assert gem_ok.verdict == "social_engineering"
    assert gem_ok.raw_score == 0.88
    assert gem_ok.score_type == "contextual_risk_score"
    assert gem_ok.details["usage_metadata"]["prompt_token_count"] == 210

    gem_inc = map_gemini_context(
        {"model": "gemini-2.5-flash", "status": "inconclusive", "reasoning_summary": "Audio too short"},
        call_id="CALL_M3_1",
    )
    assert gem_inc.status == "inconclusive"
    assert gem_inc.verdict is None
    assert gem_inc.raw_score is None
    assert "cues" not in gem_inc.details

    gem_fail = map_gemini_context(
        {"model": "gemini-2.5-flash", "error": {"code": "rate_limited", "message": "429"}},
        call_id="CALL_M3_1",
    )
    assert gem_fail.status == "failed"
    assert gem_fail.details["error"]["code"] == "rate_limited"


def test_invalid_provider_payloads_and_secret_sanitization():
    with pytest.raises(EvidenceMappingError):
        map_aletheia_rest_result({"unexpected": "garbage"}, call_id="CALL_ERR")

    with pytest.raises(EvidenceMappingError):
        map_aletheia_rest_result({"verdict": "real", "score": float("nan")}, call_id="CALL_ERR")

    with pytest.raises(EvidenceMappingError):
        map_eidos_verify_rest_results({"result": "not-a-dict"}, call_id="CALL_ERR")

    with pytest.raises(EvidenceMappingError):
        map_detectif_websocket_message({"type": "deepfake", "sequence": "not-int"}, call_id="CALL_ERR")

    with pytest.raises(EvidenceMappingError):
        map_detectif_webhook_event({"type": "stream.completed", "data": {"reference": "CALL_ERR", "results": {}}})

    with pytest.raises(EvidenceMappingError):
        map_sarvam_transcription({"transcript": "hi"}, call_id="CALL_ERR")  # missing explicit model

    with pytest.raises(EvidenceMappingError):
        map_sarvam_transcription(
            {"model": "saaras:v4", "transcript": "hi", "language_probability": 1.4},
            call_id="CALL_ERR",
        )

    with pytest.raises(EvidenceMappingError):
        map_gemini_context({"model": "gemini-2.5-flash", "cues": "not-a-list"}, call_id="CALL_ERR")

    with pytest.raises(EvidenceMappingError):
        map_provider_evidence(provider="unknown_provider", payload={}, call_id="CALL_ERR")

    sanitized = sanitize_evidence_details(
        {
            "authorization": "Bearer secret",
            "audio_base64": "AQIDBA==",
            "phone_number": "+919999999999",
            "token_count": 42,
            "nested": {"webhook_secret": "whsec_secret", "bytes_field": b"rawpcm"},
        }
    )
    assert sanitized["authorization"] == "[REDACTED]"
    assert sanitized["audio_base64"] == "[REDACTED]"
    assert sanitized["phone_number"] == "[REDACTED]"
    assert sanitized["token_count"] == 42
    assert sanitized["nested"]["webhook_secret"] == "[REDACTED]"
    assert sanitized["nested"]["bytes_field"] == "<redacted-bytes:6>"

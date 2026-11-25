from app.core.config import Settings


def test_provider_settings_have_safe_defaults():
    settings = Settings(_env_file=None)

    assert settings.gemini_api_key is None
    assert settings.gemini_model
    assert settings.gemini_max_output_tokens > 0
    assert settings.sarvam_api_key is None
    assert settings.sarvam_base_url.startswith("https://")
    assert settings.sarvam_model
    assert settings.sarvam_timeout_seconds > 0
    assert settings.sarvam_sample_rate in {8000, 16000}
    assert settings.sarvam_encoding


def test_provider_settings_accept_overrides():
    settings = Settings(
        _env_file=None,
        gemini_api_key="test-gemini-key",
        sarvam_api_key="test-sarvam-key",
        sarvam_sample_rate=8000,
    )

    assert settings.gemini_api_key == "test-gemini-key"
    assert settings.sarvam_api_key == "test-sarvam-key"
    assert settings.sarvam_sample_rate == 8000

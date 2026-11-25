from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import BACKEND_DIR, DEFAULT_ENV_FILE, Settings, normalize_database_url


def test_settings_defaults():
    settings = Settings()
    assert settings.app_name == "TRUSTLAYER Backend"
    assert settings.app_env == "development"
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.detectif_api_key is None
    assert settings.detectif_base_url == "https://platform.detectif.ai"
    assert settings.max_upload_mb == 25
    assert settings.max_upload_bytes == 25 * 1024 * 1024
    assert settings.cors_origin_list == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


def test_default_env_file_points_to_backend_directory():
    assert BACKEND_DIR.name == "backend"
    assert DEFAULT_ENV_FILE == BACKEND_DIR / ".env"


def test_settings_loads_env_file_regardless_of_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "APP_NAME=CWD Test Backend",
                "APP_ENV=test",
                "DETECTIF_API_KEY=dummy-placeholder-key",
                "CORS_ORIGINS=http://localhost:3000, https://example.test ",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setitem(Settings.model_config, "env_file", env_file)
    monkeypatch.chdir(BACKEND_DIR.parent)

    settings = Settings()
    assert settings.app_name == "CWD Test Backend"
    assert settings.app_env == "test"
    assert settings.detectif_api_key == "dummy-placeholder-key"
    assert settings.cors_origin_list == ["http://localhost:3000", "https://example.test"]


def test_environment_variables_override_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env_file = tmp_path / ".env"
    env_file.write_text("APP_NAME=FromEnvFile\nMAX_UPLOAD_MB=10\n", encoding="utf-8")
    monkeypatch.setitem(Settings.model_config, "env_file", env_file)
    monkeypatch.setenv("APP_NAME", "FromProcessEnv")
    monkeypatch.setenv("MAX_UPLOAD_MB", "50")

    settings = Settings()
    assert settings.app_name == "FromProcessEnv"
    assert settings.max_upload_bytes == 50 * 1024 * 1024


def test_normalize_postgresql_urls_for_asyncpg():
    assert (
        normalize_database_url("postgres://user:pass@localhost:5432/trustlayer")
        == "postgresql+asyncpg://user:pass@localhost:5432/trustlayer"
    )
    assert (
        normalize_database_url("postgresql://user:pass@db.example:5432/trustlayer?sslmode=require")
        == "postgresql+asyncpg://user:pass@db.example:5432/trustlayer?sslmode=require"
    )
    already_async = "postgresql+asyncpg://user:pass@localhost:5432/trustlayer"
    assert normalize_database_url(already_async) == already_async


def test_normalize_sqlite_urls_anchors_relative_paths(tmp_path: Path):
    expected_root = (BACKEND_DIR / "trustlayer.db").resolve().as_posix()
    assert normalize_database_url("sqlite+aiosqlite:///./trustlayer.db") == f"sqlite+aiosqlite:///{expected_root}"

    expected_sub = (BACKEND_DIR / "data" / "local.db").resolve().as_posix()
    assert normalize_database_url("sqlite:///data/local.db") == f"sqlite:///{expected_sub}"

    assert normalize_database_url("sqlite+aiosqlite:///:memory:") == "sqlite+aiosqlite:///:memory:"
    assert (
        normalize_database_url("sqlite+aiosqlite:///file::memory:?cache=shared")
        == "sqlite+aiosqlite:///file::memory:?cache=shared"
    )

    absolute_url = f"sqlite+aiosqlite:///{(tmp_path / 'abs.db').as_posix()}"
    assert normalize_database_url(absolute_url) == absolute_url


def test_empty_database_url_raises_validation_error():
    with pytest.raises(ValidationError):
        Settings(database_url="   ")

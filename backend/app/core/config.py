from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = BACKEND_DIR / ".env"


def normalize_database_url(url: str, *, base_dir: Path = BACKEND_DIR) -> str:
    """Normalize PostgreSQL URLs for asyncpg and anchor relative SQLite file paths."""
    cleaned = url.strip()
    if not cleaned:
        raise ValueError("DATABASE_URL cannot be empty")

    if cleaned.startswith("postgres://"):
        return "postgresql+asyncpg://" + cleaned[len("postgres://"):]
    if cleaned.startswith("postgresql://"):
        return "postgresql+asyncpg://" + cleaned[len("postgresql://"):]

    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if cleaned.startswith(prefix):
            raw_path = cleaned[len(prefix):]
            path_part, sep, query_part = raw_path.partition("?")
            if (
                not path_part
                or path_part == ":memory:"
                or path_part.startswith("file:")
                or path_part.startswith("/")
                or path_part.startswith("\\")
                or (len(path_part) >= 2 and path_part[1] == ":")
                or Path(path_part).is_absolute()
            ):
                return cleaned
            resolved = (base_dir / path_part).resolve().as_posix()
            return f"{prefix}{resolved}{sep}{query_part}"

    return cleaned


class Settings(BaseSettings):
    app_name: str = "TRUSTLAYER Backend"
    app_env: Literal["development", "test", "production"] = "development"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"

    database_url: str = "sqlite+aiosqlite:///./trustlayer.db"

    detectif_api_key: str | None = None
    detectif_base_url: str = "https://platform.detectif.ai"
    detectif_connect_timeout_seconds: float = Field(default=10.0, gt=0.0)
    detectif_timeout_seconds: float = Field(default=300.0, gt=0.0)
    detectif_max_retries: int = Field(default=2, ge=0, le=5)
    detectif_retry_backoff_seconds: float = Field(default=0.5, ge=0.0, le=30.0)
    detectif_ws_max_connections_per_call: int = Field(default=2, ge=1, le=20)

    detectif_webhook_secret: str | None = None
    detectif_webhook_secret_previous: str | None = None
    webhook_tolerance_seconds: int = Field(default=300, ge=30, le=3600)
    webhook_max_attempts: int = Field(default=5, ge=1, le=20)
    webhook_retry_base_seconds: int = Field(default=30, ge=1, le=3600)

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_max_output_tokens: int = 1024

    sarvam_api_key: str | None = None
    sarvam_base_url: str = "https://api.sarvam.ai"
    sarvam_model: str = "saaras:v2.5"
    sarvam_timeout_seconds: float = 60.0
    sarvam_sample_rate: int = 16000
    sarvam_encoding: str = "audio/pcm"

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_upload_mb: int = 25
    backend_access_token: str | None = None

    jwt_secret_key: str | None = None
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "trustlayer-backend"
    jwt_audience: str = "trustlayer-api"
    jwt_access_token_ttl_seconds: int = Field(default=3600, ge=60, le=86400)

    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    rate_limit_auth_requests: int = Field(default=30, ge=1)
    rate_limit_call_create_requests: int = Field(default=30, ge=1)
    rate_limit_evidence_requests: int = Field(default=120, ge=1)
    rate_limit_assessment_requests: int = Field(default=60, ge=1)
    rate_limit_webhook_requests: int = Field(default=300, ge=1)
    rate_limit_ws_connect_requests: int = Field(default=20, ge=1)
    rate_limit_ws_messages_per_window: int = Field(default=2400, ge=1)

    tx_policy_min_allow_trust_score: float = Field(default=0.75, ge=0.0, le=1.0)
    tx_policy_block_trust_score: float = Field(default=0.35, ge=0.0, le=1.0)
    tx_policy_high_value_amount: Decimal = Field(default=Decimal("50000.00"), gt=Decimal("0"))
    tx_policy_require_final_deepfake: bool = True
    tx_policy_require_final_verification_when_configured: bool = True

    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("DATABASE_URL must be a string")
        return normalize_database_url(value)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

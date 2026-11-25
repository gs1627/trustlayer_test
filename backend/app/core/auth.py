from __future__ import annotations

import base64
from collections.abc import Iterable
from dataclasses import dataclass
import hashlib
import hmac
import json
import time
from typing import Any, Literal

from fastapi import Depends, Header, HTTPException, WebSocket

from app.core.config import Settings, get_settings
from app.core.errors import AppAPIError

AuthRole = Literal["admin", "service", "operator", "user", "anonymous_dev"]
_ALLOWED_JWT_ROLES = frozenset({"admin", "service", "operator", "user"})


class JWTValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class AuthPrincipal:
    subject: str
    role: AuthRole
    auth_type: Literal["jwt", "shared_token", "dev_open"]
    scopes: frozenset[str] = frozenset()

    @property
    def is_privileged(self) -> bool:
        return self.role in {"admin", "service", "operator", "anonymous_dev"}


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def create_access_token(
    *,
    subject: str,
    role: Literal["admin", "service", "operator", "user"] = "user",
    scopes: Iterable[str] = (),
    expires_in_seconds: int | None = None,
    settings: Settings | None = None,
) -> tuple[str, int]:
    """Create a signed HS256 JWT access token."""
    cfg = settings or get_settings()
    if not cfg.jwt_secret_key:
        raise AppAPIError(
            status_code=503,
            code="jwt_not_configured",
            message="JWT_SECRET_KEY is not configured",
        )
    if role not in _ALLOWED_JWT_ROLES:
        raise ValueError(f"Unsupported role '{role}'")

    ttl = expires_in_seconds if expires_in_seconds is not None else cfg.jwt_access_token_ttl_seconds
    now = int(time.time())
    header = {"alg": cfg.jwt_algorithm, "typ": "JWT"}
    payload = {
        "sub": subject,
        "role": role,
        "scopes": list(scopes),
        "iss": cfg.jwt_issuer,
        "aud": cfg.jwt_audience,
        "iat": now,
        "nbf": now,
        "exp": now + ttl,
    }
    signing_input = (
        f"{_b64url_encode(json.dumps(header, separators=(',', ':')).encode('utf-8'))}."
        f"{_b64url_encode(json.dumps(payload, separators=(',', ':')).encode('utf-8'))}"
    )
    if cfg.jwt_algorithm != "HS256":
        raise AppAPIError(
            status_code=503,
            code="jwt_algorithm_unsupported",
            message=f"Unsupported JWT algorithm '{cfg.jwt_algorithm}'",
        )
    sig = hmac.new(cfg.jwt_secret_key.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url_encode(sig)}", ttl


def decode_access_token(token: str, *, settings: Settings | None = None) -> AuthPrincipal:
    """Validate and decode an HS256 JWT access token."""
    cfg = settings or get_settings()
    if not cfg.jwt_secret_key:
        raise JWTValidationError("invalid_token", "JWT authentication is not enabled")
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        raise JWTValidationError("invalid_token", "Malformed JWT bearer token")

    encoded_header, encoded_payload, encoded_sig = parts
    try:
        header = json.loads(_b64url_decode(encoded_header).decode("utf-8"))
        payload = json.loads(_b64url_decode(encoded_payload).decode("utf-8"))
        supplied_sig = _b64url_decode(encoded_sig)
    except Exception as exc:
        raise JWTValidationError("invalid_token", "Malformed JWT token encoding") from exc

    if not isinstance(header, dict) or header.get("alg") != "HS256":
        raise JWTValidationError("invalid_token", "Unsupported or missing JWT signing algorithm")

    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    expected_sig = hmac.new(cfg.jwt_secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_sig, supplied_sig):
        raise JWTValidationError("invalid_token", "Invalid JWT signature")

    if not isinstance(payload, dict):
        raise JWTValidationError("invalid_token", "Invalid JWT claims payload")

    now = time.time()
    exp = payload.get("exp")
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        raise JWTValidationError("invalid_token", "JWT missing valid exp claim")
    if now >= float(exp):
        raise JWTValidationError("token_expired", "JWT token has expired")

    nbf = payload.get("nbf")
    if nbf is not None:
        if isinstance(nbf, bool) or not isinstance(nbf, (int, float)):
            raise JWTValidationError("invalid_token", "JWT nbf claim is invalid")
        if now + 30 < float(nbf):
            raise JWTValidationError("token_not_yet_valid", "JWT token is not yet valid")

    if payload.get("iss") != cfg.jwt_issuer or payload.get("aud") != cfg.jwt_audience:
        raise JWTValidationError("invalid_token", "JWT issuer or audience mismatch")

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise JWTValidationError("invalid_token", "JWT missing valid subject")

    role = payload.get("role")
    if role not in _ALLOWED_JWT_ROLES:
        raise JWTValidationError("invalid_token", "JWT contains invalid role")

    raw_scopes = payload.get("scopes") or []
    if not isinstance(raw_scopes, list) or not all(isinstance(s, str) for s in raw_scopes):
        raise JWTValidationError("invalid_token", "JWT scopes claim must be a list of strings")

    return AuthPrincipal(
        subject=subject.strip(),
        role=role,
        auth_type="jwt",
        scopes=frozenset(raw_scopes),
    )


def resolve_bearer_principal(authorization: str | None, *, settings: Settings | None = None) -> AuthPrincipal:
    """Resolve `Authorization: Bearer <token>` supporting JWT and legacy BACKEND_ACCESS_TOKEN."""
    cfg = settings or get_settings()
    has_shared = bool(cfg.backend_access_token)
    has_jwt = bool(cfg.jwt_secret_key)

    if not has_shared and not has_jwt:
        if cfg.app_env == "production":
            raise AppAPIError(
                status_code=503,
                code="auth_not_configured",
                message="BACKEND_ACCESS_TOKEN or JWT_SECRET_KEY must be configured in production",
            )
        return AuthPrincipal(
            subject="local_dev",
            role="anonymous_dev",
            auth_type="dev_open",
            scopes=frozenset({"*"}),
        )

    supplied = authorization or ""
    if not supplied.startswith("Bearer "):
        raise AppAPIError(
            status_code=401,
            code="unauthorized",
            message="Missing or invalid backend access token",
        )
    token = supplied[7:]
    if not token:
        raise AppAPIError(
            status_code=401,
            code="unauthorized",
            message="Missing or invalid backend access token",
        )

    if has_jwt and token.count(".") == 2:
        try:
            return decode_access_token(token, settings=cfg)
        except JWTValidationError as exc:
            raise AppAPIError(
                status_code=401,
                code=exc.code,
                message=exc.message,
            ) from exc

    if has_shared and hmac.compare_digest(token, cfg.backend_access_token or ""):
        return AuthPrincipal(
            subject="backend_shared_token",
            role="service",
            auth_type="shared_token",
            scopes=frozenset({"*"}),
        )

    raise AppAPIError(
        status_code=401,
        code="unauthorized",
        message="Missing or invalid backend access token",
    )


async def require_backend_access(authorization: str | None = Header(default=None)) -> AuthPrincipal:
    """Authenticate the caller via JWT or legacy shared BACKEND_ACCESS_TOKEN."""
    return resolve_bearer_principal(authorization)


def require_roles(*allowed_roles: AuthRole, allow_shared_token: bool = True):
    """Build a FastAPI dependency requiring the resolved principal to hold an allowed role."""
    allowed_set = set(allowed_roles)

    async def _check_role(principal: AuthPrincipal = Depends(require_backend_access)) -> AuthPrincipal:
        if principal.auth_type == "dev_open":
            return principal
        if principal.auth_type == "shared_token" and allow_shared_token:
            return principal
        if principal.role not in allowed_set:
            raise AppAPIError(
                status_code=403,
                code="forbidden",
                message=f"Role '{principal.role}' is not permitted to perform this action",
                details={"role": principal.role, "required_roles": sorted(allowed_set)},
            )
        return principal

    return _check_role


def authorize_call_access(call_session: Any, principal: AuthPrincipal) -> None:
    """Ensure user principals cannot access another user's call or unowned system calls."""
    if principal.is_privileged:
        return
    if call_session.owner_id != principal.subject:
        raise AppAPIError(
            status_code=403,
            code="call_access_forbidden",
            message="You are not authorized to access this call session",
            details={"call_id": call_session.call_id},
        )


def authorize_speaker_access(speaker_profile: Any, principal: AuthPrincipal) -> None:
    """Ensure user principals can only manage/delete their own speaker profiles."""
    if principal.is_privileged:
        return
    if speaker_profile.owner_id != principal.subject:
        raise AppAPIError(
            status_code=403,
            code="speaker_access_forbidden",
            message="You are not authorized to manage this speaker profile",
            details={"speaker_id": speaker_profile.speaker_id},
        )


async def resolve_websocket_principal(websocket: WebSocket) -> AuthPrincipal | None:
    """Authenticate the first JSON frame when backend auth is configured.

    Development environments without credentials receive the same explicit
    anonymous-dev principal as HTTP routes. Tokens are never accepted in URLs.
    """
    settings = get_settings()
    has_shared = bool(settings.backend_access_token)
    has_jwt = bool(settings.jwt_secret_key)
    if not has_shared and not has_jwt:
        if settings.app_env == "production":
            return None
        return AuthPrincipal(
            subject="local_dev",
            role="anonymous_dev",
            auth_type="dev_open",
            scopes=frozenset({"*"}),
        )

    try:
        message = await websocket.receive_json()
    except Exception:
        return None
    if not isinstance(message, dict) or message.get("type") != "auth":
        return None
    token = message.get("token")
    if not isinstance(token, str) or not token.strip():
        return None
    try:
        return resolve_bearer_principal(f"Bearer {token.strip()}", settings=settings)
    except AppAPIError:
        return None


def require_demo_mode() -> None:
    """Prevent demo-only endpoints from being enabled in production."""
    if get_settings().app_env == "production":
        raise HTTPException(
            status_code=403,
            detail="This demo-only endpoint is disabled in production",
        )



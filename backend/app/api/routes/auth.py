from fastapi import APIRouter, Depends

from app.core.auth import AuthPrincipal, create_access_token, require_backend_access, require_roles
from app.core.config import get_settings
from app.core.rate_limit import rate_limit
from app.schemas.contracts import AuthPrincipalRead, AuthTokenRequest, AuthTokenResponse, ErrorResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/token",
    response_model=AuthTokenResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 429: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    dependencies=[
        Depends(rate_limit("auth_token", lambda s: s.rate_limit_auth_requests)),
    ],
)
async def issue_jwt_token(
    payload: AuthTokenRequest,
    _principal: AuthPrincipal = Depends(require_roles("admin", "service")),
):
    """Issue a short-lived signed JWT using configured JWT_SECRET_KEY and service credentials."""
    settings = get_settings()
    token, expires_in = create_access_token(
        subject=payload.subject,
        role=payload.role,
        scopes=payload.scopes,
        expires_in_seconds=payload.expires_in_seconds,
        settings=settings,
    )
    return AuthTokenResponse(
        access_token=token,
        expires_in=expires_in,
        subject=payload.subject,
        role=payload.role,
        scopes=list(payload.scopes),
    )


@router.get(
    "/me",
    response_model=AuthPrincipalRead,
    responses={401: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def get_current_principal(principal: AuthPrincipal = Depends(require_backend_access)):
    """Return resolved principal metadata for the active bearer credential."""
    return AuthPrincipalRead(
        subject=principal.subject,
        role=principal.role,
        auth_type=principal.auth_type,
        scopes=sorted(principal.scopes),
    )

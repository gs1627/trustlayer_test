from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.schemas.contracts import ErrorDetail, ErrorResponse


class AppAPIError(Exception):
    """Application exception serialized using the shared ErrorResponse envelope."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        provider: str | None = None,
        request_id: str | None = None,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.provider = provider
        self.request_id = request_id
        self.retryable = retryable
        self.details = details or {}
        super().__init__(message)


async def handle_app_api_error(_request: Request, exc: AppAPIError) -> JSONResponse:
    """Serialize AppAPIError into the shared ErrorResponse structure."""
    body = ErrorResponse(
        detail=exc.message,
        error=ErrorDetail(
            code=exc.code,
            message=exc.message,
            provider=exc.provider,
            request_id=exc.request_id,
            retryable=exc.retryable,
            details=exc.details,
        ),
    )
    headers: dict[str, str] = {}
    retry_after = exc.details.get("retry_after_seconds") if isinstance(exc.details, dict) else None
    if exc.status_code == 429 and isinstance(retry_after, (int, float)):
        headers["Retry-After"] = str(max(1, int(retry_after)))
    return JSONResponse(status_code=exc.status_code, content=body.model_dump(mode="json"), headers=headers)

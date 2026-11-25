from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.contracts import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    try:
        await db.execute(text("SELECT 1"))
        database_status = "connected"
    except Exception:
        database_status = "unavailable"
    return HealthResponse(
        status="ok" if database_status == "connected" else "degraded",
        app=settings.app_name,
        environment=settings.app_env,
        database=database_status,
        detectif_configured=bool(settings.detectif_api_key),
    )

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, calls, detectif, health, intelligence, transactions, webhooks
from app.core.config import get_settings
from app.core.errors import AppAPIError, handle_app_api_error
from app.db.session import close_db, init_db

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await detectif.client.aclose()
    await close_db()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Member 1 backend foundation for TRUSTLAYER.",
    lifespan=lifespan,
)
app.add_exception_handler(AppAPIError, handle_app_api_error)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Correlation-ID"],
)

app.include_router(health.router, prefix=settings.api_v1_prefix)
app.include_router(auth.router, prefix=settings.api_v1_prefix)
app.include_router(detectif.router, prefix=settings.api_v1_prefix)
app.include_router(webhooks.router, prefix=settings.api_v1_prefix)
app.include_router(calls.router, prefix=settings.api_v1_prefix)
app.include_router(intelligence.router, prefix=settings.api_v1_prefix)
app.include_router(transactions.router, prefix=settings.api_v1_prefix)


@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "docs": "/docs",
        "health": f"{settings.api_v1_prefix}/health",
    }

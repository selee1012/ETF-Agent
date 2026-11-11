"""FastAPI 앱 팩토리: 설정·로깅·CORS·DB 수명주기와 /health."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import dispose_engine, get_session
from app.logging import configure_logging, get_logger
from app.settings import Settings, get_settings

log = get_logger(__name__)

HEALTH_DB_TIMEOUT_SECONDS = 2.0


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "error"]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(title="ETF Agent API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.get("/health", response_model=HealthResponse, tags=["ops"])
    async def health(
        response: Response,
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> HealthResponse:
        try:
            async with asyncio.timeout(HEALTH_DB_TIMEOUT_SECONDS):
                await session.execute(text("SELECT 1"))
        except Exception:
            log.exception("health_db_check_failed")
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return HealthResponse(status="degraded", db="error")
        return HealthResponse(status="ok", db="ok")

    log.info("app_created", app_env=settings.app_env.value)
    return app

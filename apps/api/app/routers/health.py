"""/health: DB 연결 확인(실패 시 503)."""

import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.logging import get_logger

log = get_logger(__name__)
router = APIRouter(tags=["ops"])

HEALTH_DB_TIMEOUT_SECONDS = 2.0


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "error"]


@router.get("/health", response_model=HealthResponse)
async def health(
    response: Response, session: Annotated[AsyncSession, Depends(get_session)]
) -> HealthResponse:
    try:
        async with asyncio.timeout(HEALTH_DB_TIMEOUT_SECONDS):
            await session.execute(text("SELECT 1"))
    except Exception:
        log.exception("health_db_check_failed")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="degraded", db="error")
    return HealthResponse(status="ok", db="ok")

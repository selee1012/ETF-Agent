"""/health: 실제 DB 연결(SELECT 1)과 장애 시 503 응답."""

from collections.abc import AsyncIterator

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import get_session


async def test_health_ok_with_real_db(client: AsyncClient) -> None:
    resp = await client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok"}


async def test_health_degraded_when_db_unreachable(app: FastAPI, client: AsyncClient) -> None:
    engine = create_async_engine("postgresql+asyncpg://u:p@127.0.0.1:1/none")
    maker = async_sessionmaker(engine)

    async def broken_session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = broken_session
    try:
        resp = await client.get("/health")
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()

    assert resp.status_code == 503
    assert resp.json() == {"status": "degraded", "db": "error"}


async def test_cors_allows_only_configured_origins(client: AsyncClient) -> None:
    def preflight(origin: str) -> dict[str, str]:
        return {"Origin": origin, "Access-Control-Request-Method": "GET"}

    allowed = await client.options("/health", headers=preflight("http://localhost:5173"))
    denied = await client.options("/health", headers=preflight("https://bad.example"))

    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in denied.headers

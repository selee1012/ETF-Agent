"""FastAPI 앱 팩토리: 설정·로깅·CORS·어댑터 컨테이너·라우터·메트릭 미들웨어."""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.container import build_container
from app.db import dispose_engine
from app.logging import configure_logging, get_logger
from app.observability.metrics import observe_http
from app.routers import admin, auth, chat, feedback, health, history, metrics
from app.settings import Settings, get_settings

log = get_logger(__name__)


class MetricsMiddleware:
    """요청 수·지연 시간(라우트 템플릿 기준 라벨)"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = getattr(scope.get("route"), "path", "unmatched")
            if route != "/metrics":
                observe_http(scope["method"], route, status_code, time.perf_counter() - start)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(title="ETF Agent API", version="0.1.0", lifespan=lifespan)
    app.state.container = build_container(settings)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    for r in (health, auth, chat, history, feedback, admin, metrics):
        app.include_router(r.router)

    log.info(
        "app_created",
        app_env=settings.app_env.value,
        llm_provider=settings.llm_provider.value,
        auth_provider=settings.auth_provider.value,
        storage_provider=settings.storage_provider.value,
        tracer=settings.tracer.value,
    )
    return app

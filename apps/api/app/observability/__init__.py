"""트레이싱·메트릭. TRACER(Enum)로만 고른다."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.observability.base import Tracer, TraceRecord
from app.settings import Settings
from app.settings import Tracer as TracerKind


def build_tracer(settings: Settings, maker: async_sessionmaker[AsyncSession]) -> Tracer:
    match settings.tracer:
        case TracerKind.PG:
            from app.observability.pg_tracer import PgTracer

            return PgTracer(maker)
        case TracerKind.LANGFUSE:
            from app.observability.langfuse_tracer import LangfuseTracer

            return LangfuseTracer()


__all__ = ["TraceRecord", "Tracer", "build_tracer"]

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
            # 스텁(langfuse_tracer.py)을 그대로 끼우면 요청마다 record()가 실패하고 채팅 서비스가 이를
            # 삼켜, 채팅은 되는데 트레이스만 조용히 빠진다. 폴백 설정 누락처럼 기동할 때 막는다.
            raise ValueError("TRACER=langfuse는 아직 구현되지 않았습니다. TRACER=pg를 사용하세요")


__all__ = ["TraceRecord", "Tracer", "build_tracer"]

"""TRACER=pg: Postgres traces 테이블에 요청당 1행. # P1-OP-01"""

from dataclasses import asdict

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.observability.base import Tracer, TraceRecord
from app.privacy import mask_pii
from app.repositories.models import Trace


class PgTracer(Tracer):
    def __init__(self, maker: async_sessionmaker[AsyncSession]) -> None:
        self._maker = maker

    async def record(self, trace: TraceRecord) -> None:
        data = asdict(trace)
        # 사유 문자열에 사용자 입력 조각이 섞여도 개인정보는 남기지 않는다.
        data["guard_reasons"] = [mask_pii(r) for r in trace.guard_reasons]
        async with self._maker() as session:
            session.add(Trace(**data))
            await session.commit()

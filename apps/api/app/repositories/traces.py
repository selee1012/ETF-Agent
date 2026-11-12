"""트레이스 조회(운영 화면). 저장은 observability/pg_tracer.py가 담당한다. # P1-API-04"""

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import Trace


def _filtered(intent: str | None, verdict: str | None) -> Select[tuple[Trace]]:
    stmt = select(Trace)
    if intent:
        # 복수 의도는 "etf_info+disclosure"처럼 저장된다.
        stmt = stmt.where(
            func.array_position(func.string_to_array(Trace.intent, "+"), intent).is_not(None)
        )
    if verdict:
        stmt = stmt.where(Trace.guard_verdict == verdict)
    return stmt


async def list_traces(
    session: AsyncSession,
    *,
    intent: str | None = None,
    verdict: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Trace], int]:
    stmt = _filtered(intent, verdict)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await session.scalars(stmt.order_by(Trace.created_at.desc()).limit(limit).offset(offset))
    return list(rows.all()), int(total or 0)


async def get_trace(session: AsyncSession, request_id: str) -> Trace | None:
    return await session.scalar(select(Trace).where(Trace.request_id == request_id))

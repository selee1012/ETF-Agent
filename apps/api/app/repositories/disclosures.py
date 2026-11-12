"""공시 조회/적재. # P1-AG-05"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import Disclosure


async def upsert_disclosures(session: AsyncSession, rows: Sequence[dict[str, Any]]) -> int:
    for row in rows:
        stmt = insert(Disclosure).values(**row)
        cols = {c: stmt.excluded[c] for c in row if c != "external_id"}
        await session.execute(stmt.on_conflict_do_update(index_elements=["external_id"], set_=cols))
    return len(rows)


async def recent_disclosures(
    session: AsyncSession,
    *,
    tickers: Sequence[str] = (),
    constituents: Sequence[str] = (),
    limit: int = 5,
) -> list[Disclosure]:
    conds = []
    if tickers:
        conds.append(Disclosure.ticker.in_(tickers))
    for name in constituents:
        conds.append(Disclosure.constituent_name.ilike(f"%{name}%"))
    stmt = select(Disclosure)
    if conds:
        stmt = stmt.where(or_(*conds))
    stmt = stmt.order_by(Disclosure.disclosed_at.desc(), Disclosure.id.desc()).limit(limit)
    return list((await session.scalars(stmt)).all())

"""ETF 마스터·시세 조회/적재. # P1-AG-03 P1-DA-02"""

from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import EtfMaster, PriceDaily


def build_alias_text(name: str, aliases: Iterable[str]) -> str:
    return " ".join([name, *aliases])


async def upsert_etfs(session: AsyncSession, rows: Sequence[dict[str, Any]]) -> int:
    if not rows:
        return 0
    values = [
        {**row, "alias_text": build_alias_text(row["name"], row.get("aliases") or [])}
        for row in rows
    ]
    stmt = insert(EtfMaster).values(values)
    update_cols = {
        c: stmt.excluded[c]
        for c in values[0]
        if c != "ticker"  # PK
    }
    update_cols["updated_at"] = func.now()
    await session.execute(stmt.on_conflict_do_update(index_elements=["ticker"], set_=update_cols))
    return len(values)


async def upsert_prices(session: AsyncSession, rows: Sequence[dict[str, Any]]) -> int:
    total = 0
    for start in range(0, len(rows), 500):
        batch = rows[start : start + 500]
        stmt = insert(PriceDaily).values(list(batch))
        cols = {c: stmt.excluded[c] for c in batch[0] if c not in ("ticker", "trade_date")}
        await session.execute(
            stmt.on_conflict_do_update(index_elements=["ticker", "trade_date"], set_=cols)
        )
        total += len(batch)
    return total


async def list_etfs(session: AsyncSession) -> list[EtfMaster]:
    return list((await session.scalars(select(EtfMaster).order_by(EtfMaster.ticker))).all())


async def get_etfs(session: AsyncSession, tickers: Sequence[str]) -> list[EtfMaster]:
    if not tickers:
        return []
    rows = (await session.scalars(select(EtfMaster).where(EtfMaster.ticker.in_(tickers)))).all()
    order = {t: i for i, t in enumerate(tickers)}
    return sorted(rows, key=lambda r: order.get(r.ticker, 0))


async def search_etfs(
    session: AsyncSession,
    *,
    keyword: str | None = None,
    category: str | None = None,
    category_prefix: str | None = None,
    unprefixed_ok: Sequence[str] = (),
    underlying_index: str | None = None,
    max_fee: Decimal | None = None,
    min_fee: Decimal | None = None,
    max_fee_exclusive: bool = False,
    min_fee_exclusive: bool = False,
    limit: int = 10,
) -> list[EtfMaster]:
    """ETF 검색·필터(분류, 기초지수, 보수 범위). 키워드는 이름·별칭 trgm 유사도로 정렬.

    category_prefix는 분류 앞부분(국내·해외), *_exclusive는 경계값 제외(미만·초과).
    unprefixed_ok를 주면, 그 접두어들 중 어느 것으로도 시작하지 않는 분류(지역 표기가 없는
    '부동산'·'원자재' 등)도 category_prefix 조건을 통과시킨다.
    """
    stmt: Select[tuple[EtfMaster]] = select(EtfMaster)
    if category:
        stmt = stmt.where(EtfMaster.category.ilike(f"%{category}%"))
    if underlying_index:
        stmt = stmt.where(EtfMaster.underlying_index.ilike(f"%{underlying_index}%"))
    if category_prefix:
        cond = EtfMaster.category.like(f"{category_prefix}%")
        if unprefixed_ok:
            cond = or_(cond, and_(*(EtfMaster.category.not_like(f"{x}%") for x in unprefixed_ok)))
        stmt = stmt.where(cond)
    fee = EtfMaster.total_expense_ratio
    if max_fee is not None:
        stmt = stmt.where(fee < max_fee if max_fee_exclusive else fee <= max_fee)
    if min_fee is not None:
        stmt = stmt.where(fee > min_fee if min_fee_exclusive else fee >= min_fee)
    if keyword:
        sim = func.greatest(
            func.similarity(EtfMaster.name, keyword), func.similarity(EtfMaster.alias_text, keyword)
        )
        stmt = stmt.where(sim > 0.1).order_by(sim.desc())
    else:
        stmt = stmt.order_by(EtfMaster.total_expense_ratio.asc().nulls_last(), EtfMaster.ticker)
    return list((await session.scalars(stmt.limit(limit))).all())


async def latest_prices(session: AsyncSession, tickers: Sequence[str]) -> dict[str, PriceDaily]:
    """티커별 최신 일별 시세 1행."""
    if not tickers:
        return {}
    latest = (
        select(PriceDaily.ticker, func.max(PriceDaily.trade_date).label("d"))
        .where(PriceDaily.ticker.in_(tickers))
        .group_by(PriceDaily.ticker)
        .subquery()
    )
    stmt = select(PriceDaily).join(
        latest, (PriceDaily.ticker == latest.c.ticker) & (PriceDaily.trade_date == latest.c.d)
    )
    return {p.ticker: p for p in (await session.scalars(stmt)).all()}


async def price_history(session: AsyncSession, ticker: str, days: int = 30) -> list[PriceDaily]:
    stmt = (
        select(PriceDaily)
        .where(PriceDaily.ticker == ticker)
        .order_by(PriceDaily.trade_date.desc())
        .limit(days)
    )
    return list(reversed((await session.scalars(stmt)).all()))

"""ETF 마스터·시세 조회/적재. # P1-AG-03 P1-DA-02"""

from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, false, func, not_, or_, select
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


# 분류 앞머리로 쓰는 지역 표기. 지역은 분류('국내 주식 …')로만 알 수 있다.
REGION_PREFIXES = ("국내", "해외")


def _filter_terms(
    *,
    category: str | None,
    category_prefix: str | None,
    unprefixed_ok: Sequence[str],
    underlying_index: str | None,
    max_fee: Decimal | None,
    min_fee: Decimal | None,
    max_fee_exclusive: bool,
    min_fee_exclusive: bool,
) -> list[tuple[ColumnElement[bool], ColumnElement[bool]]]:
    """조건마다 (만족 여부, 값이 없어 판단할 수 없는지) 쌍. 검색과 '확인 못 한 상품 수'가 같이 쓴다."""
    cat, fee = EtfMaster.category, EtfMaster.total_expense_ratio
    terms: list[tuple[ColumnElement[bool], ColumnElement[bool]]] = []
    if category:
        terms.append((cat.ilike(f"%{category}%"), cat.is_(None)))
    if underlying_index:
        idx = EtfMaster.underlying_index
        terms.append((idx.ilike(f"%{underlying_index}%"), idx.is_(None)))
    if category_prefix:
        cond = cat.like(f"{category_prefix}%")
        unknown = cat.is_(None)
        if unprefixed_ok:
            cond = or_(cond, and_(*(cat.not_like(f"{x}%") for x in unprefixed_ok)))
        else:  # 지역 표기가 없는 분류('부동산'·'원자재')도 지역을 알 수 없다
            unknown = or_(unknown, and_(*(cat.not_like(f"{x}%") for x in REGION_PREFIXES)))
        terms.append((cond, unknown))
    if max_fee is not None:
        terms.append((fee < max_fee if max_fee_exclusive else fee <= max_fee, fee.is_(None)))
    if min_fee is not None:
        terms.append((fee > min_fee if min_fee_exclusive else fee >= min_fee, fee.is_(None)))
    return terms


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
    terms = _filter_terms(
        category=category,
        category_prefix=category_prefix,
        unprefixed_ok=unprefixed_ok,
        underlying_index=underlying_index,
        max_fee=max_fee,
        min_fee=min_fee,
        max_fee_exclusive=max_fee_exclusive,
        min_fee_exclusive=min_fee_exclusive,
    )
    stmt: Select[tuple[EtfMaster]] = select(EtfMaster).where(*(cond for cond, _ in terms))
    if keyword:
        sim = func.greatest(
            func.similarity(EtfMaster.name, keyword), func.similarity(EtfMaster.alias_text, keyword)
        )
        stmt = stmt.where(sim > 0.1).order_by(sim.desc())
    else:
        stmt = stmt.order_by(EtfMaster.total_expense_ratio.asc().nulls_last(), EtfMaster.ticker)
    return list((await session.scalars(stmt.limit(limit))).all())


async def count_unverifiable(
    session: AsyncSession,
    *,
    category: str | None = None,
    category_prefix: str | None = None,
    unprefixed_ok: Sequence[str] = (),
    underlying_index: str | None = None,
    max_fee: Decimal | None = None,
    min_fee: Decimal | None = None,
    max_fee_exclusive: bool = False,
    min_fee_exclusive: bool = False,
) -> int:
    """같은 조건의 search_etfs가 '값이 없어 판단할 수 없어서' 뺀 상품 수.

    확인된 값으로 이미 탈락한 상품(분류가 '국내 채권'인데 '해외 주식'을 찾는 경우)은 세지 않는다.
    즉 모든 조건이 '만족하거나 판단 불가'이고, 그중 하나 이상이 판단 불가인 상품이다.
    """
    terms = _filter_terms(
        category=category,
        category_prefix=category_prefix,
        unprefixed_ok=unprefixed_ok,
        underlying_index=underlying_index,
        max_fee=max_fee,
        min_fee=min_fee,
        max_fee_exclusive=max_fee_exclusive,
        min_fee_exclusive=min_fee_exclusive,
    )
    if not terms:
        return 0
    met = [func.coalesce(cond, false()) for cond, _ in terms]  # 값이 없으면 비교 결과가 NULL이다
    possible = and_(*(or_(m, unknown) for m, (_, unknown) in zip(met, terms, strict=True)))
    stmt = select(func.count()).select_from(EtfMaster).where(possible, not_(and_(*met)))
    return int(await session.scalar(stmt) or 0)


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

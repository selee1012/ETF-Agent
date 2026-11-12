"""최신 일별 시세·괴리율 조회 도구(캐시 1시간, 키 price:latest:{ticker}). # P1-AG-03"""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app import cache
from app.repositories import etf as etf_repo
from app.repositories.models import PriceDaily


async def latest(session: AsyncSession, tickers: Sequence[str]) -> dict[str, PriceDaily]:
    c = cache.price_cache()
    out: dict[str, PriceDaily] = {}
    missing = []
    for t in tickers:
        if (hit := c.get(cache.price_key(t))) is not None:
            out[t] = hit
        else:
            missing.append(t)
    if missing:
        fresh = await etf_repo.latest_prices(session, missing)
        for t, p in fresh.items():
            c[cache.price_key(t)] = p
        out.update(fresh)
    return out


async def etfs(session: AsyncSession, tickers: Sequence[str]):
    """ETF 마스터 단건 조회(캐시 1일, 키 etf:{ticker})."""
    c = cache.etf_cache()
    found = {t: c[cache.etf_key(t)] for t in tickers if cache.etf_key(t) in c}
    missing = [t for t in tickers if t not in found]
    for row in await etf_repo.get_etfs(session, missing):
        c[cache.etf_key(row.ticker)] = row
        found[row.ticker] = row
    return [found[t] for t in tickers if t in found]

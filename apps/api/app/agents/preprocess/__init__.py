"""발화 전처리: 정규화 + ETF명·티커 인식(오타 허용). # P1-AG-01"""

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import cache
from app.agents.state import EtfEntity
from app.repositories import etf as etf_repo

_KEEP = re.compile(r"[^0-9A-Za-z가-힣\s%.,?!&+\-~/()]")
_TICKER = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """NFKC(전각→반각), 제어·특수기호 제거, 공백 정리. 숫자·%·소수점은 남긴다."""
    text = unicodedata.normalize("NFKC", text)
    text = _KEEP.sub(" ", text)
    text = re.sub(r"([?!.,])\1+", r"\1", text)  # 반복 기호 축약
    return _WS.sub(" ", text).strip()


def compact(text: str) -> str:
    """매칭용: 소문자, 한글·영숫자만(공백·기호 제거). 'S&P 500' → 'sp500'"""
    return re.sub(r"[^0-9a-z가-힣]", "", text.lower())


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    ticker: str
    name: str
    keys: tuple[str, ...]  # 이름·별칭의 compact 형태
    underlying_index: str | None
    category: str | None


async def load_catalog(maker: async_sessionmaker[AsyncSession]) -> list[CatalogEntry]:
    """ETF 마스터를 이름·별칭 사전으로 캐시(1일, 키 etf_master:all)."""
    c = cache.etf_cache()
    if (hit := c.get(cache.ETF_MASTER_ALL)) is not None:
        return hit
    async with maker() as session:
        rows = await etf_repo.list_etfs(session)
    catalog = [
        CatalogEntry(
            ticker=r.ticker,
            name=r.name,
            keys=tuple(dict.fromkeys(k for k in map(compact, [r.name, *r.aliases]) if k)),
            underlying_index=r.underlying_index,
            category=r.category,
        )
        for r in rows
    ]
    c[cache.ETF_MASTER_ALL] = catalog
    return catalog


def recognize_entities(
    text: str, catalog: list[CatalogEntry], *, fuzzy_threshold: int = 80, limit: int = 3
) -> list[EtfEntity]:
    """1) 티커 2) 이름·별칭 정확 포함(긴 것 우선) 3) rapidfuzz 부분 정렬로 오타 허용."""
    found: dict[str, EtfEntity] = {}
    pos: dict[str, int] = {}  # 질문 안 위치(언급 순서대로 돌려주기 위함)
    by_ticker = {e.ticker: e for e in catalog}
    q = compact(text)

    for m in _TICKER.finditer(text):
        if (e := by_ticker.get(m.group(1))) is not None:
            found.setdefault(e.ticker, EtfEntity(e.ticker, e.name, m.group(1), 100.0, "ticker"))
            pos.setdefault(e.ticker, q.find(m.group(1)))

    masked = q
    keys = sorted(((k, e) for e in catalog for k in e.keys), key=lambda x: -len(x[0]))
    for key, e in keys:  # 정확 포함: 긴 키부터, 매칭된 구간은 지워 짧은 키의 중복 매칭을 막는다
        idx = masked.find(key)
        if idx >= 0 and len(key) >= 3:
            masked = masked[:idx] + "#" * len(key) + masked[idx + len(key) :]
            found.setdefault(e.ticker, EtfEntity(e.ticker, e.name, key, 100.0, "exact"))
            pos.setdefault(e.ticker, idx)

    best: dict[str, tuple[float, str, int, int]] = {}
    for key, e in keys:  # 오타 허용(남은 구간에서만)
        if e.ticker in found or len(key) < 5:
            continue
        al = fuzz.partial_ratio_alignment(key, masked, score_cutoff=fuzzy_threshold)
        if al is None or "#" in masked[al.dest_start : al.dest_end]:
            continue
        span = masked[al.dest_start : al.dest_end]
        # 짧은 공통 접두어(예: '샘플')만 맞는 경우를 거른다: 매칭 길이가 키의 80% 이상
        if len(span) < 0.8 * len(key):
            continue
        prev = best.get(e.ticker)
        if prev is None or al.score > prev[0]:
            best[e.ticker] = (al.score, span, al.dest_start, al.dest_end)
    # 겹치는 구간은 점수가 높은 쪽만 남긴다
    taken: list[tuple[int, int]] = []
    for ticker, (score, span, s, t) in sorted(best.items(), key=lambda x: -x[1][0]):
        if any(s < b and a < t for a, b in taken):
            continue
        taken.append((s, t))
        found[ticker] = EtfEntity(ticker, by_ticker[ticker].name, span, round(score, 1), "fuzzy")
        pos[ticker] = s

    return sorted(found.values(), key=lambda x: pos.get(x.ticker, 0))[:limit]

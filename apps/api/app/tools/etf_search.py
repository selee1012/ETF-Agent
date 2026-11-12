"""ETF 검색·필터 도구(분류, 기초지수, 보수 범위). # P1-AG-03"""

import re
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import etf as etf_repo
from app.repositories.models import EtfMaster

_FEE_RE = re.compile(
    r"(?:보수|수수료|비용)[^\d]{0,12}(\d+(?:\.\d+)?)\s*%?\s*(이하|미만|이내|이상|초과)?"
)
# 질문 표현 → etf_master.category 부분 문자열
_CATEGORY = [
    ("레버리지", "레버리지"),
    ("인버스", "레버리지·인버스"),
    ("채권", "채권"),
    ("배당", "배당"),
    ("원자재", "원자재"),
    ("금리", "단기금리"),
    ("파킹", "단기금리"),
    ("리츠", "부동산"),
    ("부동산", "부동산"),
    ("테마", "테마"),
    ("업종", "업종"),
    ("자산배분", "자산배분"),
    ("tdf", "자산배분"),
    ("주식", "주식"),
]


@dataclass(slots=True)
class EtfFilters:
    category: str | None = None
    region: str | None = None  # 국내 | 해외
    underlying_index: str | None = None
    max_fee: Decimal | None = None
    min_fee: Decimal | None = None

    def is_empty(self) -> bool:
        return not any(
            (self.category, self.region, self.underlying_index, self.max_fee, self.min_fee)
        )

    def describe(self) -> str:
        parts = []
        if self.region:
            parts.append(self.region)
        if self.category:
            parts.append(f"분류 '{self.category}'")
        if self.underlying_index:
            parts.append(f"기초지수 '{self.underlying_index}'")
        if self.max_fee is not None:
            parts.append(f"총보수 {self.max_fee}% 이하")
        if self.min_fee is not None:
            parts.append(f"총보수 {self.min_fee}% 이상")
        return ", ".join(parts) or "조건 없음"


def parse_filters(text: str, known_indexes: list[str]) -> EtfFilters:
    f = EtfFilters()
    low = text.lower()
    if m := _FEE_RE.search(text):
        value = Decimal(m.group(1))
        if m.group(2) in ("이상", "초과"):
            f.min_fee = value
        else:
            f.max_fee = value
    for word, cat in _CATEGORY:
        if word in low:
            f.category = cat
            break
    if "해외" in text or "미국" in text:
        f.region = "해외"
    elif "국내" in text:
        f.region = "국내"
    squashed = re.sub(r"[^0-9a-z가-힣]", "", low)
    for idx in sorted(known_indexes, key=len, reverse=True):
        key = re.sub(r"[^0-9a-z가-힣]", "", idx.lower())
        if len(key) >= 4 and key in squashed:
            f.underlying_index = idx
            break
    return f


async def search(session: AsyncSession, f: EtfFilters, limit: int = 10) -> list[EtfMaster]:
    rows = await etf_repo.search_etfs(
        session,
        category=f.category,
        underlying_index=f.underlying_index,
        max_fee=f.max_fee,
        min_fee=f.min_fee,
        limit=50,
    )
    if f.region:
        rows = [r for r in rows if (r.category or "").startswith(f.region)]
    return rows[:limit]

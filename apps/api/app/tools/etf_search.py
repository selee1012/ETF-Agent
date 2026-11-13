"""ETF 검색·필터 도구(분류, 기초지수, 보수 범위). # P1-AG-03"""

import re
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import etf as etf_repo
from app.repositories.models import EtfMaster

# 보수 조건: '보수|수수료|비용' 뒤에 오는 숫자 중 %(퍼센트·프로)나 비교어가 붙은 것만 조건이다.
# 없으면 '보수 낮은 순으로 3개'의 3처럼 보수와 무관한 숫자다.
_FEE_KEY = re.compile(r"보수|수수료|비용")
_FEE_NUM = re.compile(
    r"(\d+(?:\.\d+)?)\s*(%|퍼센트|프로)?\s*(?:보다\s*)?"
    r"(이하|이내|이상|미만|초과|넘|높[은게아]|큰|많[은이]|낮[은게아]|작[은게아]|적[은게]|밑|아래)?"
)
_FEE_FIRST_GAP = 12  # 보수 표현과 첫 숫자 사이
_FEE_NEXT_GAP = 6  # 범위 조건('0.1% 이상 0.3% 이하')의 두 숫자 사이


def _fee_op(word: str | None) -> tuple[str, bool]:
    """비교어 → (max|min, 경계 제외 여부). 비교어 없이 %만 있으면 '이하'로 본다."""
    if word is None or word in ("이하", "이내"):
        return "max", False
    if word == "이상":
        return "min", False
    if word in ("미만", "밑", "아래") or word[0] in "낮작적":
        return "max", True
    return "min", True  # 초과·넘·높·큰·많


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


REGIONS = ("국내", "해외")


@dataclass(slots=True)
class EtfFilters:
    category: str | None = None
    region: str | None = None  # 국내 | 해외
    underlying_index: str | None = None
    max_fee: Decimal | None = None
    min_fee: Decimal | None = None
    max_exclusive: bool = False  # 미만(경계값 제외)
    min_exclusive: bool = False  # 초과(경계값 제외)

    def is_empty(self) -> bool:
        # 보수 0도 조건이다(Decimal(0)은 거짓이라 값의 참거짓으로 보면 안 된다).
        return (
            not any((self.category, self.region, self.underlying_index))
            and self.max_fee is None
            and self.min_fee is None
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
            parts.append(f"총보수 {self.max_fee}% {'미만' if self.max_exclusive else '이하'}")
        if self.min_fee is not None:
            parts.append(f"총보수 {self.min_fee}% {'초과' if self.min_exclusive else '이상'}")
        return ", ".join(parts) or "조건 없음"


def parse_filters(text: str, known_indexes: list[str]) -> EtfFilters:
    f = EtfFilters()
    low = text.lower()
    if key := _FEE_KEY.search(text):
        pos, gap = key.end(), _FEE_FIRST_GAP
        for m in _FEE_NUM.finditer(text, pos):
            unit, op = m.group(2), m.group(3)
            if m.start() - pos > gap or not (unit or op):
                break
            side, exclusive = _fee_op(op)
            value = Decimal(m.group(1))
            if side == "max":
                f.max_fee, f.max_exclusive = value, exclusive
            else:
                f.min_fee, f.min_exclusive = value, exclusive
            pos, gap = m.end(), _FEE_NEXT_GAP
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
    # 지역도 DB에서 거른다(LIMIT 뒤에 거르면 앞쪽 N건 밖의 일치 상품이 빠진다).
    # 지역은 분류 앞머리('국내 주식 …')로만 알 수 있다. '부동산'·'원자재'처럼 지역 표기가 없는
    # 분류를 함께 물으면('국내 리츠') 지역을 확인할 수 없으므로 그 분류의 상품은 빼지 않는다.
    return await etf_repo.search_etfs(
        session,
        category=f.category,
        category_prefix=f.region,
        unprefixed_ok=REGIONS if f.region and f.category else (),
        underlying_index=f.underlying_index,
        max_fee=f.max_fee,
        min_fee=f.min_fee,
        max_fee_exclusive=f.max_exclusive,
        min_fee_exclusive=f.min_exclusive,
        limit=limit,
    )

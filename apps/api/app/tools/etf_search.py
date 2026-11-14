"""ETF 검색·필터 도구(분류, 기초지수, 보수 범위). # P1-AG-03"""

import re
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import etf as etf_repo
from app.repositories.models import EtfMaster

# ---------- 보수 조건 ----------
# '보수|수수료|비용' 뒤에 이어지는 수치를 읽는다. 비교어는 수치 바로 뒤에 붙지 않아도 된다
# ('0.3%를 초과하는', '0.3%가 넘는', '0.5%보다 더 낮은'): 수치 뒤의 짧은 구간에서 찾는다.
_FEE_KEY = re.compile(r"보수|수수료|비용")
_PCT = r"(?:%|퍼센트|프로)"
_NUM = r"\d+(?:\.\d+)?"
_FEE_NUM = re.compile(rf"({_NUM})\s*({_PCT})?")
# 범위 표기: 0.1~0.3%, 0.1%-0.3%, 0.1%에서 0.3% 사이, 0.1%부터 0.3%까지
_FEE_RANGE = re.compile(rf"({_NUM})\s*{_PCT}?\s*(?:~|-|에서|부터)\s*({_NUM})\s*{_PCT}")
# 비교어 → (max|min, 경계 제외 여부)
_FEE_OPS: list[tuple[re.Pattern[str], tuple[str, bool]]] = [
    (re.compile(r"이하|이내"), ("max", False)),
    (re.compile(r"이상"), ("min", False)),
    (re.compile(r"미만|밑|아래|낮|작[은게아]|적[은게]|싼|저렴"), ("max", True)),
    (re.compile(r"초과|넘|높|큰|많[은이]|비싼"), ("min", True)),
]
# 수치와 보수 표현 사이에 이 말이 끼면 그 수치는 보수가 아니다('수수료 싼 배당률 4% 이상')
_OTHER_METRIC = re.compile(
    r"배당|분배|수익|괴리|금리|순자산|거래량|가격|시세|종가|nav", re.IGNORECASE
)
# 비교어를 찾는 구간은 다음 수치나 대상 명사 앞에서 끊는다('0.3% ETF 중 순자산 많은')
_OP_STOP = re.compile(r"\d|etf|이티에프|상품|펀드|,|이고|면서", re.IGNORECASE)
_FEE_FIRST_GAP = 12  # 보수 표현과 첫 수치 사이
_FEE_NEXT_GAP = 8  # 두 번째 조건('0.1% 이상 0.3% 이하')까지
_OP_WINDOW = 10  # 수치 뒤에서 비교어를 찾는 길이


def _fee_op(tail: str) -> tuple[str, bool] | None:
    """수치 뒤 구간에서 가장 먼저 나오는 비교어."""
    if stop := _OP_STOP.search(tail):
        tail = tail[: stop.start()]
    found = [(m.start(), op) for pat, op in _FEE_OPS if (m := pat.search(tail))]
    return min(found)[1] if found else None


def _parse_fee(text: str, f: EtfFilters) -> None:
    key = _FEE_KEY.search(text)
    if key is None:
        return
    pos, gap = key.end(), _FEE_FIRST_GAP
    while (m := _FEE_NUM.search(text, pos)) is not None:
        between = text[pos : m.start()]
        if len(between) > gap or _OTHER_METRIC.search(between):
            return
        if r := _FEE_RANGE.match(text, m.start()):
            low, high = sorted((Decimal(r.group(1)), Decimal(r.group(2))))
            f.min_fee, f.min_exclusive = low, False
            f.max_fee, f.max_exclusive = high, False
            return
        op = _fee_op(text[m.end() : m.end() + _OP_WINDOW])
        if op is None:
            if not m.group(2):
                return  # 단위도 비교어도 없다: '보수 낮은 순으로 3개'의 3
            op = ("max", False)  # '보수 0.3% ETF'는 0.3% 이하로 본다
        side, exclusive = op
        if side == "max":
            f.max_fee, f.max_exclusive = Decimal(m.group(1)), exclusive
        else:
            f.min_fee, f.min_exclusive = Decimal(m.group(1)), exclusive
        pos, gap = m.end(), _FEE_NEXT_GAP


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

    def has_fee(self) -> bool:
        return self.max_fee is not None or self.min_fee is not None

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
    _parse_fee(text, f)
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


async def unverifiable_note(session: AsyncSession, f: EtfFilters) -> str:
    """조건에 쓰인 값(분류·총보수)이 비어 있어 확인하지 못하고 뺀 상품이 있으면 그 사실을 알리는 문장.

    외부 수집으로 들어온 상품은 분류·총보수가 없다. 말없이 빼면 '조건에 맞는 상품은 이것뿐'으로 읽힌다.
    """
    by_category, by_fee = bool(f.category or f.region), f.has_fee()
    n = await etf_repo.count_missing(session, category=by_category, fee=by_fee)
    if not n:
        return ""
    fields = "·".join(x for x, on in (("분류", by_category), ("총보수", by_fee)) if on)
    return f"{fields} 정보가 없는 상품 {n}개는 조건을 확인할 수 없어 결과에서 뺐습니다."


def region_unverified(f: EtfFilters, etfs: list[EtfMaster]) -> list[EtfMaster]:
    """지역 조건을 걸었지만 분류에 지역 표기가 없어 지역을 확인하지 못한 채 결과에 넣은 상품.

    search()는 '국내 리츠'처럼 지역과 분류를 함께 물으면 '부동산'·'원자재' 같은 분류를 빼지 않는다.
    """
    if not (f.region and f.category):
        return []
    return [e for e in etfs if not (e.category or "").startswith(REGIONS)]

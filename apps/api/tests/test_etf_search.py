"""ETF 검색 조건 해석: 보수 범위(이하·미만·이상·초과), 보수와 무관한 숫자, 지역 필터 (P1-AG-03)."""

from decimal import Decimal

import pytest

from app.agents.state import AgentDeps
from app.tools.etf_search import EtfFilters, parse_filters, search


@pytest.mark.parametrize(
    ("text", "expected", "described"),
    [
        ("총보수 0.1% 이하 ETF", ("max", "0.1", False), "총보수 0.1% 이하"),
        ("총보수 0.1% 미만 ETF", ("max", "0.1", True), "총보수 0.1% 미만"),
        ("보수 0.5 이상인 ETF", ("min", "0.5", False), "총보수 0.5% 이상"),
        ("수수료 0.5% 초과 ETF", ("min", "0.5", True), "총보수 0.5% 초과"),
        ("보수 0.3프로 ETF", ("max", "0.3", False), "총보수 0.3% 이하"),
    ],
)
def test_fee_condition(text: str, expected: tuple[str, str, bool], described: str) -> None:
    f = parse_filters(text, [])
    side, value, exclusive = expected
    if side == "max":
        assert (f.max_fee, f.max_exclusive, f.min_fee) == (Decimal(value), exclusive, None)
    else:
        assert (f.min_fee, f.min_exclusive, f.max_fee) == (Decimal(value), exclusive, None)
    assert f.describe() == described


@pytest.mark.parametrize("text", ["보수 낮은 순으로 3개 찾아줘", "수수료 싼 ETF 5개 알려줘"])
def test_count_is_not_read_as_fee(text: str) -> None:
    f = parse_filters(text, [])
    assert f.max_fee is None and f.min_fee is None


async def test_exclusive_bound_drops_boundary_value(deps: AgentDeps) -> None:
    async with deps.maker() as s:
        upto = await search(s, EtfFilters(region="해외", max_fee=Decimal("0.07")))
        below = await search(
            s, EtfFilters(region="해외", max_fee=Decimal("0.07"), max_exclusive=True)
        )
    assert any(e.total_expense_ratio == Decimal("0.07") for e in upto)
    assert below and all(e.total_expense_ratio < Decimal("0.07") for e in below)


async def test_region_is_filtered_before_limit(deps: AgentDeps) -> None:
    async with deps.maker() as s:
        rows = await search(s, EtfFilters(region="국내"), limit=3)
    assert len(rows) == 3  # 지역 밖 상품이 LIMIT 자리를 차지하지 않는다
    assert all(e.category.startswith("국내") for e in rows)

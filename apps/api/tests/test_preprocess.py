"""발화 전처리: 정규화, 오타·별칭·티커 ETF명 인식(P1-AG-01)."""

import pytest

from app.agents.preprocess import load_catalog, normalize, recognize_entities
from app.agents.state import AgentDeps


def test_normalize_spaces_and_symbols() -> None:
    assert normalize("  샘플   코스피200★★ 괴리율??  ") == "샘플 코스피200 괴리율?"
    # 전각 문자(NFKC 정규화 대상)는 코드 포인트로 만든다
    fullwidth = (
        "".join(chr(0xFEE0 + ord(c)) for c in "SAMPLE") + "\u3000" + "\uff10\uff0e\uff15\uff05"
    )
    assert normalize(fullwidth) == "SAMPLE 0.5%"


@pytest.mark.parametrize(
    ("query", "tickers", "method"),
    [
        ("샘플 코스피200 시세", ["900010"], "exact"),
        ("샘플코스피 괴리율", ["900010"], "exact"),  # 별칭
        ("샘플 나스댁100 괴리율 알려줘", ["900040"], "fuzzy"),  # 오타
        ("샘풀코스닥 시세", ["900020"], "fuzzy"),  # 오타
        ("샘플 S&P 500 가격", ["900030"], "exact"),  # 기호·공백 차이
        ("900050 정보", ["900050"], "ticker"),
        ("샘플 코스피200이랑 샘플 미국S&P500 비교", ["900010", "900030"], "exact"),  # 언급 순서
    ],
)
async def test_recognizes_etf_names(
    deps: AgentDeps, query: str, tickers: list[str], method: str
) -> None:
    catalog = await load_catalog(deps.maker)
    found = recognize_entities(normalize(query), catalog)
    assert [e.ticker for e in found] == tickers
    assert found[0].method == method


async def test_no_false_positive_on_generic_question(deps: AgentDeps) -> None:
    catalog = await load_catalog(deps.maker)
    assert recognize_entities("괴리율이 뭐야?", catalog) == []
    assert recognize_entities("샘플 데이터라는 게 뭐야?", catalog) == []

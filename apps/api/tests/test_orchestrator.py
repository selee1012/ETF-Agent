"""오케스트레이터: LLM JSON 분류, 파싱 실패 시 키워드 규칙, 고위험 우선(P1-AG-02)."""

import pytest

from app.agents.orchestrator import classify, parse_intents
from app.agents.orchestrator.rules import classify_rules
from app.llm.fake import FakeLLM


@pytest.mark.parametrize(
    ("text", "has_entity", "expected"),
    [
        ("샘플 코스피200 괴리율 알려줘", True, ["etf_info"]),
        ("총보수 0.1% 이하 해외 주식 ETF 찾아줘", False, ["etf_info"]),
        ("괴리율이 뭐야?", False, ["faq"]),
        ("ETF 분배금은 언제 받아?", False, ["faq"]),
        ("샘플 반도체 최근 공시 알려줘", True, ["disclosure"]),
        ("샘플 코스피200 지금 사야 할까?", True, ["high_risk"]),
        ("샘플 나스닥 내년에 오를까?", True, ["high_risk"]),
        ("제 세금 얼마 나와요?", False, ["high_risk"]),
        ("손실 보상해 주나요?", False, ["high_risk"]),
        ("ETF 추천해줘", False, ["recommendation"]),
        ("오늘 날씨 어때?", False, ["out_of_scope"]),
        ("샘플 반도체랑 샘플 2차전지 비교하고 뉴스도 알려줘", True, ["etf_info", "disclosure"]),
    ],
)
def test_keyword_rules(text: str, has_entity: bool, expected: list[str]) -> None:
    assert classify_rules(text, has_entity=has_entity) == expected


def test_parse_intents() -> None:
    assert parse_intents('{"intents": ["faq"]}') == ["faq"]
    assert parse_intents('답: {"intents": ["etf_info", "disclosure", "x"]} 끝') == [
        "etf_info",
        "disclosure",
    ]
    assert parse_intents("분류 불가") is None
    assert parse_intents('{"intents": []}') is None


async def test_uses_llm_json_when_valid() -> None:
    llm = FakeLLM(script={"classify": ['{"intents": ["disclosure", "etf_info"]}']})
    intents, source = await classify(llm, "그 ETF 소식이랑 시세", has_entity=True)
    assert source == "llm"
    assert intents == ["etf_info", "disclosure"]  # 에이전트 순서로 정렬


async def test_falls_back_to_rules_on_bad_json() -> None:
    llm = FakeLLM(script={"classify": ["음… faq인 것 같아요"]})
    intents, source = await classify(llm, "괴리율이 뭐야?", has_entity=False)
    assert (intents, source) == (["faq"], "rules")


async def test_high_risk_overrides_llm() -> None:
    llm = FakeLLM(script={"classify": ['{"intents": ["etf_info"]}']})
    intents, _ = await classify(llm, "샘플 코스피200 언제 사야 돼?", has_entity=True)
    assert intents == ["high_risk"]

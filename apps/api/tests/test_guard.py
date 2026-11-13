"""컴플라이언스 가드: 금칙 표현·고지 누락·개인정보·근거 없는 수치, 1회 재생성 후 안전 답변 (P1-AG-06)."""

import json

import pytest

from app.agents.graph import run_graph
from app.agents.guard.judge import parse_judge
from app.agents.guard.rules import check_rules, find_banned, ungrounded_numbers
from app.agents.state import AgentDeps
from app.llm.base import LLMError
from app.llm.fake import FakeLLM


@pytest.mark.parametrize(
    "text",
    [
        "이 ETF는 원금이 보장됩니다.",
        "원금 보장 상품이라 안심하세요.",
        "연 5% 수익 보장",
        "손실이 전혀 없습니다.",
        "무조건 오릅니다.",
        "내년에는 상승할 것입니다.",
        "지금 매수를 추천합니다.",
        "지금 사세요!",
    ],
)
def test_banned_expressions_detected(text: str) -> None:
    assert find_banned(text), text


@pytest.mark.parametrize(
    "text",
    [
        "ETF는 원금이 보장되지 않습니다.",
        "원금 보장되지 않는 상품입니다.",
        "수익이 보장되지 않으며 손실이 날 수 있습니다.",
        "과거 수익률이 미래 수익을 보장하지 않습니다.",
    ],
)
def test_negated_expressions_allowed(text: str) -> None:
    assert find_banned(text) == [], text


def test_ungrounded_numbers() -> None:
    evidence = ["| 종가 | 36,180원 |\n| 괴리율 | 0.23% |"]
    assert ungrounded_numbers("종가는 36,180원, 괴리율은 0.23%입니다.", evidence) == []
    assert ungrounded_numbers("괴리율은 0.5%입니다.", evidence) == ["0.5%"]
    # 날짜·인용 번호·티커는 검사하지 않는다
    assert ungrounded_numbers("2026-11-11 기준 900010 [1]", evidence) == []


def test_missing_disclaimer_and_pii() -> None:
    reasons = check_rules(
        "연락처 010-1234-5678로 주세요",
        included_disclaimers=[],
        required_disclaimers=["general"],
        evidence=[],
    )
    assert "missing_disclaimer:general" in reasons
    assert "pii:PHONE" in reasons


async def test_banned_answer_regenerates_once_then_safe_answer(
    deps: AgentDeps, fake_llm: FakeLLM
) -> None:
    bad = "ETF는 원금이 보장되는 안전한 상품입니다. [1]"
    fake_llm.push("answer", bad, bad)
    st = await run_graph(deps, request_id="t", query="ETF가 뭐야?")
    assert fake_llm.count("answer") == 2  # 최초 1회 + 재생성 1회
    assert st["verdict"] == "blocked"
    assert "원금이 보장되는" not in st["answer"]
    assert "문의" in st["answer"]  # 안전 답변 + 문의 채널
    assert any("banned:guarantee_principal" in rs for rs in st["guard_history"])


async def test_regeneration_can_pass(deps: AgentDeps, fake_llm: FakeLLM) -> None:
    fake_llm.push(
        "answer",
        "ETF는 무조건 오릅니다. [1]",
        "ETF는 지수를 따라가도록 만든 펀드를 거래소에 상장한 상품입니다. [1]",
    )
    st = await run_graph(deps, request_id="t", query="ETF가 뭐야?")
    assert st["verdict"] == "pass_after_retry"
    assert "무조건" not in st["answer"]


async def test_judge_model_blocks_solicitation(deps: AgentDeps, fake_llm: FakeLLM) -> None:
    verdict = json.dumps({"grounded": True, "is_solicitation": True, "issues": ["권유"]})
    fake_llm.push("judge", verdict, verdict)
    st = await run_graph(deps, request_id="t", query="괴리율이 뭐야?")
    assert fake_llm.count("judge") == 2
    assert st["verdict"] == "blocked"
    assert any("judge:solicitation" in rs for rs in st["guard_history"])


async def test_judge_unparsed_is_asked_again(deps: AgentDeps, fake_llm: FakeLLM) -> None:
    fake_llm.push("judge", "판정 불가")  # 두 번째 응답은 기본값(정상 판정)
    st = await run_graph(deps, request_id="t", query="괴리율이 뭐야?")
    assert fake_llm.count("judge") == 2
    assert st["verdict"] == "pass"
    assert st["guard_history"] == [[]]


async def test_judge_unparsed_twice_gives_safe_answer(deps: AgentDeps, fake_llm: FakeLLM) -> None:
    fake_llm.push("judge", "판정 불가", "여전히 판정 불가")
    st = await run_graph(deps, request_id="t", query="괴리율이 뭐야?")
    assert st["verdict"] == "llm_unavailable"
    assert st["guard_history"] == [["judge:unparsed"]]
    assert fake_llm.count("answer") == 1  # 답변을 다시 쓰지 않는다
    assert "문의" in st["answer"] and not st["sources"]


async def test_judge_unavailable_gives_safe_answer_and_is_not_cached(
    deps: AgentDeps, fake_llm: FakeLLM
) -> None:
    fake_llm.push("judge", LLMError("down"))
    st = await run_graph(deps, request_id="t", query="괴리율이 뭐야?")
    assert st["verdict"] == "llm_unavailable"
    assert st["guard_history"] == [["judge:unavailable"]]
    assert fake_llm.count("answer") == 1 and fake_llm.count("judge") == 1
    assert "문의" in st["answer"]

    # 검증하지 못한 답변은 캐시에 남지 않는다: 검증 모델이 돌아오면 새로 작성해 통과한다
    st = await run_graph(deps, request_id="t2", query="괴리율이 뭐야?")
    assert st["verdict"] == "pass"
    assert fake_llm.count("answer") == 2


async def test_ungrounded_number_in_summary_blocks(deps: AgentDeps, fake_llm: FakeLLM) -> None:
    fake_llm.push("answer", "샘플 코스피200의 괴리율은 9.99%입니다.")
    st = await run_graph(deps, request_id="t", query="샘플 코스피200 괴리율")
    # 재생성 시도에서는 요약 없이 DB 표만 내보내므로 통과한다
    assert st["verdict"] == "pass_after_retry"
    assert "9.99%" not in st["answer"]
    assert "ungrounded_number:9.99%" in st["guard_history"][0]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"grounded": false, "is_solicitation": false}', (False, False)),
        ('{"grounded": "false", "is_solicitation": "false"}', (False, False)),
        ('{"grounded": "True", "is_solicitation": "no"}', (True, False)),
        ('{"grounded": 1}', (True, False)),
    ],
)
def test_parse_judge_reads_string_booleans(raw: str, expected: tuple[bool, bool]) -> None:
    verdict = parse_judge(raw)
    assert verdict is not None
    assert (verdict["grounded"], verdict["is_solicitation"]) == expected


@pytest.mark.parametrize(
    "raw",
    ['{"grounded": "maybe"}', '{"grounded": null}', '{"grounded": true, "is_solicitation": []}'],
)
def test_parse_judge_rejects_unreadable_values(raw: str) -> None:
    assert parse_judge(raw) is None


async def test_judge_string_false_does_not_pass(deps: AgentDeps, fake_llm: FakeLLM) -> None:
    verdict = '{"grounded": "false", "is_solicitation": "false", "issues": []}'
    fake_llm.push("judge", verdict, verdict)
    st = await run_graph(deps, request_id="t", query="괴리율이 뭐야?")
    assert st["verdict"] == "blocked"
    assert any("judge:ungrounded" in rs for rs in st["guard_history"])

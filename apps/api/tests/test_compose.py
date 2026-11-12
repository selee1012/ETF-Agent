"""자료는 동시에 모으고 LLM은 한 번만: 답변 합성·검색 선행·재생성 범위·캐시 (P1-AG-02, P1-AG-04, P1-AG-06)."""

import json

import pytest

from app.agents import faq
from app.agents.graph import run_graph
from app.agents.state import AgentDeps
from app.llm.base import ChatMessage
from app.llm.fake import FakeLLM


async def ask(deps: AgentDeps, q: str, **kw):
    return await run_graph(deps, request_id="test", query=q, **kw)


def capture_answer(llm: FakeLLM, text: str) -> list[list[ChatMessage]]:
    seen: list[list[ChatMessage]] = []

    def reply(messages: list[ChatMessage]) -> str:
        seen.append(messages)
        return text

    llm.push("answer", reply)
    return seen


async def test_multi_intent_collects_in_parallel_and_answers_once(
    deps: AgentDeps, fake_llm: FakeLLM
) -> None:
    fake_llm.push("classify", json.dumps({"intents": ["etf_info", "faq"]}))
    seen = capture_answer(
        fake_llm, "괴리율은 시장가격과 NAV의 차이입니다 [1]. 표의 괴리율을 확인하세요."
    )
    st = await ask(deps, "샘플 코스피200 괴리율이 뭐야?")
    assert st["intents"] == ["etf_info", "faq"]
    assert fake_llm.count("answer") == 1  # 의도가 둘이어도 LLM 답변 호출은 한 번
    user = seen[0][1].content
    assert "[ETF 데이터]" in user and "[근거 1]" in user  # 두 수집 결과를 한 프롬프트에
    ans = st["answer"]
    assert ans.startswith("괴리율은 시장가격과 NAV의 차이입니다.")  # 설명이 먼저, [1]은 지움
    assert "### ETF 정보" in ans and "| 항목 |" in ans  # DB 표는 그대로 아래에
    kinds = {s.kind for s in st["sources"]}
    assert kinds == {"document", "etf_data"}


async def test_answer_prompt_has_level_style_and_rules(deps: AgentDeps, fake_llm: FakeLLM) -> None:
    seen = capture_answer(fake_llm, "ETF는 지수를 따라가는 펀드입니다 [1].")
    await ask(deps, "ETF가 뭐야?", level="expert")
    system = seen[0][0].content
    assert "설명 방식 (숙련)" in system and "반드시 지킬 것" in system


async def test_faq_search_starts_with_classification_once(
    deps: AgentDeps, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    original = faq.hybrid_search

    async def counting(session, embedder, query, **kw):
        calls.append(query)
        return await original(session, embedder, query, **kw)

    monkeypatch.setattr(faq, "hybrid_search", counting)
    st = await ask(deps, "분배금은 언제 받아?")
    assert st["intents"] == ["faq"] and st["sources"]
    assert len(calls) == 1  # 분류와 동시에 미리 검색한 결과를 FAQ 수집이 그대로 쓴다


async def test_retry_reruns_only_synthesis(deps: AgentDeps, fake_llm: FakeLLM) -> None:
    bad = "ETF는 원금이 보장됩니다. [1]"
    fake_llm.push("answer", bad, "ETF는 지수를 따라가도록 만든 펀드입니다. [1]")
    st = await ask(deps, "ETF가 뭐야?")
    assert st["verdict"] == "pass_after_retry"
    assert st["agents_called"].count("faq") == 1  # 자료 수집은 반복하지 않는다
    assert fake_llm.count("answer") == 2


async def test_faq_cache_skips_llm_on_repeat(deps: AgentDeps, fake_llm: FakeLLM) -> None:
    q = "추적오차가 뭐야?"
    first = await ask(deps, q, level="intermediate")
    assert first["verdict"] == "pass"
    calls = fake_llm.count("answer")
    second = await ask(deps, q, level="intermediate")
    assert fake_llm.count("answer") == calls  # 같은 수준·같은 질문은 캐시
    assert second["answer"] == first["answer"]
    assert "note:cache_hit" in second["guard_history"][0]
    await ask(deps, q, level="beginner")  # 수준이 다르면 새로 쓴다
    assert fake_llm.count("answer") == calls + 1


@pytest.mark.parametrize(
    ("query", "uses_previous"),
    [
        ("그럼 세금은?", True),
        ("그건 왜 그래?", True),
        ("세금은?", True),  # 짧은 질문
        ("ETF 분배금 지급 일정은 어떻게 되나요?", False),
    ],
)
def test_followup_search_query_includes_previous_question(query: str, uses_previous: bool) -> None:
    state = {
        "normalized": query,
        "history": [
            {"role": "user", "content": "레버리지 ETF가 뭐야?"},
            {"role": "assistant", "content": "레버리지 ETF는 …"},
        ],
    }
    got = faq.retrieval_query(state)  # type: ignore[arg-type]
    assert got.startswith("레버리지 ETF가 뭐야?") is uses_previous
    assert got.endswith(query)

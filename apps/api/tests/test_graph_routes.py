"""의도별 경로: etf_info, faq, disclosure, high_risk, recommendation, out_of_scope (P1-AG-02~06)."""

import pytest

from app.agents.graph import run_graph
from app.agents.state import AgentDeps
from app.llm.base import LLMError
from app.llm.fake import FakeLLM


async def ask(deps: AgentDeps, q: str, **kw):
    return await run_graph(deps, request_id="test", query=q, **kw)


async def test_etf_info_compare_uses_db_numbers_with_as_of(deps: AgentDeps) -> None:
    st = await ask(deps, "샘플 코스피200이랑 샘플 미국S&P500 비교해줘")
    assert st["intents"] == ["etf_info"]
    assert st["verdict"] == "pass"
    ans = st["answer"]
    assert "| 항목 | 샘플 코스피200 | 샘플 미국S&P500 |" in ans
    assert "36,180원" in ans and "21,940원" in ans  # data/samples/prices_daily.csv 최신 종가
    assert "기준일: 2026-11-11" in ans
    assert "원금 손실이 발생할 수 있습니다" in ans  # 필수 고지


async def test_etf_info_premium_discount(deps: AgentDeps) -> None:
    st = await ask(deps, "샘플 나스댁100 괴리율 알려줘")  # 오타
    assert st["intents"] == ["etf_info"]
    assert "0.20%" in st["answer"]
    assert [e.ticker for e in st["entities"]] == ["900040"]


async def test_etf_info_filter_search(deps: AgentDeps) -> None:
    st = await ask(deps, "총보수 0.1% 이하 해외 주식 ETF 찾아줘")
    assert "샘플 미국S&P500" in st["answer"]
    assert "샘플 미국채30년" not in st["answer"]  # 채권은 주식 분류가 아님
    assert "샘플 골드선물" not in st["answer"]  # 보수 0.68%


async def test_faq_answers_with_sources(deps: AgentDeps) -> None:
    st = await ask(deps, "괴리율이 뭐야?", level="beginner")
    assert st["intents"] == ["faq"]
    assert st["verdict"] == "pass"
    assert st["sources"] and st["sources"][0].title == "[샘플] 괴리율과 추적오차"
    assert "설명 수준" not in st["answer"]  # 수준은 프로필로 정하고 답변에 표시하지 않는다
    assert "[1]" not in st["answer"]  # 인용 번호는 출처 목록으로만


async def test_faq_says_unknown_without_evidence(deps: AgentDeps) -> None:
    st = await ask(deps, "ETF 운용역의 연봉 협상 절차는?")
    assert st["intents"] == ["faq"]
    assert "제공된 자료로는 답하기 어렵습니다" in st["answer"]


async def test_disclosure_summary_with_links(deps: AgentDeps) -> None:
    st = await ask(deps, "샘플 반도체 최근 공시 알려줘")
    assert st["intents"] == ["disclosure"]
    assert "https://example.com/disclosures/sample-0005" in st["answer"]
    assert all(s.url for s in st["sources"])


@pytest.mark.parametrize(
    ("q", "kind"),
    [
        ("샘플 코스피200 지금 사야 할까?", "buy_sell_timing"),
        ("샘플 나스닥100 내년 수익률 예측해줘", "return_forecast"),
        ("내 ETF 양도세 얼마 나와?", "personal_tax"),
        ("손실 난 거 보상해 주세요", "loss_compensation"),
    ],
)
async def test_high_risk_uses_template_without_generation(
    deps: AgentDeps, fake_llm: FakeLLM, q: str, kind: str
) -> None:
    st = await ask(deps, q)
    assert st["intents"] == ["high_risk"]
    assert st["verdict"] == "template"
    assert st["answer"].splitlines()[0].find("준법감시 승인 전 초안") >= 0
    assert st["agents_called"] == [f"template:high_risk/{kind}"]
    # 분류 외에는 LLM을 부르지 않는다
    assert {c["task"] for c in fake_llm.calls} <= {"classify"}


async def test_recommendation_phase3_notice(deps: AgentDeps) -> None:
    st = await ask(deps, "나한테 맞는 ETF 추천해줘")
    assert st["intents"] == ["recommendation"]
    assert "Phase 3" in st["answer"]


async def test_out_of_scope(deps: AgentDeps) -> None:
    st = await ask(deps, "오늘 점심 뭐 먹지")
    assert st["intents"] == ["out_of_scope"]
    assert st["verdict"] == "template"


async def test_multi_intent_runs_agents_in_parallel_and_merges(deps: AgentDeps) -> None:
    st = await ask(deps, "샘플 반도체랑 샘플 2차전지 비교하고 뉴스도 알려줘")
    assert st["intents"] == ["etf_info", "disclosure"]
    assert sorted(st["agents_called"]) == ["disclosure", "etf_info"]
    assert "### ETF 정보" in st["answer"] and "### 공시" in st["answer"]
    assert "공시 요약은 참고용" in st["answer"]  # 두 의도의 고지를 합친다


async def test_multiturn_carries_previous_etf(deps: AgentDeps) -> None:
    st = await ask(deps, "그럼 괴리율은?", context_tickers=["900010"])
    assert st["intents"] == ["etf_info"]
    assert "샘플 코스피200" in st["answer"]


async def test_llm_down_faq_returns_safe_answer(deps: AgentDeps, fake_llm: FakeLLM) -> None:
    fake_llm.push("classify", LLMError("down"))
    fake_llm.push("answer", LLMError("down"))
    st = await ask(deps, "분배금은 언제 받아?")
    assert st["verdict"] == "llm_unavailable"
    assert "문의" in st["answer"]


async def test_llm_down_etf_info_still_answers_from_db(deps: AgentDeps, fake_llm: FakeLLM) -> None:
    fake_llm.push("classify", LLMError("down"))
    fake_llm.push("answer", LLMError("down"))
    st = await ask(deps, "샘플 코스피200 시세")
    assert st["verdict"] == "pass"
    assert "36,180원" in st["answer"]


def test_strip_citations_and_cited_formats() -> None:
    from app.agents.faq import cited, strip_citations

    text = "괴리율은 가격 차이입니다 [1]. 확인이 필요합니다.[2][3]\n- 항목 [1, 4]"
    assert strip_citations(text) == "괴리율은 가격 차이입니다. 확인이 필요합니다.\n- 항목"
    assert cited(text, 4) == [1, 2, 3, 4]
    assert cited("인용 없음", 2) == [1, 2]

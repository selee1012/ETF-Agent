"""의도별 경로: etf_info, faq, disclosure, high_risk, recommendation, out_of_scope (P1-AG-02~06)."""

import pytest
from sqlalchemy import delete, update

from app.agents.graph import run_graph
from app.agents.state import AgentDeps
from app.llm.base import LLMError
from app.llm.fake import FakeLLM
from app.repositories import etf as etf_repo
from app.repositories.models import EtfMaster
from app.tools import price_lookup


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


async def test_compare_does_not_label_stale_price_with_newest_date(
    deps: AgentDeps, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 900010만 최신 시세가 하루 늦은 상황(거래 정지·수집 누락)
    async with deps.maker() as s:
        older_row, latest_row = await etf_repo.price_history(s, "900010", days=2)
    original = price_lookup.latest

    async def stale_latest(session, tickers):
        prices = await original(session, tickers)
        return {**prices, "900010": older_row}

    monkeypatch.setattr(price_lookup, "latest", stale_latest)
    st = await ask(deps, "샘플 코스피200이랑 샘플 미국S&P500 비교해줘")
    older, latest = older_row.trade_date.isoformat(), latest_row.trade_date.isoformat()
    ans = st["answer"]
    assert st["verdict"] == "pass"
    assert f"기준일: {latest} (일별 데이터)" not in ans  # 최신 날짜 하나로 뭉뚱그리지 않는다
    assert "기준일: 상품마다 다릅니다" in ans
    assert f"| 시세 기준일 | {older} | {latest} |" in ans
    assert st["sources"][0].location == f"기준일 {older} ~ {latest}"


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


async def test_condition_search_after_etf_turn_is_not_treated_as_followup(deps: AgentDeps) -> None:
    prior = {"context_tickers": ["900010"], "history": [{"role": "user", "content": "이전 질문"}]}
    st = await ask(deps, "총보수 0.1% 이하 해외 주식 ETF 찾아줘", **prior)
    assert st["intents"] == ["etf_info"]
    assert "검색 결과" in st["answer"] and "샘플 미국S&P500" in st["answer"]
    assert "샘플 코스피200 정보" not in st["answer"]  # 직전 ETF 정보표가 아니다

    followup = await ask(deps, "그럼 괴리율은?", **prior)  # 후속 질문은 그대로 직전 ETF를 잇는다
    assert "샘플 코스피200" in followup["answer"]


@pytest.mark.parametrize(
    ("query", "is_search"),
    [
        ("총보수 0.3% 초과 ETF 알려줘", True),  # '찾아줘'·'이하'가 없어도 조건 검색
        ("보수 0.2%보다 낮은 해외 주식 ETF 알려줘", True),
        ("이 상품 총보수 0.1% 이하 맞아?", False),  # 직전 상품을 가리키는 후속 질문
    ],
)
async def test_condition_search_detection(deps: AgentDeps, query: str, is_search: bool) -> None:
    prior = {"context_tickers": ["900010"], "history": [{"role": "user", "content": "이전 질문"}]}
    st = await ask(deps, query, **prior)
    assert st["intents"] == ["etf_info"]
    assert ("검색 결과" in st["answer"]) is is_search
    assert ("샘플 코스피200 정보" in st["answer"]) is not is_search


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("총보수 0.001% 이하 ETF 찾아줘", "조건(총보수 0.001% 이하)에 맞는 ETF가 없습니다."),
        ("ETF 목록 찾아줘", "'총보수 0.1% 이하 해외 주식 ETF'처럼 조건을 말씀해 주세요."),
    ],
)
async def test_no_result_notice_with_numbers_is_not_blocked(
    deps: AgentDeps, query: str, expected: str
) -> None:
    st = await ask(deps, query)
    assert st["intents"] == ["etf_info"]
    assert st["verdict"] == "pass"  # 안내 문구 속 수치가 '근거 없는 수치'로 반려되지 않는다
    assert expected in st["answer"]


async def test_faq_answers_with_sources(deps: AgentDeps) -> None:
    st = await ask(deps, "괴리율이 뭐야?", level="beginner")
    assert st["intents"] == ["faq"]
    assert st["verdict"] == "pass"
    assert st["sources"] and st["sources"][0].title == "[샘플] 괴리율과 추적오차"
    assert "설명 수준" not in st["answer"]  # 수준은 프로필로 정하고 답변에 표시하지 않는다
    assert "[1]" not in st["answer"]  # 인용 번호는 출처 목록으로만


async def test_faq_says_unknown_without_evidence(deps: AgentDeps) -> None:
    st = await ask(deps, "ETF 회사 직원의 연봉 협상 절차는?")
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


async def test_truncated_search_result_says_more_exist(deps: AgentDeps) -> None:
    """10건으로 자른 목록을 전체 건수처럼 표시하지 않는다(샘플 ETF 20개가 모두 일치하는 조건)."""
    st = await ask(deps, "총보수 5% 이하 ETF 찾아줘")
    assert "10건만 표시" in st["answer"] and "더 있습니다" in st["answer"]
    assert st["answer"].count("\n| 샘플") == 10

    small = await ask(deps, "총보수 0.05% 이하 ETF 찾아줘")
    assert "건만 표시" not in small["answer"]


async def test_search_discloses_products_it_could_not_check(deps: AgentDeps) -> None:
    """분류·총보수가 없는(외부 수집) 상품은 조건 검색에서 빠진다. 뺐다는 사실을 결과에 밝힌다."""
    rows = [
        {"ticker": "999999", "name": "수집된 미분류 ETF", "aliases": [], "source": "data_go_kr"},
        # 분류가 확인돼 '해외 주식'에서 이미 탈락한 상품. 총보수가 없어도 '확인 못 해 뺀 상품'이 아니다.
        {
            "ticker": "999998",
            "name": "보수 없는 국내 채권 ETF",
            "aliases": [],
            "source": "data_go_kr",
        },
    ]
    async with deps.maker() as s:
        await etf_repo.upsert_etfs(s, rows)
        await s.execute(
            update(EtfMaster).where(EtfMaster.ticker == "999998").values(category="국내 채권")
        )
        await s.commit()
    try:
        st = await ask(deps, "총보수 0.1% 이하 해외 주식 ETF 찾아줘")
        assert "수집된 미분류 ETF" not in st["answer"]
        assert (
            "조건(지역·분류·총보수) 가운데 정보가 없어 확인할 수 없는 항목이 있는 상품 1개"
            in st["answer"]
        )
        none = await ask(deps, "총보수 0.001% 이하 ETF 찾아줘")
        assert "맞는 ETF가 없습니다" in none["answer"]
        assert (
            "조건(총보수) 가운데 정보가 없어 확인할 수 없는 항목이 있는 상품 2개" in none["answer"]
        )
    finally:
        async with deps.maker() as s:
            await s.execute(delete(EtfMaster).where(EtfMaster.ticker.in_(["999999", "999998"])))
            await s.commit()


async def test_region_only_search_discloses_products_without_region(deps: AgentDeps) -> None:
    """'국내 ETF'는 분류에 지역 표기가 없는 상품(원자재·부동산 등 샘플 8개)을 뺀다. 전체 목록처럼 두지 않는다."""
    st = await ask(deps, "국내 ETF 찾아줘")
    assert "샘플 리츠부동산" not in st["answer"]
    assert "조건(지역) 가운데 정보가 없어 확인할 수 없는 항목이 있는 상품 8개" in st["answer"]


async def test_region_unverified_products_are_marked(deps: AgentDeps) -> None:
    """'국내 리츠'는 분류('부동산')에 지역 표기가 없어 국내 여부를 모른다. 조건을 만족한 것처럼 두지 않는다."""
    st = await ask(deps, "국내 리츠 ETF 목록 찾아줘")
    assert "샘플 리츠부동산" in st["answer"]
    assert "국내 상품인지 확인하지 못했습니다: 샘플 리츠부동산" in st["answer"]

    plain = await ask(
        deps, "총보수 0.1% 이하 해외 주식 ETF 찾아줘"
    )  # 분류에 지역이 있으면 표시 없음
    assert "확인하지 못했습니다" not in plain["answer"]

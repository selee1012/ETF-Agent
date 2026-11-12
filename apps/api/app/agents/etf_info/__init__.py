"""ETF 정보 에이전트: 검색·필터, 최신 시세·괴리율, 2~3개 비교. 숫자는 DB 값만, 기준일 표기. # P1-AG-03"""

from app.agents.common import retry_note
from app.agents.preprocess import load_catalog
from app.agents.prompts import load_text
from app.agents.state import AgentDeps, AgentResult, GraphState, Source
from app.llm.base import ChatMessage, LLMError
from app.logging import get_logger
from app.tools import compare, etf_search, price_lookup

log = get_logger(__name__)
NAME = "etf_info"


async def _summarize(deps: AgentDeps, state: GraphState, data: str) -> str:
    resp = await deps.llm.complete(
        [
            ChatMessage("system", load_text("system/etf_summary.md")),
            ChatMessage(
                "user", f"질문: {state['normalized']}\n\n[데이터]\n{data}{retry_note(state)}"
            ),
        ],
        task="etf_summary",
        intent=NAME,
        max_tokens=200,
    )
    return resp.text.strip()


async def run(state: GraphState, deps: AgentDeps) -> AgentResult:
    await deps.emit(NAME, "ETF 정보를 찾는 중")
    tickers = [e.ticker for e in state.get("entities") or []][:3]
    async with deps.maker() as session:
        if tickers:
            etfs = await price_lookup.etfs(session, tickers)
            prices = await price_lookup.latest(session, [e.ticker for e in etfs])
            as_of = compare.as_of(list(prices.values()))
            if len(etfs) >= 2:
                table = compare.compare_table(etfs, prices)
                title = f"{len(etfs)}개 상품 비교"
            else:
                table = compare.detail_table(etfs[0], prices.get(etfs[0].ticker))
                title = f"{etfs[0].name} 정보"
        else:
            catalog = await load_catalog(deps.maker)
            indexes = sorted({c.underlying_index for c in catalog if c.underlying_index})
            filters = etf_search.parse_filters(state["normalized"], indexes)
            if filters.is_empty():
                return AgentResult(
                    agent=NAME,
                    content=(
                        "질문에서 ETF 이름을 찾지 못했어요. 상품명이나 종목코드(6자리)를 알려 주시거나, "
                        "'총보수 0.1% 이하 해외 주식 ETF'처럼 조건을 말씀해 주세요."
                    ),
                )
            etfs = await etf_search.search(session, filters)
            if not etfs:
                return AgentResult(
                    agent=NAME, content=f"조건({filters.describe()})에 맞는 ETF가 없습니다."
                )
            table = compare.list_table(etfs)
            title = f"검색 결과({filters.describe()}) {len(etfs)}건"
            as_of = None

    as_of_line = f"기준일: {as_of.isoformat()} (일별 데이터)" if as_of else "출처: ETF 마스터(샘플)"
    data = f"**{title}**\n\n{table}\n\n{as_of_line}"
    summary = ""
    generated = False
    # 재생성 시도에서는 요약 문장 없이 DB 표만 내보낸다(수치 왜곡 가능성 제거).
    if not state.get("retry_feedback"):
        try:
            summary = await _summarize(deps, state, data)
            generated = bool(summary)
        except LLMError as e:  # 요약 없이 DB 표·목록만으로 답한다(LLM이 없어도 동작)
            log.info("etf_summary_failed", error=type(e).__name__)
    content = f"{summary}\n\n{data}" if summary else data
    source = Source(
        title="ETF 마스터·일별 시세 DB(샘플)",
        location=f"기준일 {as_of.isoformat()}" if as_of else None,
        kind="etf_data",
    )
    return AgentResult(
        agent=NAME,
        content=content,
        sources=[source],
        evidence=[data],
        retrieved_ids=[f"etf:{e.ticker}" for e in etfs],
        generated=generated,
    )

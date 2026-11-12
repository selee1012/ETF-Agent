"""ETF 정보 수집: 검색·필터, 최신 시세·괴리율, 2~3개 비교. 숫자는 DB 값만, 기준일 표기. # P1-AG-03

LLM을 부르지 않는다. DB 표는 화면에 그대로 붙고, 설명 문장은 답변 합성(compose)이 한 번에 쓴다.
"""

from app.agents.preprocess import load_catalog
from app.agents.state import AgentDeps, AgentResult, GraphState, Source
from app.tools import compare, etf_search, price_lookup

NAME = "etf_info"


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
                    found=False,
                    content=(
                        "질문에서 ETF 이름을 찾지 못했어요. 상품명이나 종목코드(6자리)를 알려 주시거나, "
                        "'총보수 0.1% 이하 해외 주식 ETF'처럼 조건을 말씀해 주세요."
                    ),
                )
            etfs = await etf_search.search(session, filters)
            if not etfs:
                return AgentResult(
                    agent=NAME,
                    found=False,
                    content=f"조건({filters.describe()})에 맞는 ETF가 없습니다.",
                )
            table = compare.list_table(etfs)
            title = f"검색 결과({filters.describe()}) {len(etfs)}건"
            as_of = None

    as_of_line = f"기준일: {as_of.isoformat()} (일별 데이터)" if as_of else "출처: ETF 마스터(샘플)"
    data = f"**{title}**\n\n{table}\n\n{as_of_line}"
    source = Source(
        title="ETF 마스터·일별 시세 DB(샘플)",
        location=f"기준일 {as_of.isoformat()}" if as_of else None,
        kind="etf_data",
    )
    return AgentResult(
        agent=NAME,
        content=data,
        context=f"[ETF 데이터] (DB 조회값, 화면에 표로 그대로 붙는다)\n{data}",
        sources=[source],
        evidence=[data],
        retrieved_ids=[f"etf:{e.ticker}" for e in etfs],
    )

"""공시 수집: 대상 ETF·구성종목 최근 공시 조회 → 목록 + 원문 링크. # P1-AG-05

LLM을 부르지 않는다. 목록은 화면에 그대로 붙고, 요약 문장은 답변 합성(compose)이 한 번에 쓴다.
"""

import re

from sqlalchemy import select

from app.agents.preprocess import compact
from app.agents.state import AgentDeps, AgentResult, GraphState, Source
from app.repositories.models import Disclosure
from app.tools import disclosure_lookup

NAME = "disclosure"


async def _constituents_in(session, text: str) -> list[str]:
    names = (
        await session.scalars(
            select(Disclosure.constituent_name)
            .where(Disclosure.constituent_name.is_not(None))
            .distinct()
        )
    ).all()
    q = compact(text)
    out = []
    for n in names:
        base = re.sub(r"\(.*?\)", "", n)
        if len(compact(base)) >= 2 and compact(base) in q:
            out.append(n)
    return out


async def run(state: GraphState, deps: AgentDeps) -> AgentResult:
    await deps.emit(NAME, "공시를 확인하는 중")
    tickers = [e.ticker for e in state.get("entities") or []]
    async with deps.maker() as session:
        constituents = await _constituents_in(session, state["normalized"])
        if not tickers and not constituents:
            return AgentResult(
                agent=NAME,
                found=False,
                content="어떤 ETF나 구성종목의 공시를 찾을지 알려 주세요. 예: '샘플 반도체 최근 공시'",
            )
        rows = await disclosure_lookup.recent(
            session, tickers=tickers, constituents=constituents, limit=5
        )
    if not rows:
        return AgentResult(agent=NAME, found=False, content="최근 등록된 관련 공시가 없습니다.")

    listing = disclosure_lookup.format_list(rows)
    return AgentResult(
        agent=NAME,
        content=f"**최근 공시 {len(rows)}건**\n\n{listing}",
        context=f"[공시] (최근 공시 {len(rows)}건, 화면에 목록으로 그대로 붙는다)\n{listing}",
        sources=[
            Source(title=d.title, location=d.disclosed_at.isoformat(), url=d.url, kind="disclosure")
            for d in rows
        ],
        evidence=[listing],
        retrieved_ids=[f"disclosure:{d.id}" for d in rows],
    )

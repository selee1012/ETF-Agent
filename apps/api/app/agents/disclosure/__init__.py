"""공시 요약 에이전트: 대상 ETF·구성종목 최근 공시 조회 → 요약 + 원문 링크. # P1-AG-05"""

import re

from sqlalchemy import select

from app.agents.common import retry_note
from app.agents.preprocess import compact
from app.agents.prompts import load_text
from app.agents.state import AgentDeps, AgentResult, GraphState, Source
from app.llm.base import ChatMessage, LLMError
from app.logging import get_logger
from app.repositories.models import Disclosure
from app.tools import disclosure_lookup

log = get_logger(__name__)
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
                content="어떤 ETF나 구성종목의 공시를 찾을지 알려 주세요. 예: '샘플 반도체 최근 공시'",
            )
        rows = await disclosure_lookup.recent(
            session, tickers=tickers, constituents=constituents, limit=5
        )
    if not rows:
        return AgentResult(agent=NAME, content="최근 등록된 관련 공시가 없습니다.")

    listing = disclosure_lookup.format_list(rows)
    summary, generated = "", False
    if not state.get("retry_feedback"):
        try:
            resp = await deps.llm.complete(
                [
                    ChatMessage("system", load_text("system/disclosure_summary.md")),
                    ChatMessage("user", f"[공시]\n{listing}{retry_note(state)}"),
                ],
                task="disclosure_summary",
                intent=NAME,
                max_tokens=250,
            )
            summary, generated = resp.text.strip(), bool(resp.text.strip())
        except LLMError as e:  # 요약 없이 DB 표·목록만으로 답한다(LLM이 없어도 동작)
            log.info("disclosure_summary_failed", error=type(e).__name__)
    head = f"최근 공시 {len(rows)}건"
    content = f"{summary}\n\n**{head}**\n\n{listing}" if summary else f"**{head}**\n\n{listing}"
    return AgentResult(
        agent=NAME,
        content=content,
        sources=[
            Source(title=d.title, location=d.disclosed_at.isoformat(), url=d.url, kind="disclosure")
            for d in rows
        ],
        evidence=[listing],
        retrieved_ids=[f"disclosure:{d.id}" for d in rows],
        generated=generated,
    )

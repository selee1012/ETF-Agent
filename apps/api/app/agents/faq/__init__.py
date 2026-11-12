"""지식·FAQ 에이전트: 하이브리드 검색 근거만으로 수준별 설명, 출처 표기. # P1-AG-04"""

import re
from dataclasses import replace

from app import cache
from app.agents import general
from app.agents.common import LEVEL_LABEL, history_text, retry_note
from app.agents.prompts import load_text
from app.agents.state import AgentDeps, AgentResult, GraphState, Intent, Level, Source
from app.llm.base import ChatMessage
from app.rag.retriever import RetrievedChunk, hybrid_search

NAME = "faq"
NO_ANSWER = "제공된 자료로는 답하기 어렵습니다."
_CITE = re.compile(r"\[(\d{1,2})\]")


def _evidence_block(chunks: list[RetrievedChunk]) -> str:
    return "\n".join(
        f"[근거 {i}] ({c.title} · {c.location})\n{c.content}" for i, c in enumerate(chunks, 1)
    )


def _cited(text: str, n: int) -> list[int]:
    nums = sorted({int(m) for m in _CITE.findall(text) if 1 <= int(m) <= n})
    return nums or list(range(1, n + 1))


async def _no_evidence(
    state: GraphState, deps: AgentDeps, *, generated: bool = False
) -> AgentResult:
    """근거 없음. 일반 대화 모드(로컬 전용)이고 FAQ 단독 질문이면 모델 일반 지식으로 답한다."""
    if deps.settings.general_chat_enabled and state.get("intents") == [Intent.FAQ]:
        text = await general.answer(state, deps, intent=NAME)
        if text:
            return AgentResult(
                agent=NAME,
                content=f"{text}\n\n{general.UNGROUNDED_NOTE}",
                generated=True,
                grounded=False,
            )
    return AgentResult(agent=NAME, content=NO_ANSWER, generated=generated)


async def run(state: GraphState, deps: AgentDeps) -> AgentResult:
    await deps.emit(NAME, "관련 자료를 찾는 중")
    s = deps.settings
    level = state.get("level") or Level.BEGINNER
    use_cache = not state.get("history") and not state.get("retry_feedback")
    key = cache.faq_key(level, state["normalized"])
    if use_cache and (hit := cache.faq_cache().get(key)) is not None:
        return replace(hit, cached=True)

    async with deps.maker() as session:
        chunks = await hybrid_search(
            session,
            deps.embedder,
            state["normalized"],
            k=s.rag_top_k,
            vector_weight=s.rag_vector_weight,
        )
    chunks = [c for c in chunks if c.score >= s.rag_min_score]
    if not chunks:
        return await _no_evidence(state, deps)

    hist = history_text(state)
    user = (
        (f"[이전 대화]\n{hist}\n\n" if hist else "")
        + f"[질문]\n{state['normalized']}\n\n{_evidence_block(chunks)}"
        + retry_note(state)
    )
    resp = await deps.llm.complete(
        [
            ChatMessage("system", load_text(f"system/faq_{level}.md")),
            ChatMessage("user", user),
        ],
        task="faq_answer",
        intent=NAME,
    )
    answer = resp.text.strip() or NO_ANSWER
    if NO_ANSWER in answer and len(answer) < len(NO_ANSWER) + 20:
        return await _no_evidence(state, deps, generated=True)
    used = [chunks[i - 1] for i in _cited(answer, len(chunks))]
    sources = [
        Source(
            title=c.title,
            location=c.location,
            kind="document",
            doc_id=str(c.document_id),
        )
        for c in used
    ]
    # 같은 문서·위치 중복 제거
    uniq = list({(x.title, x.location): x for x in sources}.values())
    result = AgentResult(
        agent=NAME,
        content=f"{answer}\n\n_설명 수준: {LEVEL_LABEL.get(level, level)}_",
        sources=uniq,
        evidence=[c.content for c in chunks],
        retrieved_ids=[f"doc:{c.document_id}#chunk:{c.chunk_id}" for c in chunks],
        generated=True,
        cache_key=key if use_cache else None,
    )
    return result

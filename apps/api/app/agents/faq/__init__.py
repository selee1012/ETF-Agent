"""지식·FAQ 수집: 하이브리드 검색으로 근거 문서를 찾는다. 설명 문장은 답변 합성(compose)이 쓴다. # P1-AG-04

- 검색은 오케스트레이터가 의도 분류와 동시에 미리 시작하고(prefetched_chunks), 여기서는 결과만 쓴다.
- 후속 질문('그럼 세금은?')은 직전 사용자 질문을 붙여 검색해 맥락을 잃지 않게 한다.
- 같은 수준·같은 질문(이전 대화 없음)은 가드를 통과한 답변 캐시를 쓴다(키 faq:{level}:{hash}).
"""

import re
from dataclasses import replace

from app import cache
from app.agents.state import AgentDeps, AgentResult, GraphState, Intent, Level, Source
from app.rag.retriever import RetrievedChunk, hybrid_search

NAME = "faq"
NO_ANSWER = "제공된 자료로는 답하기 어렵습니다."
# 인용 표시: [1], [1][2], [1, 2] 모두 허용. 출처 목록을 고르는 데만 쓰고 본문에서는 지운다.
_CITE = re.compile(r"\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]")
_CITE_STRIP = re.compile(r"[ \t]*\[\d{1,2}(?:\s*,\s*\d{1,2})*\]")
# 앞 대화에 기대는 짧은 후속 질문 표지
_FOLLOWUP = re.compile(
    r"^(그럼|그러면|그럴|그건|그거|그게|그것|이건|이거|이게|저건|아까|방금|위에|앞에서|그래서|왜)"
)
_SHORT_QUERY = 12
# 스스로 주제를 가진 뜻풀이 질문('ETF가 뭐야?', '괴리율이란?'). 짧아도 앞 대화의 후속 질문이 아니다.
# 직전 질문을 붙여 검색하면 앞 주제의 문서가 섞여, 묻지 않은 상품 이야기로 답이 흘러간다.
_DEFINITION = re.compile(r"(뭐야|뭐예요|뭐에요|뭔가요|뭐지|뭔지|무엇|이란|란\?|뜻|의미|정의)")


def cited(text: str, n: int) -> list[int]:
    """본문에서 인용한 근거 번호(1..n). 인용이 없으면 전부."""
    found = {int(x) for group in _CITE.findall(text) for x in re.findall(r"\d+", group)}
    nums = sorted(x for x in found if 1 <= x <= n)
    return nums or list(range(1, n + 1))


def strip_citations(text: str) -> str:
    """화면용: 본문의 [n] 인용 표시를 지운다(출처는 출처 목록으로 따로 보여 준다)."""
    return _CITE_STRIP.sub("", text).strip()


def retrieval_query(state: GraphState) -> str:
    """검색용 질의. 짧거나 앞 대화를 가리키는 후속 질문이면 직전 사용자 질문을 붙인다."""
    q = state["normalized"]
    prev = next(
        (
            str(h.get("content", ""))
            for h in reversed(state.get("history") or [])
            if h.get("role") == "user"
        ),
        "",
    )
    if not prev:
        return q
    refers_back = bool(_FOLLOWUP.search(q))
    short = len(q) <= _SHORT_QUERY and not _DEFINITION.search(q)
    return f"{prev[:200]} {q}" if refers_back or short else q


def cache_key(state: GraphState) -> str | None:
    """이전 대화가 없고 재생성 중이 아닐 때만 캐시를 쓴다."""
    if state.get("history") or state.get("retry_feedback"):
        return None
    return cache.faq_key(state.get("level") or Level.BEGINNER, state["normalized"])


def cached_answer(state: GraphState) -> AgentResult | None:
    key = cache_key(state)
    hit = cache.faq_cache().get(key) if key else None
    return replace(hit, cached=True) if hit is not None else None


async def retrieve(state: GraphState, deps: AgentDeps) -> list[RetrievedChunk]:
    s = deps.settings
    async with deps.maker() as session:
        chunks = await hybrid_search(
            session,
            deps.embedder,
            retrieval_query(state),
            k=s.rag_top_k,
            vector_weight=s.rag_vector_weight,
        )
    return [c for c in chunks if c.score >= s.rag_min_score]


def evidence_block(chunks: list[RetrievedChunk]) -> str:
    return "\n".join(
        f"[근거 {i}] ({c.title} · {c.location})\n{c.content}" for i, c in enumerate(chunks, 1)
    )


async def run(state: GraphState, deps: AgentDeps) -> AgentResult:
    await deps.emit(NAME, "관련 자료를 찾는 중")
    # 캐시에는 완성된 답변만 있고 근거 블록이 없다. FAQ 단독 질문일 때만 그대로 쓸 수 있고,
    # 다른 의도와 함께면 합성 단계가 근거를 보고 새로 써야 하므로 문서를 검색한다.
    if state.get("intents") == [Intent.FAQ] and (hit := cached_answer(state)) is not None:
        return hit
    chunks = state.get("prefetched_chunks")
    if chunks is None:
        chunks = await retrieve(state, deps)
    if not chunks:
        return AgentResult(agent=NAME, content="", found=False)
    return AgentResult(
        agent=NAME,
        content="",
        context=evidence_block(chunks),
        # [근거 N] 순서와 같은 순서. 합성 단계가 인용 번호로 골라 쓴다.
        sources=[
            Source(title=c.title, location=c.location, kind="document", doc_id=str(c.document_id))
            for c in chunks
        ],
        evidence=[c.content for c in chunks],
        retrieved_ids=[f"doc:{c.document_id}#chunk:{c.chunk_id}" for c in chunks],
        cache_key=cache_key(state),
    )

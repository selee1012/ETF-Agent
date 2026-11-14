"""하이브리드 검색: pgvector 코사인 + pg_trgm word_similarity 가중합. # P1-AG-04

질문 임베딩(외부 API)과 키워드 후보 조회(DB)는 서로 기다릴 필요가 없어 동시에 보낸다.
"""

import asyncio
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import Embedder
from app.rag.embedder import embed_query
from app.repositories import documents as doc_repo


@dataclass(slots=True)
class RetrievedChunk:
    chunk_id: int
    document_id: int
    title: str
    location: str  # 출처 위치(섹션명 또는 p.N)
    content: str
    score: float
    vector_score: float
    text_score: float


def _location(meta: dict) -> str:
    if meta.get("page"):
        return f"p.{meta['page']}"
    if meta.get("heading"):
        return str(meta["heading"])
    return f"#{meta.get('chunk_index', 0) + 1}"


async def hybrid_search(
    session: AsyncSession,
    embedder: Embedder,
    query: str,
    *,
    k: int = 4,
    vector_weight: float = 0.7,
    candidates: int = 20,
) -> list[RetrievedChunk]:
    # 같은 세션을 동시에 두 쿼리가 쓰지 않도록 DB 조회는 하나씩, 임베딩 호출만 겹친다.
    # 한쪽이 실패해도 다른 쪽이 끝날 때까지 기다린다. 임베딩이 먼저 실패했을 때 바로 예외를 올리면
    # 호출 측이 쿼리가 도는 세션을 닫으려다 다른 예외(LLMError가 아닌)가 나서 그래프 전체가 죽는다.
    qvec, trg = await asyncio.gather(
        embed_query(embedder, query),
        doc_repo.trgm_candidates(session, query, candidates),
        return_exceptions=True,
    )
    for result in (qvec, trg):
        if isinstance(result, BaseException):
            raise result
    vec = await doc_repo.vector_candidates(session, qvec, candidates)
    ids = set(vec) | set(trg)
    scored = sorted(
        (
            (vector_weight * max(vec.get(i, 0.0), 0.0) + (1 - vector_weight) * trg.get(i, 0.0), i)
            for i in ids
        ),
        reverse=True,
    )[:k]
    rows = await doc_repo.load_chunks(session, [i for _, i in scored])
    out = []
    for score, i in scored:
        # 후보를 고른 뒤 문서가 다시 적재되면 그 청크는 지워지고 새 id로 들어간다. 없어진 후보는 건너뛴다
        # (여기서 KeyError가 나면 선행 검색이 실패해 질문 전체가 안전 답변으로 끝난다).
        if i not in rows:
            continue
        chunk, title = rows[i]
        out.append(
            RetrievedChunk(
                chunk_id=i,
                document_id=chunk.document_id,
                title=title,
                location=_location({**chunk.meta, "chunk_index": chunk.chunk_index}),
                content=chunk.content,
                score=round(score, 4),
                vector_score=round(vec.get(i, 0.0), 4),
                text_score=round(trg.get(i, 0.0), 4),
            )
        )
    return out

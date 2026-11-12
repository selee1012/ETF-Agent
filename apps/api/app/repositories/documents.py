"""문서·청크 적재와 하이브리드 검색용 쿼리. # P1-DA-03 P1-AG-04"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import Chunk, Document


async def get_document_by_uri(session: AsyncSession, source_uri: str) -> Document | None:
    return await session.scalar(select(Document).where(Document.source_uri == source_uri))


async def replace_document(
    session: AsyncSession,
    *,
    source_uri: str,
    title: str,
    doc_type: str,
    content_hash: str,
    embedding_model: str,
    meta: dict[str, Any],
    chunks: Sequence[tuple[str, list[float], dict[str, Any]]],
) -> Document:
    """같은 source_uri 문서가 있으면 청크를 모두 갈아끼운다(재-ingest 갱신)."""
    doc = await get_document_by_uri(session, source_uri)
    if doc is None:
        doc = Document(source_uri=source_uri)
        session.add(doc)
    doc.title = title
    doc.doc_type = doc_type
    doc.content_hash = content_hash
    doc.embedding_model = embedding_model
    doc.meta = meta
    await session.flush()
    await session.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    session.add_all(
        Chunk(document_id=doc.id, chunk_index=i, content=c, embedding=e, meta=m)
        for i, (c, e, m) in enumerate(chunks)
    )
    await session.flush()
    return doc


async def list_documents(session: AsyncSession, limit: int = 100) -> list[dict[str, Any]]:
    stmt = (
        select(Document, func.count(Chunk.id))
        .outerjoin(Chunk, Chunk.document_id == Document.id)
        .group_by(Document.id)
        .order_by(Document.updated_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": d.id,
            "title": d.title,
            "source_uri": d.source_uri,
            "doc_type": d.doc_type,
            "embedding_model": d.embedding_model,
            "chunks": n,
            "updated_at": d.updated_at.isoformat(),
        }
        for d, n in (await session.execute(stmt)).all()
    ]


_VECTOR_SQL = text(
    """
    SELECT c.id, 1 - (c.embedding <=> CAST(:qvec AS vector)) AS score
    FROM chunks c
    ORDER BY c.embedding <=> CAST(:qvec AS vector)
    LIMIT :n
    """
)

_TRGM_SQL = text(
    """
    SELECT c.id, word_similarity(:q, c.content) AS score
    FROM chunks c
    WHERE :q <% c.content
    ORDER BY score DESC
    LIMIT :n
    """
)


async def vector_candidates(
    session: AsyncSession, qvec: Sequence[float], n: int
) -> dict[int, float]:
    vec = "[" + ",".join(f"{x:.6f}" for x in qvec) + "]"
    rows = (await session.execute(_VECTOR_SQL, {"qvec": vec, "n": n})).all()
    return {int(r.id): float(r.score) for r in rows}


async def trgm_candidates(session: AsyncSession, query: str, n: int) -> dict[int, float]:
    # word_similarity 기본 임계값(0.6)은 한국어 질의에 너무 높아 세션 단위로 낮춘다.
    await session.execute(text("SET LOCAL pg_trgm.word_similarity_threshold = 0.2"))
    rows = (await session.execute(_TRGM_SQL, {"q": query, "n": n})).all()
    return {int(r.id): float(r.score) for r in rows}


async def load_chunks(session: AsyncSession, ids: Sequence[int]) -> dict[int, tuple[Chunk, str]]:
    if not ids:
        return {}
    stmt = select(Chunk, Document.title).join(Document).where(Chunk.id.in_(ids))
    return {c.id: (c, title) for c, title in (await session.execute(stmt)).all()}

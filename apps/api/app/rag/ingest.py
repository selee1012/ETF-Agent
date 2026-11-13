"""문서 적재: PDF·마크다운 → 청킹 → 임베딩 → chunks. 같은 문서를 다시 넣으면 갱신한다. # P1-DA-03"""

import hashlib
from dataclasses import dataclass
from pathlib import PurePath

from sqlalchemy.ext.asyncio import AsyncSession

from app import cache
from app.llm.base import Embedder
from app.rag.chunker import Section, chunk_sections, parse_markdown, parse_plain_pages
from app.rag.embedder import embed_texts
from app.repositories import documents as doc_repo

SUPPORTED_SUFFIXES = (".md", ".markdown", ".txt", ".pdf")


@dataclass(slots=True)
class IngestResult:
    document_id: int
    title: str
    source_uri: str
    status: str  # created | updated | unchanged
    chunks: int


def _parse(filename: str, data: bytes) -> tuple[str | None, list[Section]]:
    suffix = PurePath(filename).suffix.lower()
    if suffix == ".pdf":
        import pymupdf  # PDF 파서(공급자 SDK 아님)

        try:
            with pymupdf.open(stream=data, filetype="pdf") as pdf:
                pages = [page.get_text("text") for page in pdf]
                title = (pdf.metadata or {}).get("title") or None
        except (
            RuntimeError,
            ValueError,
        ) as e:  # 손상·암호화된 PDF(pymupdf 예외는 RuntimeError 계열)
            raise ValueError("PDF를 읽을 수 없습니다(손상됐거나 암호가 걸린 파일)") from e
        return title, parse_plain_pages(pages)
    if suffix in (".md", ".markdown", ".txt"):
        return parse_markdown(data.decode("utf-8", errors="replace"))
    raise ValueError(f"지원하지 않는 파일 형식: {suffix} (지원: {', '.join(SUPPORTED_SUFFIXES)})")


async def ingest_bytes(
    session: AsyncSession,
    embedder: Embedder,
    *,
    source_uri: str,
    filename: str,
    data: bytes,
    doc_type: str = "faq",
    force: bool = False,
) -> IngestResult:
    content_hash = hashlib.sha256(data).hexdigest()
    existing = await doc_repo.get_document_by_uri(session, source_uri)
    if (
        existing is not None
        and not force
        and existing.content_hash == content_hash
        and existing.embedding_model == embedder.model
    ):
        return IngestResult(existing.id, existing.title, source_uri, "unchanged", -1)

    title, sections = _parse(filename, data)
    title = title or PurePath(filename).stem
    pieces = chunk_sections(sections)
    if not pieces:
        raise ValueError("본문이 비어 있어 적재할 청크가 없습니다")
    # 임베딩 입력에는 문서명을 붙여 짧은 청크의 문맥을 보강한다.
    vectors = await embed_texts(embedder, [f"{title}\n{p.content}" for p in pieces])
    doc = await doc_repo.replace_document(
        session,
        source_uri=source_uri,
        title=title,
        doc_type=doc_type,
        content_hash=content_hash,
        embedding_model=embedder.model,
        meta={"filename": PurePath(filename).name},
        chunks=[(p.content, v, p.meta) for p, v in zip(pieces, vectors, strict=True)],
    )
    await session.commit()
    cache.faq_cache().clear()  # 검색 결과가 바뀌었으니 FAQ 답변 캐시를 비운다
    status = "created" if existing is None else "updated"
    return IngestResult(doc.id, title, source_uri, status, len(pieces))

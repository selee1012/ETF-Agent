"""ingest: 문단 청킹(겹침), 재적재 시 갱신 (P1-DA-03)."""

import pytest

from app.db import get_sessionmaker
from app.llm.fake import FakeEmbedder
from app.rag.chunker import chunk_sections, parse_markdown
from app.rag.ingest import ingest_bytes
from app.repositories import documents as doc_repo
from app.settings import REPO_ROOT
from jobs.ingest import resolve_target


def test_markdown_chunking_with_overlap() -> None:
    para = "가" * 300
    md = f"# 제목\n\n## 섹션\n\n{para}1\n\n{para}2\n\n{para}3\n"
    title, sections = parse_markdown(md)
    chunks = chunk_sections(sections, max_chars=700, overlap_chars=100)
    assert title == "제목"
    assert len(chunks) == 2
    assert chunks[0].meta["heading"] == "섹션"
    # 두 번째 청크는 직전 청크 마지막 문단 끝 100자로 시작한다(겹침)
    assert chunks[1].content.split("\n")[1] == (para + "2")[-100:]


async def test_reingest_updates_document() -> None:
    emb = FakeEmbedder(dim=1024)
    async with get_sessionmaker()() as s:
        r1 = await ingest_bytes(
            s, emb, source_uri="test://doc.md", filename="doc.md", data=b"# A\n\n## x\n\nfirst"
        )
    async with get_sessionmaker()() as s:
        r2 = await ingest_bytes(
            s,
            emb,
            source_uri="test://doc.md",
            filename="doc.md",
            data=b"# A\n\n## x\n\nsecond\n\n## y\n\nthird",
        )
    assert (r1.status, r2.status) == ("created", "updated")
    assert r1.document_id == r2.document_id
    async with get_sessionmaker()() as s:
        doc = await doc_repo.get_document_by_uri(s, "test://doc.md")
        rows = await doc_repo.load_chunks(s, [c for c in range(1, 10_000)])
    contents = [c.content for c, _ in rows.values() if c.document_id == doc.id]
    assert sorted(contents) == ["## x\nsecond", "## y\nthird"]


def test_resolve_target_falls_back_to_repo_root() -> None:
    """실행 위치(apps/api)에 없는 레포 기준 경로도 찾는다(make ingest ARGS="data/samples/docs")."""
    assert resolve_target("data/samples/docs") == REPO_ROOT / "data/samples/docs"


def test_resolve_target_rejects_missing_path() -> None:
    with pytest.raises(FileNotFoundError):
        resolve_target("no/such/dir")

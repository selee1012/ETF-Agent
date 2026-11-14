"""ingest: 문단 청킹(겹침), 재적재 시 갱신 (P1-DA-03)."""

from pathlib import Path

import pytest

from app.db import get_sessionmaker
from app.llm.fake import FakeEmbedder
from app.rag.chunker import chunk_sections, parse_markdown
from app.rag.ingest import ingest_bytes
from app.repositories import documents as doc_repo
from app.settings import REPO_ROOT
from jobs.ingest import resolve_target
from jobs.ingest.__main__ import main as ingest_cli


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


def test_resolve_target_prefers_repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """레포 기준 경로를 실행 위치와 무관하게 찾는다(make ingest ARGS="data/samples/docs")."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("# cwd")
    assert resolve_target("data/samples/docs") == REPO_ROOT / "data/samples/docs"
    assert resolve_target("README.md") == REPO_ROOT / "README.md"  # 실행 위치의 같은 이름보다 먼저
    (tmp_path / "only-here.md").write_text("# x")
    assert resolve_target("only-here.md") == Path("only-here.md")
    # 실행 위치를 명시하면 레포 루트로 바꾸지 않는다(`.`이 레포 전체가 되지 않게).
    assert resolve_target(".") == Path(".")
    assert resolve_target("./README.md") == Path("README.md")


def test_resolve_target_rejects_missing_path() -> None:
    with pytest.raises(FileNotFoundError):
        resolve_target("no/such/dir")


@pytest.mark.parametrize("kind", ["missing", "unsupported_file", "empty_dir", "unreadable"])
async def test_cli_fails_when_nothing_to_ingest(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """없는 경로, 지원하지 않는 파일, 문서가 없는 디렉터리, 읽을 수 없는 문서는 1로 끝난다."""
    (tmp_path / "notes.toml").write_text("x = 1")
    (tmp_path / "empty").mkdir()
    (tmp_path / "broken.pdf").write_bytes(b"not a pdf")
    target = {
        "missing": tmp_path / "nope",
        "unsupported_file": tmp_path / "notes.toml",
        "empty_dir": tmp_path / "empty",
        "unreadable": tmp_path / "broken.pdf",
    }[kind]
    monkeypatch.setattr("sys.argv", ["jobs.ingest", str(target)])
    assert await ingest_cli() == 1
    out = capsys.readouterr().out
    assert out
    if kind == "unreadable":
        assert "broken.pdf" in out

"""문서 파싱·청킹·임베딩 적재 배치. 핵심 로직은 app.rag.ingest(운영 화면 업로드와 공유). # P1-DA-03"""

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.llm.base import Embedder
from app.rag.ingest import SUPPORTED_SUFFIXES, IngestResult, ingest_bytes
from app.settings import REPO_ROOT


def source_uri_for(path: Path) -> str:
    """레포 안 파일은 레포 기준 상대 경로를 키로 쓴다(호스트·컨테이너에서 같은 값)."""
    path = path.resolve()
    try:
        return f"file://{path.relative_to(REPO_ROOT).as_posix()}"
    except ValueError:
        return f"file://{path.as_posix()}"


def collect_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    return sorted(p for p in target.rglob("*") if p.suffix.lower() in SUPPORTED_SUFFIXES)


async def ingest_paths(
    maker: async_sessionmaker[AsyncSession],
    embedder: Embedder,
    target: Path,
    *,
    doc_type: str = "faq",
    force: bool = False,
) -> list[IngestResult]:
    results = []
    for path in collect_files(target):
        async with maker() as session:
            results.append(
                await ingest_bytes(
                    session,
                    embedder,
                    source_uri=source_uri_for(path),
                    filename=path.name,
                    data=path.read_bytes(),
                    doc_type=doc_type,
                    force=force,
                )
            )
    return results

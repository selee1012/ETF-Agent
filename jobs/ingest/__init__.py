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


def resolve_target(raw: str) -> Path:
    """없는 상대 경로는 레포 루트 기준으로 다시 찾는다. 그래도 없으면 FileNotFoundError.

    make ingest는 컨테이너의 apps/api에서 실행되므로 `data/samples/docs` 같은 레포 기준 경로가
    그대로는 없는 경로가 된다. 없는 경로는 빈 목록이 되어 아무것도 적재하지 않고 성공으로 끝났다.
    """
    path = Path(raw)
    if not path.exists() and not path.is_absolute():
        path = REPO_ROOT / path
    if not path.exists():
        raise FileNotFoundError(raw)
    return path


def collect_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target] if target.suffix.lower() in SUPPORTED_SUFFIXES else []
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

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
    """상대 경로는 레포 루트 기준으로 먼저 찾고, 없으면 실행 위치 기준으로 찾는다. 없으면 FileNotFoundError.

    make ingest는 컨테이너의 apps/api에서 실행되므로 `data/samples/docs` 같은 레포 기준 경로가
    그대로는 없는 경로가 된다. 없는 경로는 빈 목록이 되어 아무것도 적재하지 않고 성공으로 끝났다.
    """
    path = Path(raw)
    candidates = [path] if path.is_absolute() else [REPO_ROOT / path, path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(raw)


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
            try:
                result = await ingest_bytes(
                    session,
                    embedder,
                    source_uri=source_uri_for(path),
                    filename=path.name,
                    data=path.read_bytes(),
                    doc_type=doc_type,
                    force=force,
                )
            except ValueError as e:  # 읽을 수 없는 문서. 어느 파일인지 알 수 있게 경로를 붙인다.
                raise ValueError(f"{path}: {e}") from e
            results.append(result)
    return results

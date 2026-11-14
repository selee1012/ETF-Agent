"""CLI: python -m jobs.ingest [경로...] [--force] [--doc-type faq]"""

import argparse
import asyncio

from app.db import dispose_engine, get_sessionmaker
from app.llm import build_embedder
from app.llm.base import LLMError
from app.rag.ingest import SUPPORTED_SUFFIXES
from app.settings import REPO_ROOT, get_settings
from jobs.ingest import collect_files, ingest_paths, resolve_target


async def main() -> int:
    parser = argparse.ArgumentParser(description="문서 ingest (PDF·마크다운)")
    parser.add_argument("paths", nargs="*", default=[str(REPO_ROOT / "data/samples/docs")])
    parser.add_argument("--force", action="store_true", help="내용이 같아도 다시 임베딩")
    parser.add_argument("--doc-type", default="faq")
    args = parser.parse_args()

    try:
        targets = [resolve_target(p) for p in args.paths]
    except FileNotFoundError as e:
        print(
            f"경로를 찾을 수 없습니다: {e}\n"
            f"→ 레포 루트({REPO_ROOT}) 기준 상대 경로나 컨테이너 안의 절대 경로를 주세요."
        )
        return 1
    empty = [str(t) for t in targets if not collect_files(t)]
    if empty:
        print(
            f"적재할 문서가 없습니다: {', '.join(empty)}\n→ 지원 형식: {', '.join(SUPPORTED_SUFFIXES)}"
        )
        return 1

    settings = get_settings()
    embedder = build_embedder(settings)
    print(f"임베딩: provider={settings.embedding_provider} model={embedder.model}")
    try:
        for target in targets:
            for r in await ingest_paths(
                get_sessionmaker(), embedder, target, doc_type=args.doc_type, force=args.force
            ):
                n = "-" if r.chunks < 0 else r.chunks
                print(f"  [{r.status:9}] {r.title}  chunks={n}  ({r.source_uri})")
    except LLMError as e:
        print(
            f"임베딩 실패: {e}\n→ LLM_API_KEY·EMBEDDING_MODEL({settings.embedding_model})·네트워크를 확인하세요."
        )
        return 1
    except ValueError as e:  # 읽을 수 없는 문서(손상된 PDF, 빈 본문 등). 이 파일에서 멈춘다.
        print(f"문서를 적재하지 못해 중단합니다: {e}")
        return 1
    finally:
        await dispose_engine()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

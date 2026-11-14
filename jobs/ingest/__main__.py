"""CLI: python -m jobs.ingest [경로...] [--force] [--doc-type faq]"""

import argparse
import asyncio

from app.db import dispose_engine, get_sessionmaker
from app.llm import build_embedder
from app.llm.base import LLMError
from app.settings import REPO_ROOT, get_settings
from jobs.ingest import ingest_paths, resolve_target


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
    finally:
        await dispose_engine()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

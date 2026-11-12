"""CLI: python -m ml.eval [--sets data/eval-sets] [--out report.json] [--with-judge]"""

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from app.agents.state import AgentDeps
from app.db import dispose_engine, get_sessionmaker
from app.llm import build_embedder, build_llm
from app.settings import get_settings
from ml.eval import DEFAULT_SETS, render_table, run_all


async def main() -> None:
    parser = argparse.ArgumentParser(description="ETF Agent 오프라인 평가")
    parser.add_argument("--sets", type=Path, default=DEFAULT_SETS)
    parser.add_argument("--out", type=Path, help="JSON 리포트 저장 경로")
    parser.add_argument("--with-judge", action="store_true", help="위반 탐지에 검증 모델도 사용")
    args = parser.parse_args()

    s = get_settings()
    deps = AgentDeps(
        settings=s, llm=build_llm(s), embedder=build_embedder(s), maker=get_sessionmaker()
    )
    print(f"LLM={s.llm_provider.value}:{deps.llm.model}  embedding={deps.embedder.model}")
    try:
        rep = await run_all(deps, args.sets, with_judge=args.with_judge)
    finally:
        await dispose_engine()
    report = {"llm": deps.llm.model, "embedding": deps.embedder.model, **asdict(rep)}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    print(render_table(rep))
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"저장: {args.out}")


if __name__ == "__main__":
    asyncio.run(main())

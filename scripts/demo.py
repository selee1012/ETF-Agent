"""대표 질문 6개(비교, 괴리율, 입문 설명, 공시, 매수 시점, 추천)를 그래프로 실행해 답변·가드 판정을 출력한다.

실행: make demo  (LLM_API_KEY 필요) / make demo PROVIDER=fake
"""

import asyncio
import sys
import time
import uuid
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "apps" / "api")]

from app.agents.graph import run_graph  # noqa: E402
from app.agents.state import AgentDeps  # noqa: E402
from app.db import dispose_engine, get_sessionmaker  # noqa: E402
from app.llm import build_embedder, build_llm  # noqa: E402
from app.settings import get_settings  # noqa: E402

QUESTIONS = [
    ("비교", "샘플 코스피200이랑 샘플 미국S&P500 비교해줘", None),
    ("괴리율", "샘플 미국나스닥100 괴리율 알려줘", None),
    ("입문 설명", "ETF 괴리율이 뭐야? 쉽게 설명해줘", "beginner"),
    ("공시", "샘플 반도체 최근 공시 요약해줘", None),
    ("매수 시점", "샘플 코스피200 지금 사야 할까?", None),
    ("추천 요청", "나한테 맞는 ETF 추천해줘", None),
]


async def main() -> None:
    s = get_settings()
    llm = build_llm(s)

    async def emit(stage: str, message: str) -> None:
        print(f"    · {message}")

    deps = AgentDeps(
        settings=s, llm=llm, embedder=build_embedder(s), maker=get_sessionmaker(), emit=emit
    )
    print(
        f"LLM: {s.llm_provider.value} / {llm.model} @ {s.llm_base_url}  (judge: {s.judge_model_name})"
    )
    try:
        for i, (label, q, level) in enumerate(QUESTIONS, 1):
            print("\n" + "=" * 80 + f"\n[{i}/6] {label}: {q}")
            t0 = time.perf_counter()
            st = await run_graph(
                deps, request_id=f"demo-{uuid.uuid4().hex[:8]}", query=q, level=level
            )
            dt = time.perf_counter() - t0
            reasons = [r for rs in st.get("guard_history", []) for r in rs]
            print(
                f"  의도={st.get('intents')} ({st.get('intent_source', '-')})  "
                f"가드={st.get('verdict')}  사유={reasons or '-'}  {dt:.1f}s"
            )
            print("-" * 80)
            print(st.get("answer", ""))
            srcs = st.get("sources") or []
            if srcs:
                print(
                    "  출처: " + "; ".join(f"{x.title}({x.location or x.url or '-'})" for x in srcs)
                )
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())

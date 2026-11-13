"""하이브리드 검색: 임베딩 실패가 DB 세션을 깨뜨리지 않는다 (P1-AG-04)."""

import pytest
from sqlalchemy import text

from app.agents.graph import run_graph
from app.agents.state import AgentDeps
from app.llm.base import Embedder, LLMError
from app.rag.retriever import hybrid_search


class DownEmbedder(Embedder):
    model, dim = "down", 1024

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise LLMError("embedding down")


async def test_embedding_failure_leaves_session_usable(deps: AgentDeps) -> None:
    async with deps.maker() as s:
        with pytest.raises(LLMError):
            await hybrid_search(s, DownEmbedder(), "괴리율이 뭐야?")
        assert await s.scalar(text("select 1")) == 1  # 진행 중인 쿼리를 남기지 않는다


async def test_embedding_failure_does_not_crash_graph(deps: AgentDeps) -> None:
    deps.embedder = DownEmbedder()
    st = await run_graph(deps, request_id="t", query="샘플 코스피200 괴리율이 뭐야?")
    assert st["verdict"] in ("pass", "llm_unavailable")  # 예외로 끝나지 않는다

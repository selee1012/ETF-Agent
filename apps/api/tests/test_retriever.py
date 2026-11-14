"""하이브리드 검색: 임베딩 실패가 DB 세션을 깨뜨리지 않는다 (P1-AG-04)."""

import pytest
from sqlalchemy import text

from app.agents.graph import run_graph
from app.agents.state import AgentDeps
from app.llm.base import Embedder, LLMError
from app.rag.retriever import hybrid_search
from app.repositories import documents as doc_repo


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


async def test_chunk_deleted_during_search_is_skipped(
    deps: AgentDeps, monkeypatch: pytest.MonkeyPatch
) -> None:
    """후보를 고른 뒤 재적재로 청크가 사라져도 검색이 KeyError로 끝나지 않는다."""
    real = doc_repo.load_chunks

    async def load_without_first(session, ids):  # 가장 높은 후보가 그사이 삭제된 상황
        rows = await real(session, ids)
        rows.pop(ids[0], None)
        return rows

    async with deps.maker() as s:
        before = await hybrid_search(s, deps.embedder, "괴리율이 뭐야?")
        monkeypatch.setattr(doc_repo, "load_chunks", load_without_first)
        after = await hybrid_search(s, deps.embedder, "괴리율이 뭐야?")
    assert [c.chunk_id for c in after] == [c.chunk_id for c in before][1:]

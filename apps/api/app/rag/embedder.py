"""임베딩 배치 호출. 모델 교체(bge-m3 → Kanana-2 등)는 EMBEDDING_MODEL/EMBEDDING_DIM으로만 한다."""

from app.llm.base import Embedder

BATCH_SIZE = 16


async def embed_texts(embedder: Embedder, texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        out.extend(await embedder.embed(texts[i : i + BATCH_SIZE]))
    return out


async def embed_query(embedder: Embedder, text: str) -> list[float]:
    return (await embedder.embed([text]))[0]

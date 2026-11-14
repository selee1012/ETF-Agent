"""운영 화면 API: 트레이스·피드백 조회, 문서 업로드 → 저장 → ingest, 검색 확인. role=admin만. # P1-API-04"""

import asyncio
import uuid
from datetime import datetime
from pathlib import PurePath
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import text

from app import cache
from app.deps import AdminDep, ContainerDep
from app.llm.base import LLMError
from app.rag.ingest import SUPPORTED_SUFFIXES, ingest_bytes
from app.rag.retriever import hybrid_search
from app.repositories import conversations as conv_repo
from app.repositories import documents as doc_repo
from app.repositories import traces as trace_repo

router = APIRouter(prefix="/admin", tags=["admin"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# 같은 파일 이름의 업로드를 한 번에 하나씩 처리하는 잠금. 트랜잭션이 끝나면(커밋·롤백) 풀린다.
# DB 잠금이라 API 인스턴스가 여러 개여도 통한다. 다른 이름의 업로드는 서로 기다리지 않는다.
# 적재와 같은 세션(연결 하나)에서 잡는다. 잠금용 연결을 따로 잡으면 동시 업로드가 풀을 잠금용으로
# 다 채우고 적재용 연결을 서로 기다리다 모두 시간 초과로 끝난다.
_UPLOAD_LOCK = text("SELECT pg_advisory_xact_lock(hashtext(:key))")


class TraceOut(BaseModel):
    """마스킹된 정보만: 질의 원문은 테이블에 없다."""

    request_id: str
    user_id: uuid.UUID | None
    intent: str | None
    agents: list[str]
    retrieved_doc_ids: list[str]
    guard_verdict: str | None
    guard_reasons: list[str]
    latency_ms: int | None
    model: str | None
    fallback_used: bool
    created_at: datetime


class TracePage(BaseModel):
    items: list[TraceOut]
    total: int


class FeedbackOut(BaseModel):
    id: int
    message_id: uuid.UUID | None
    request_id: str | None
    user_id: uuid.UUID | None
    kind: str
    correction_text: str | None
    created_at: datetime


@router.get("/traces", response_model=TracePage)
async def traces(
    _: AdminDep,
    c: ContainerDep,
    intent: str | None = None,
    verdict: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TracePage:
    async with c.maker() as session:
        rows, total = await trace_repo.list_traces(
            session, intent=intent, verdict=verdict, limit=limit, offset=offset
        )
    return TracePage(
        items=[TraceOut.model_validate(r, from_attributes=True) for r in rows], total=total
    )


@router.get("/feedback", response_model=list[FeedbackOut])
async def feedback(
    _: AdminDep,
    c: ContainerDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[FeedbackOut]:
    async with c.maker() as session:
        rows = await conv_repo.list_feedback(session, limit=limit, offset=offset)
    return [FeedbackOut.model_validate(r, from_attributes=True) for r in rows]


@router.get("/documents")
async def documents(_: AdminDep, c: ContainerDep) -> list[dict]:
    async with c.maker() as session:
        return await doc_repo.list_documents(session)


@router.post("/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    _: AdminDep,
    c: ContainerDep,
    file: Annotated[UploadFile, File()],
    doc_type: Annotated[str, Form()] = "faq",
) -> dict:
    """업로드 → 저장(storage 어댑터) → ingest. 같은 파일명은 같은 키라 다시 올리면 갱신된다."""
    filename = PurePath(file.filename or "upload.md").name
    if PurePath(filename).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"지원 형식: {', '.join(SUPPORTED_SUFFIXES)}",
        )
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "10MB 이하 파일만 올릴 수 있습니다")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "빈 파일입니다")
    # 적재가 실패하거나 중단되면 저장소를 원래대로 되돌린다. 그러지 않으면 같은 이름의 정상 문서 원본이
    # 반영되지 않은 파일로 덮인 채 남아 저장소와 색인(DB 청크)이 어긋난다.
    key = f"uploads/{filename}"
    async with c.maker() as session:
        # 원본 덮어쓰기 → 적재 → 커밋(실패 시 복원)이 끝날 때까지 같은 이름의 다른 업로드를 기다리게 한다.
        # 겹치면 한쪽의 복원이 다른 쪽의 성공한 원본을 덮거나, 저장 순서와 DB 반영 순서가 달라진다.
        await session.execute(_UPLOAD_LOCK, {"key": key})
        try:
            previous = await c.storage.get(key) if await c.storage.exists(key) else None
            stored = await c.storage.put(key, data, file.content_type)
        except NotImplementedError as e:  # 스텁 저장소(STORAGE_PROVIDER=supabase·azure_blob)
            raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, str(e)) from e

        async def restore() -> None:
            if previous is None:
                await c.storage.delete(key)
            else:
                await c.storage.put(key, previous, file.content_type)

        try:
            result = await ingest_bytes(
                session,
                c.embedder,
                source_uri=stored.uri,
                filename=filename,
                data=data,
                doc_type=doc_type,
                commit=False,
            )
            await session.commit()  # 잠금도 여기서 풀린다
        except BaseException as e:
            # 요청 취소(서버 종료·연결 끊김)는 Exception이 아니다. 그때도 되돌려야 한다.
            # 되돌리는 도중에 다시 취소돼도 끝까지 하도록 shield로 감싼다(아직 잠금을 쥐고 있다).
            await asyncio.shield(restore())
            if isinstance(e, ValueError):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
            if isinstance(e, LLMError):
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"임베딩 실패: {e}") from e
            raise
    if result.status != "unchanged":
        cache.faq_cache().clear()  # 검색 결과가 바뀌었으니 FAQ 답변 캐시를 비운다
    return {
        "document_id": result.document_id,
        "title": result.title,
        "source_uri": result.source_uri,
        "status": result.status,
        "chunks": result.chunks,
        "size": stored.size,
    }


@router.get("/search")
async def search(
    _: AdminDep, c: ContainerDep, q: Annotated[str, Query(min_length=1, max_length=200)]
) -> list[dict]:
    """업로드한 문서가 검색에 반영됐는지 확인용."""
    try:
        async with c.maker() as session:
            rows = await hybrid_search(
                session,
                c.embedder,
                q,
                k=c.settings.rag_top_k,
                vector_weight=c.settings.rag_vector_weight,
            )
    except LLMError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"임베딩 실패: {e}") from e
    return [
        {
            "chunk_id": r.chunk_id,
            "document_id": r.document_id,
            "title": r.title,
            "location": r.location,
            "score": r.score,
            "vector_score": r.vector_score,
            "text_score": r.text_score,
            "preview": r.content[:200],
        }
        for r in rows
    ]

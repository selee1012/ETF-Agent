"""대화 이력: 목록·상세·삭제. # P1-API-02

삭제는 본인 대화만 가능하고 메시지까지 함께 지운다(되돌릴 수 없다).
traces에는 질의 원문이 없으므로 운영 지표용으로 남긴다.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from app.deps import ContainerDep, PrincipalDep
from app.repositories import conversations as conv_repo

router = APIRouter(prefix="/history", tags=["history"])


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    request_id: str | None
    intent: str | None
    guard_verdict: str | None
    sources: list[dict[str, Any]]
    created_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class DeletedOut(BaseModel):
    deleted: int


@router.get("", response_model=list[ConversationOut])
async def list_history(c: ContainerDep, principal: PrincipalDep) -> list[ConversationOut]:
    async with c.maker() as session:
        rows = await conv_repo.list_conversations(session, principal.user_id)
    return [ConversationOut.model_validate(r, from_attributes=True) for r in rows]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_history(
    conversation_id: uuid.UUID, c: ContainerDep, principal: PrincipalDep
) -> ConversationDetail:
    async with c.maker() as session:
        found = await conv_repo.get_conversation_messages(
            session, principal.user_id, conversation_id
        )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "대화를 찾을 수 없습니다")
    conv, messages = found
    return ConversationDetail(
        **ConversationOut.model_validate(conv, from_attributes=True).model_dump(),
        messages=[MessageOut.model_validate(m, from_attributes=True) for m in messages],
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_history(
    conversation_id: uuid.UUID, c: ContainerDep, principal: PrincipalDep
) -> Response:
    async with c.maker() as session:
        deleted = await conv_repo.delete_conversation(session, principal.user_id, conversation_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "대화를 찾을 수 없습니다")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("", response_model=DeletedOut)
async def delete_all_history(c: ContainerDep, principal: PrincipalDep) -> DeletedOut:
    async with c.maker() as session:
        n = await conv_repo.delete_all_conversations(session, principal.user_id)
    return DeletedOut(deleted=n)

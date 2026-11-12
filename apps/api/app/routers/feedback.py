"""피드백(좋아요·싫어요·정정). 정정 텍스트는 mask_pii() 후 저장. # P1-API-03"""

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from app.deps import ContainerDep, PrincipalDep
from app.repositories import conversations as conv_repo
from app.repositories.models import Conversation

router = APIRouter(tags=["feedback"])


class FeedbackRequest(BaseModel):
    kind: Literal["like", "dislike", "correction"]
    message_id: uuid.UUID | None = None
    request_id: str | None = Field(default=None, max_length=64)
    correction_text: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _check(self) -> FeedbackRequest:
        if self.message_id is None and not self.request_id:
            raise ValueError("message_id 또는 request_id가 필요합니다")
        if self.kind == "correction" and not (self.correction_text or "").strip():
            raise ValueError("정정 피드백에는 correction_text가 필요합니다")
        return self


class FeedbackOut(BaseModel):
    id: int
    kind: str


@router.post("/feedback", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
async def create_feedback(
    body: FeedbackRequest, c: ContainerDep, principal: PrincipalDep
) -> FeedbackOut:
    async with c.maker() as session:
        request_id = body.request_id
        if body.message_id is not None:
            msg = await conv_repo.get_message(session, body.message_id)
            conv = await session.get(Conversation, msg.conversation_id) if msg else None
            if msg is None or conv is None or conv.user_id != principal.user_id:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "메시지를 찾을 수 없습니다")
            request_id = request_id or msg.request_id
        fb = await conv_repo.add_feedback(
            session,
            user_id=principal.user_id,
            kind=body.kind,
            message_id=body.message_id,
            request_id=request_id,
            correction_text=body.correction_text if body.kind == "correction" else None,
        )
    return FeedbackOut(id=fb.id, kind=fb.kind)

"""사용자·대화·메시지·피드백. 저장되는 텍스트는 모두 mask_pii()를 거친 값이다. # P1-API-02 P1-API-03"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.privacy import mask_pii
from app.repositories.models import Conversation, Feedback, Message, User


async def upsert_user(session: AsyncSession, email: str, role: str) -> User:
    stmt = (
        insert(User)
        .values(id=uuid.uuid4(), email=email, role=role)
        .on_conflict_do_update(index_elements=["email"], set_={"role": role})
        .returning(User)
    )
    user = (await session.execute(stmt)).scalar_one()
    await session.commit()
    return user


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def set_user_level(session: AsyncSession, user_id: uuid.UUID, level: str) -> User | None:
    user = await session.get(User, user_id)
    if user is None:
        return None
    user.level = level
    await session.commit()
    return user


async def get_or_create_conversation(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID | None, first_query: str
) -> Conversation:
    if conversation_id is not None:
        conv = await session.get(Conversation, conversation_id)
        if conv is not None and conv.user_id == user_id:
            return conv
    title = mask_pii(first_query).strip()
    conv = Conversation(user_id=user_id, title=(title[:40] or "새 대화"))
    session.add(conv)
    await session.flush()
    return conv


async def recent_messages(
    session: AsyncSession, conversation_id: uuid.UUID, turns: int
) -> list[Message]:
    if turns <= 0:
        return []
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(turns * 2)
    )
    return list(reversed((await session.scalars(stmt)).all()))


async def add_message(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    role: str,
    content: str,
    request_id: str | None = None,
    intent: str | None = None,
    guard_verdict: str | None = None,
    sources: Sequence[dict[str, Any]] = (),
    meta: dict[str, Any] | None = None,
) -> Message:
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=mask_pii(content),  # 공통 규칙 4
        request_id=request_id,
        intent=intent,
        guard_verdict=guard_verdict,
        sources=list(sources),
        meta=meta or {},
    )
    session.add(msg)
    await session.flush()
    return msg


async def touch_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> None:
    """대화 목록 정렬 기준(updated_at)을 지금으로 올린다.

    ID로 직접 UPDATE 한다. 다른 세션에서 읽은 Conversation 객체는 이 세션에 붙어 있지 않아
    속성만 바꿔서는 저장되지 않는다.
    """
    await session.execute(
        update(Conversation).where(Conversation.id == conversation_id).values(updated_at=func.now())
    )


async def list_conversations(session: AsyncSession, user_id: uuid.UUID) -> list[Conversation]:
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
        .limit(100)
    )
    return list((await session.scalars(stmt)).all())


async def get_conversation_messages(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> tuple[Conversation, list[Message]] | None:
    conv = await session.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user_id:
        return None
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    return conv, list((await session.scalars(stmt)).all())


async def delete_conversation(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> bool:
    """본인 대화만 지운다. 메시지는 FK CASCADE로 함께 지워지고, 피드백은 message_id가 NULL이 된다."""
    result = await session.execute(
        delete(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )
    await session.commit()
    return result.rowcount > 0


async def delete_all_conversations(session: AsyncSession, user_id: uuid.UUID) -> int:
    result = await session.execute(delete(Conversation).where(Conversation.user_id == user_id))
    await session.commit()
    return result.rowcount


async def add_feedback(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    message_id: uuid.UUID | None,
    request_id: str | None,
    correction_text: str | None,
) -> Feedback:
    fb = Feedback(
        user_id=user_id,
        kind=kind,
        message_id=message_id,
        request_id=request_id,
        correction_text=mask_pii(correction_text) if correction_text else None,
    )
    session.add(fb)
    await session.commit()
    return fb


async def get_message(session: AsyncSession, message_id: uuid.UUID) -> Message | None:
    return await session.get(Message, message_id)


async def owns_request(session: AsyncSession, user_id: uuid.UUID, request_id: str) -> bool:
    """이 request_id의 메시지가 사용자의 대화에 있는지."""
    stmt = (
        select(Message.id)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(Message.request_id == request_id, Conversation.user_id == user_id)
        .limit(1)
    )
    return (await session.scalar(stmt)) is not None


async def list_feedback(session: AsyncSession, limit: int = 100, offset: int = 0) -> list[Feedback]:
    stmt = select(Feedback).order_by(Feedback.created_at.desc()).limit(limit).offset(offset)
    return list((await session.scalars(stmt)).all())

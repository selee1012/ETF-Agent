"""대화 삭제: 본인 대화만, 메시지까지 함께 지워지고 피드백은 남는다. # P1-API-02"""

import uuid

from httpx import AsyncClient
from sqlalchemy import func, select

from app.db import get_sessionmaker
from app.repositories.models import Feedback, Message
from tests.conftest import login
from tests.sse import parse_sse


async def _chat(client: AsyncClient, headers: dict, message: str = "분배금이 뭐야?") -> dict:
    resp = await client.post("/chat", json={"message": message}, headers=headers)
    assert resp.status_code == 200, resp.text
    return parse_sse(resp.text)[-1][1]


async def _message_count(conversation_id: str) -> int:
    async with get_sessionmaker()() as session:
        return await session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == uuid.UUID(conversation_id))
        )


async def test_delete_one_conversation(client: AsyncClient, user_headers: dict) -> None:
    done = await _chat(client, user_headers)
    conv_id = done["conversation_id"]
    fb = await client.post(
        "/feedback", json={"message_id": done["message_id"], "kind": "like"}, headers=user_headers
    )
    assert fb.status_code in (200, 201), fb.text
    assert await _message_count(conv_id) == 2

    resp = await client.delete(f"/history/{conv_id}", headers=user_headers)
    assert resp.status_code == 204
    assert await _message_count(conv_id) == 0
    assert (await client.get(f"/history/{conv_id}", headers=user_headers)).status_code == 404
    assert (await client.delete(f"/history/{conv_id}", headers=user_headers)).status_code == 404

    async with get_sessionmaker()() as session:  # 피드백은 운영 지표로 남고 메시지 연결만 끊긴다
        kept = await session.scalar(
            select(Feedback).where(Feedback.request_id == done["request_id"])
        )
    assert kept is not None and kept.message_id is None


async def test_cannot_delete_others_conversation(client: AsyncClient, user_headers: dict) -> None:
    conv_id = (await _chat(client, user_headers))["conversation_id"]
    other = await login(client, f"other-{uuid.uuid4().hex[:8]}@local.test")
    assert (await client.delete(f"/history/{conv_id}", headers=other)).status_code == 404
    assert (await client.delete(f"/history/{conv_id}")).status_code == 401
    assert await _message_count(conv_id) == 2


async def test_delete_all_only_mine(client: AsyncClient, user_headers: dict) -> None:
    await _chat(client, user_headers)
    await _chat(client, user_headers, "괴리율이 뭐야?")
    other = await login(client, f"other-{uuid.uuid4().hex[:8]}@local.test")
    other_conv = (await _chat(client, other))["conversation_id"]

    resp = await client.delete("/history", headers=user_headers)
    assert resp.status_code == 200 and resp.json() == {"deleted": 2}
    assert (await client.get("/history", headers=user_headers)).json() == []
    assert await _message_count(other_conv) == 2

"""프로필 설명 수준: 처음엔 비어 있고, PATCH /auth/me로 고르면 채팅이 그 수준으로 답한다. # P1-API-01"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.db import get_sessionmaker
from app.repositories.models import Message
from tests.conftest import login
from tests.sse import parse_sse


async def _user_message_level(conversation_id: str) -> str:
    async with get_sessionmaker()() as session:
        msg = await session.scalar(
            select(Message)
            .where(Message.conversation_id == uuid.UUID(conversation_id), Message.role == "user")
            .order_by(Message.created_at.desc())
        )
    assert msg is not None
    return msg.meta["level"]


async def _chat(client: AsyncClient, headers: dict, **body) -> str:
    resp = await client.post("/chat", json={"message": "ETF가 뭐야?", **body}, headers=headers)
    assert resp.status_code == 200, resp.text
    return parse_sse(resp.text)[-1][1]["conversation_id"]


async def test_level_empty_until_chosen(client: AsyncClient) -> None:
    email = f"new-{uuid.uuid4().hex[:8]}@local.test"
    resp = await client.post("/auth/dev-login", json={"email": email})
    assert resp.json()["user"]["level"] is None  # 웹이 온보딩을 띄우는 신호
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me = (await client.get("/auth/me", headers=headers)).json()
    assert me["email"] == email and me["level"] is None


async def test_patch_level_persists_and_survives_relogin(client: AsyncClient) -> None:
    email = f"lv-{uuid.uuid4().hex[:8]}@local.test"
    headers = await login(client, email)
    resp = await client.patch("/auth/me", json={"level": "expert"}, headers=headers)
    assert resp.status_code == 200 and resp.json()["level"] == "expert"
    assert (await client.get("/auth/me", headers=headers)).json()["level"] == "expert"
    again = await client.post("/auth/dev-login", json={"email": email})
    assert again.json()["user"]["level"] == "expert"  # 다시 로그인해도 유지


async def test_patch_level_validation_and_auth(client: AsyncClient, user_headers: dict) -> None:
    bad = await client.patch("/auth/me", json={"level": "guru"}, headers=user_headers)
    assert bad.status_code == 422
    assert (await client.patch("/auth/me", json={"level": "expert"})).status_code == 401


async def test_chat_uses_profile_level(client: AsyncClient, user_headers: dict) -> None:
    conv = await _chat(client, user_headers)
    assert await _user_message_level(conv) == "beginner"  # 고르기 전 기본값

    await client.patch("/auth/me", json={"level": "intermediate"}, headers=user_headers)
    conv = await _chat(client, user_headers)
    assert await _user_message_level(conv) == "intermediate"

    conv = await _chat(client, user_headers, level="expert")  # 요청에 주면 그 값이 우선
    assert await _user_message_level(conv) == "expert"

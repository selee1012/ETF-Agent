"""채팅 SSE·이력·피드백·인증 (P1-API-01~03)."""

import asyncio
import time
import uuid

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.auth import Principal
from app.db import get_sessionmaker
from app.llm.base import ChatMessage, LLMResponse
from app.llm.fake import FakeLLM
from app.repositories.models import Feedback, Message
from app.services.chat import ChatRequest, stream_chat
from tests.sse import answer_text, parse_sse


async def chat(client: AsyncClient, headers: dict, message: str, **body) -> list:
    resp = await client.post("/chat", json={"message": message, **body}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["x-accel-buffering"] == "no"
    return parse_sse(resp.text)


async def test_requires_login(client: AsyncClient) -> None:
    resp = await client.post("/chat", json={"message": "안녕"})
    assert resp.status_code == 401


async def test_sse_event_order(client: AsyncClient, user_headers: dict) -> None:
    events = await chat(client, user_headers, "샘플 코스피200 괴리율 알려줘")
    names = [e for e, _ in events]
    assert names[0] == "status"
    assert events[0][1]["message"] == "질문을 이해하는 중"
    first_token = names.index("token")
    assert set(names[:first_token]) == {"status"}
    assert "ETF 정보를 찾는 중" in [d["message"] for e, d in events if e == "status"]
    assert names[-2:] == ["sources", "done"]
    assert set(names[first_token:-2]) == {"token"}
    done = events[-1][1]
    assert done["intents"] == ["etf_info"]
    assert done["guard"]["verdict"] == "pass"
    assert uuid.UUID(done["message_id"]) and done["request_id"]
    assert "0.23%" in answer_text(events)


class SlowLLM(FakeLLM):
    async def complete(self, messages: list[ChatMessage], **kw) -> LLMResponse:
        await asyncio.sleep(0.3)
        return await super().complete(messages, **kw)


async def test_first_status_is_sent_immediately(app: FastAPI, user_headers: dict) -> None:
    c = app.state.container
    c.llm = SlowLLM()
    me = await c.auth.authenticate(user_headers["Authorization"].split()[1])
    gen = stream_chat(c, Principal(me.user_id, me.email, me.role), ChatRequest(message="분배금?"))
    t0 = time.perf_counter()
    first = await anext(gen)
    first_latency = time.perf_counter() - t0
    rest = [chunk async for chunk in gen]
    total = time.perf_counter() - t0
    assert first.startswith("event: status")
    assert first_latency < 0.1  # DB·LLM 작업 전에 바로 나간다
    assert total > 0.3  # 이후 처리는 느린 LLM을 기다린다
    assert rest[-1].startswith("event: done")


async def test_multiturn_history_and_conversation(client: AsyncClient, user_headers: dict) -> None:
    first = await chat(client, user_headers, "샘플 미국나스닥100 시세 알려줘")
    conv_id = first[-1][1]["conversation_id"]
    second = await chat(client, user_headers, "그럼 괴리율은?", conversation_id=conv_id)
    assert second[-1][1]["conversation_id"] == conv_id
    assert "샘플 미국나스닥100" in answer_text(second)  # 직전 턴 ETF를 이어 쓴다

    convs = (await client.get("/history", headers=user_headers)).json()
    assert [c["id"] for c in convs] == [conv_id]
    detail = (await client.get(f"/history/{conv_id}", headers=user_headers)).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]
    assert detail["messages"][1]["sources"]

    other = await client.post("/auth/dev-login", json={"email": "other@local.test"})
    other_h = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert (await client.get(f"/history/{conv_id}", headers=other_h)).status_code == 404


async def test_feedback_like_and_correction(client: AsyncClient, user_headers: dict) -> None:
    events = await chat(client, user_headers, "괴리율이 뭐야?")
    mid = events[-1][1]["message_id"]
    r1 = await client.post(
        "/feedback", json={"kind": "like", "message_id": mid}, headers=user_headers
    )
    r2 = await client.post(
        "/feedback",
        json={"kind": "correction", "message_id": mid, "correction_text": "제 번호 010-9999-8888"},
        headers=user_headers,
    )
    bad = await client.post(
        "/feedback", json={"kind": "correction", "message_id": mid}, headers=user_headers
    )
    assert (r1.status_code, r2.status_code, bad.status_code) == (201, 201, 422)
    async with get_sessionmaker()() as s:
        fb = await s.get(Feedback, r2.json()["id"])
    assert fb.correction_text == "제 번호 [PHONE]"
    assert fb.request_id == events[-1][1]["request_id"]


async def test_user_message_is_masked(client: AsyncClient, user_headers: dict) -> None:
    events = await chat(client, user_headers, "제 메일 hong@example.com 인데 괴리율이 뭐야?")
    rid = events[-1][1]["request_id"]
    async with get_sessionmaker()() as s:
        rows = (await s.scalars(select(Message).where(Message.request_id == rid))).all()
    user_msg = next(m for m in rows if m.role == "user")
    assert "hong@example.com" not in user_msg.content and "[EMAIL]" in user_msg.content


async def test_dev_login_admin_role(client: AsyncClient) -> None:
    resp = await client.post("/auth/dev-login", json={"email": "admin@local.test"})
    assert resp.json()["user"]["role"] == "admin"
    resp = await client.post("/auth/dev-login", json={"email": "not-an-email"})
    assert resp.status_code == 422

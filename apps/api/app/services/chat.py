"""채팅 SSE 서비스. # P1-API-01

이벤트 순서: status(요청 즉시) → status… → token… → sources → done
- 답변 저장·트레이스는 토큰 전송 전에 끝낸다(클라이언트가 중간에 끊어도 기록이 남는다).
- 토큰은 가드를 통과한 최종 답변을 잘게 나눠 보낸다(검증 전 문장이 화면에 노출되지 않도록).
- 질의 원문은 메모리에서만 쓰고, DB에는 mask_pii() 값만, 트레이스·로그에는 남기지 않는다.
"""

import asyncio
import json
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import run_graph
from app.agents.guard.templates import safe_answer
from app.agents.state import AgentDeps, GraphState, Level
from app.auth import Principal
from app.container import Container
from app.logging import get_logger
from app.observability import TraceRecord
from app.observability.metrics import observe_chat
from app.repositories import conversations as conv_repo

log = get_logger(__name__)

_TOKEN_RE = re.compile(r"\S+\s*|\s+")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: uuid.UUID | None = None
    # 없으면 사용자 프로필의 설명 수준, 프로필도 비어 있으면 입문 # P1-API-01
    level: Level | None = None


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def split_tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def _public_reasons(reasons: list[str]) -> list[str]:
    """done 이벤트에는 사유 코드만 보낸다(수치·문구 원문 제외)."""
    return sorted({r.split(":", 2)[0] + ":" + r.split(":", 2)[1] for r in reasons if ":" in r})


async def _profile_level(session: AsyncSession, principal: Principal) -> Level:
    user = await conv_repo.get_user(session, principal.user_id)
    return Level(user.level) if user is not None and user.level else Level.BEGINNER


async def stream_chat(c: Container, principal: Principal, req: ChatRequest) -> AsyncIterator[str]:
    request_id = uuid.uuid4().hex
    started = time.perf_counter()
    # 요청 즉시 첫 status (DB·LLM 작업 전)
    yield sse("status", {"stage": "preprocess", "message": "질문을 이해하는 중"})

    queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

    async def emit(stage: str, message: str) -> None:
        await queue.put(("status", {"stage": stage, "message": message}))

    async with c.maker() as session:
        conv = await conv_repo.get_or_create_conversation(
            session, principal.user_id, req.conversation_id, req.message
        )
        history_rows = await conv_repo.recent_messages(session, conv.id, c.settings.history_turns)
        level = req.level or await _profile_level(session, principal)
        await conv_repo.add_message(
            session, conversation_id=conv.id, role="user", content=req.message,
            request_id=request_id, meta={"level": level.value},
        )  # fmt: skip
        await session.commit()
    history = [{"role": m.role, "content": m.content, "intent": m.intent} for m in history_rows]
    context_tickers: list[str] = []
    for m in reversed(history_rows):
        if m.role == "assistant" and m.meta.get("tickers"):
            context_tickers = list(m.meta["tickers"])
            break

    deps = AgentDeps(settings=c.settings, llm=c.llm, embedder=c.embedder, maker=c.maker, emit=emit)
    task = asyncio.create_task(
        run_graph(
            deps,
            request_id=request_id,
            query=req.message,
            level=level.value,
            history=history,
            context_tickers=context_tickers,
        )
    )
    state: GraphState | None = None
    try:
        while not task.done() or not queue.empty():
            getter = asyncio.ensure_future(queue.get())
            done, _ = await asyncio.wait({task, getter}, return_when=asyncio.FIRST_COMPLETED)
            if getter in done:
                event, data = getter.result()
                yield sse(event, data)
            else:
                getter.cancel()
        try:
            state = task.result()
        except Exception:
            # 질의 원문 없이 예외 종류만 남긴다
            log.exception("chat_graph_failed", request_id=request_id)
            state = None
    finally:
        if not task.done():
            task.cancel()

    if state is None:
        answer, verdict, intents, sources = safe_answer(c.settings.inquiry_channel), "error", [], []
        reasons, agents, retrieved, model = ["error:graph_exception"], [], [], c.llm.model
        entities: list[str] = []
        fallback = False
    else:
        answer = state.get("answer") or safe_answer(c.settings.inquiry_channel)
        verdict = str(state.get("verdict") or "error")
        intents = [str(i) for i in state.get("intents") or []]
        sources = [s.to_dict() for s in state.get("sources") or []]
        reasons = [r for rs in state.get("guard_history") or [] for r in rs]
        agents = list(dict.fromkeys(state.get("agents_called") or []))
        retrieved = list(
            dict.fromkeys(
                rid for r in (state.get("results") or {}).values() for rid in r.retrieved_ids
            )
        )
        model = state.get("model") or c.llm.model
        entities = [e.ticker for e in state.get("entities") or []]
        fallback = bool(state.get("fallback_used"))

    latency_ms = int((time.perf_counter() - started) * 1000)
    message_id = None
    try:
        async with c.maker() as session:
            msg = await conv_repo.add_message(
                session,
                conversation_id=conv.id,
                role="assistant",
                content=answer,
                request_id=request_id,
                intent="+".join(intents) or None,
                guard_verdict=verdict,
                sources=sources,
                meta={"tickers": entities, "level": level.value},
            )
            await conv_repo.touch_conversation(session, conv)
            await session.commit()
            message_id = str(msg.id)
    except Exception:
        log.exception("chat_persist_failed", request_id=request_id)

    try:
        await c.tracer.record(
            TraceRecord(
                request_id=request_id,
                user_id=principal.user_id,
                intent="+".join(intents) or None,
                agents=agents,
                retrieved_doc_ids=retrieved,
                guard_verdict=verdict,
                guard_reasons=reasons,
                latency_ms=latency_ms,
                model=model,
                fallback_used=fallback,
            )
        )
    except Exception:
        log.exception("trace_record_failed", request_id=request_id)
    observe_chat(intents, verdict, latency_ms / 1000)
    log.info(
        "chat_done",
        request_id=request_id,
        intents=intents,
        verdict=verdict,
        latency_ms=latency_ms,
    )
    delay = c.settings.stream_token_delay_ms / 1000
    for piece in split_tokens(answer):
        yield sse("token", {"text": piece})
        await asyncio.sleep(delay)
    yield sse("sources", {"sources": sources})

    yield sse(
        "done",
        {
            "request_id": request_id,
            "conversation_id": str(conv.id),
            "message_id": message_id,
            "intents": intents,
            "guard": {"verdict": verdict, "reasons": _public_reasons(reasons)},
            "latency_ms": latency_ms,
        },
    )

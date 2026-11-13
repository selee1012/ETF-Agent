"""채팅 SSE 서비스. # P1-API-01

이벤트 순서: status(요청 즉시) → status(accepted, conversation_id) → status… → token… → sources → done
- 준비 단계(대화·질문 저장)나 답변 작업이 실패하면 error 이벤트로 끝낸다(done 없음).
- 답변 작성·저장·트레이스는 응답 스트림과 분리된 작업으로 돌린다. 토큰 전송은 그 뒤에 한다.
- 클라이언트가 중간에 끊으면 답변 작성(LLM 호출)은 멈추고, '중단됨' 답변과 트레이스만 남긴다.
  이력에 답 없는 질문만 남지 않고, 끊긴 요청이 비용·DB 연결을 계속 쓰지도 않는다.
- 답변 작성에는 상한 시간이 있고, 서버 종료 때는 진행 중인 작업의 저장을 기다린다(drain).
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
ERROR_MESSAGE = "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요."
CANCELLED_ANSWER = "답변을 받기 전에 연결이 끊겨 작성을 멈췄습니다. 같은 질문을 다시 보내 주세요."
CANCELLED_VERDICT = "cancelled"
# 답변 한 건의 상한 시간(분류 + 답변 + 재생성 + 판정). 넘으면 안전 답변으로 끝낸다.
ANSWER_TIMEOUT_SECONDS = 120.0
# 응답 스트림과 분리된 답변 작업. 이벤트 루프는 약한 참조만 가지므로 여기서 붙잡아 둔다.
_running: set[asyncio.Task[Any]] = set()


async def drain(wait_seconds: float = 15.0) -> None:
    """서버 종료 때: 진행 중인 답변 작업이 저장을 마칠 때까지 기다린다(DB 엔진을 닫기 전)."""
    if _running:
        await asyncio.wait(set(_running), timeout=wait_seconds)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: uuid.UUID | None = None
    # 없으면 사용자 프로필의 설명 수준, 프로필도 비어 있으면 입문 # P1-API-01
    level: Level | None = None


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def split_tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


# 사유 뒤쪽이 고정된 식별자인 종류(룰 id·판정 코드). 그 밖의 종류는 뒤에 답변의 수치·문구가
# 붙을 수 있어(ungrounded_number:9.99%) 종류만 보낸다.
_CODE_KINDS = frozenset({"banned", "judge", "pii", "missing_disclaimer", "note", "error"})


def _public_reasons(reasons: list[str]) -> list[str]:
    """done 이벤트에는 사유 코드만 보낸다(수치·문구 원문 제외)."""
    out = set()
    for r in reasons:
        kind, _, detail = r.partition(":")
        out.add(f"{kind}:{detail}" if detail and kind in _CODE_KINDS else kind)
    return sorted(out)


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

    try:
        async with c.maker() as session:
            conv = await conv_repo.get_or_create_conversation(
                session, principal.user_id, req.conversation_id, req.message
            )
            history_rows = await conv_repo.recent_messages(
                session, conv.id, c.settings.history_turns
            )
            level = req.level or await _profile_level(session, principal)
            await conv_repo.add_message(
                session, conversation_id=conv.id, role="user", content=req.message,
                request_id=request_id, meta={"level": level.value},
            )  # fmt: skip
            await session.commit()
    except Exception:
        # 응답은 이미 200으로 시작했다. 조용히 끊지 않고 실패를 알린다(질의 원문은 남기지 않는다).
        log.exception("chat_prepare_failed", request_id=request_id)
        yield sse("error", {"request_id": request_id, "message": ERROR_MESSAGE})
        return
    # 대화 id를 바로 알린다. 이후 오류·끊김으로 done을 받지 못해도 클라이언트가 같은 대화에
    # 이어서 물을 수 있다(모르면 다음 질문이 또 다른 대화로 만들어진다).
    # 여기서 직접 yield하지 않고 큐에 넣는다: 질문을 저장한 뒤 답변 작업을 만들기 전에 스트림이
    # 닫히면 답 없는 질문만 남는다.
    queue.put_nowait(
        (
            "status",
            {"stage": "accepted", "message": "질문을 이해하는 중", "conversation_id": str(conv.id)},
        )
    )
    history = [{"role": m.role, "content": m.content, "intent": m.intent} for m in history_rows]
    context_tickers: list[str] = []
    for m in reversed(history_rows):
        if m.role == "assistant" and m.meta.get("tickers"):
            context_tickers = list(m.meta["tickers"])
            break

    deps = AgentDeps(settings=c.settings, llm=c.llm, embedder=c.embedder, maker=c.maker, emit=emit)
    saving = asyncio.Event()  # 답변 작성(그래프)이 끝나고 저장 단계로 넘어가면 켜진다
    task = asyncio.create_task(
        _answer(
            c,
            principal,
            deps,
            request_id=request_id,
            conversation_id=conv.id,
            query=req.message,
            level=level,
            history=history,
            context_tickers=context_tickers,
            started=started,
            saving=saving,
        )
    )
    _running.add(task)
    task.add_done_callback(_running.discard)
    try:
        while not task.done() or not queue.empty():
            getter = asyncio.ensure_future(queue.get())
            try:
                done, _ = await asyncio.wait({task, getter}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                if not getter.done():
                    getter.cancel()
            if getter in done:
                event, data = getter.result()
                yield sse(event, data)
    finally:
        # 클라이언트가 끊겨 이 제너레이터가 닫혔다. 답변 작성을 멈춘다(작업이 '중단됨'을 기록한다).
        # 이미 저장 단계면 건드리지 않는다: 그때 취소하면 답변도 트레이스도 남지 않는다.
        if not task.done() and not saving.is_set():
            task.cancel()
    try:
        result = task.result()
    except Exception:
        log.exception("chat_answer_failed", request_id=request_id)
        yield sse("error", {"request_id": request_id, "message": ERROR_MESSAGE})
        return

    delay = c.settings.stream_token_delay_ms / 1000
    for piece in split_tokens(result["answer"]):
        yield sse("token", {"text": piece})
        await asyncio.sleep(delay)
    yield sse("sources", {"sources": result["sources"]})
    yield sse("done", result["done"])


async def _answer(
    c: Container,
    principal: Principal,
    deps: AgentDeps,
    *,
    request_id: str,
    conversation_id: uuid.UUID,
    query: str,
    level: Level,
    history: list[dict[str, Any]],
    context_tickers: list[str],
    started: float,
    saving: asyncio.Event,
) -> dict[str, Any]:
    """그래프 실행 → 답변 저장 → 트레이스. 실패·중단·시간 초과에도 답변을 저장하고 결과를 돌려준다."""
    state: GraphState | None = None
    cancelled = False
    try:
        async with asyncio.timeout(ANSWER_TIMEOUT_SECONDS):
            state = await run_graph(
                deps,
                request_id=request_id,
                query=query,
                level=level.value,
                history=history,
                context_tickers=context_tickers,
            )
    except asyncio.CancelledError:
        # 클라이언트가 끊었다(또는 서버 종료). 여기서 멈추고 아래에서 중단 기록만 남긴다.
        cancelled = True
    except Exception:
        # 질의 원문 없이 예외 종류만 남긴다(시간 초과 포함)
        log.exception("chat_graph_failed", request_id=request_id)
    saving.set()  # 여기부터는 취소하지 않는다(호출 측이 이 표시를 보고 판단한다)

    if cancelled:
        answer, verdict, intents, sources = CANCELLED_ANSWER, CANCELLED_VERDICT, [], []
        reasons, agents, retrieved, model = ["note:client_disconnected"], [], [], c.llm.model
        entities: list[str] = []
        fallback = False
    elif state is None:
        answer, verdict, intents, sources = safe_answer(c.settings.inquiry_channel), "error", [], []
        reasons, agents, retrieved, model = ["error:graph_exception"], [], [], c.llm.model
        entities = []
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
                conversation_id=conversation_id,
                role="assistant",
                content=answer,
                request_id=request_id,
                intent="+".join(intents) or None,
                guard_verdict=verdict,
                sources=sources,
                meta={"tickers": entities, "level": level.value},
            )
            await conv_repo.touch_conversation(session, conversation_id)
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
    return {
        "answer": answer,
        "sources": sources,
        "done": {
            "request_id": request_id,
            "conversation_id": str(conversation_id),
            "message_id": message_id,
            "intents": intents,
            "guard": {"verdict": verdict, "reasons": _public_reasons(reasons)},
            "latency_ms": latency_ms,
        },
    }

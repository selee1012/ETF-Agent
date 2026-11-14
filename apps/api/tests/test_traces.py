"""트레이스: 요청당 1행, 질의 원문 미저장, /metrics (P1-OP-01·02)."""

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import inspect, select

from app.db import get_engine, get_sessionmaker
from app.observability import build_tracer
from app.repositories.models import Trace
from app.settings import AppEnv, Settings, Tracer
from tests.sse import parse_sse

RAW_QUERY = "샘플 코스피200 괴리율 알려줘 제 번호는 010-2222-3333 입니다 zz-unique-marker"


async def test_trace_has_no_raw_query(client: AsyncClient, user_headers: dict) -> None:
    resp = await client.post("/chat", json={"message": RAW_QUERY}, headers=user_headers)
    done = parse_sse(resp.text)[-1][1]
    async with get_sessionmaker()() as s:
        trace = await s.scalar(select(Trace).where(Trace.request_id == done["request_id"]))
    assert trace is not None
    assert trace.intent == "etf_info"
    assert trace.agents == ["etf_info"]
    assert trace.guard_verdict == "pass"
    assert trace.latency_ms is not None and trace.model
    assert "etf:900010" in trace.retrieved_doc_ids
    # 어떤 컬럼에도 질의 원문·개인정보가 없다
    for col in Trace.__table__.columns:
        value = str(getattr(trace, col.key))
        assert "zz-unique-marker" not in value
        assert "010-2222-3333" not in value

    async with get_engine().connect() as conn:
        cols = await conn.run_sync(lambda c: [x["name"] for x in inspect(c).get_columns("traces")])
    assert not {"query", "question", "message", "content", "prompt"} & set(cols)


async def test_guard_verdict_and_template_recorded(client: AsyncClient, user_headers: dict) -> None:
    resp = await client.post(
        "/chat", json={"message": "샘플 코스피200 지금 사야 할까?"}, headers=user_headers
    )
    done = parse_sse(resp.text)[-1][1]
    async with get_sessionmaker()() as s:
        trace = await s.scalar(select(Trace).where(Trace.request_id == done["request_id"]))
    assert (trace.intent, trace.guard_verdict) == ("high_risk", "template")
    assert trace.model == "template"


async def test_metrics_endpoint(client: AsyncClient, user_headers: dict) -> None:
    await client.post("/chat", json={"message": "괴리율이 뭐야?"}, headers=user_headers)
    body = (await client.get("/metrics")).text
    assert "etf_http_requests_total" in body
    assert 'etf_chat_intent_total{intent="faq"}' in body
    assert "etf_guard_block_rate" in body
    assert "etf_http_request_duration_seconds_bucket" in body


async def test_metrics_requires_token_when_configured(client: AsyncClient, app: FastAPI) -> None:
    c = app.state.container
    c.settings = c.settings.model_copy(update={"metrics_token": SecretStr("scrape-secret")})
    assert (await client.get("/metrics")).status_code == 401
    wrong = {"Authorization": "Bearer nope"}
    assert (await client.get("/metrics", headers=wrong)).status_code == 401
    ok = await client.get("/metrics", headers={"Authorization": "Bearer scrape-secret"})
    assert ok.status_code == 200 and "etf_http_requests_total" in ok.text


async def test_metrics_hidden_outside_local_without_token(
    client: AsyncClient, app: FastAPI
) -> None:
    c = app.state.container
    c.settings = c.settings.model_copy(update={"app_env": AppEnv.DEV, "metrics_token": None})
    assert (await client.get("/metrics")).status_code == 404


def test_unimplemented_tracer_fails_at_startup(settings: Settings) -> None:
    """스텁 트레이서로 기동하면 채팅은 되고 트레이스만 조용히 빠지므로 조립 단계에서 막는다."""
    stub = settings.model_copy(update={"tracer": Tracer.LANGFUSE})
    with pytest.raises(NotImplementedError, match="TRACER=pg"):
        build_tracer(stub, get_sessionmaker())

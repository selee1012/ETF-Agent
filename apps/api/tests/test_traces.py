"""트레이스: 요청당 1행, 질의 원문 미저장, /metrics (P1-OP-01·02)."""

from httpx import AsyncClient
from sqlalchemy import inspect, select

from app.db import get_engine, get_sessionmaker
from app.repositories.models import Trace
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

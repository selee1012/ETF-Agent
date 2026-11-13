"""폴백 라우터와 공급자 SDK import 경계. 네트워크 없이 검증한다."""

import ast
from pathlib import Path

import pytest

from app.agents.graph import run_graph
from app.agents.state import AgentDeps
from app.llm import build_llm
from app.llm.base import ChatMessage, LLMError, LLMUnavailableError
from app.llm.fake import FakeLLM
from app.llm.openai_compat import OpenAICompatLLM
from app.llm.router import LLMRouter, build_fallback
from app.observability.metrics import LLM_CALLS, render
from app.settings import Settings

APP_DIR = Path(__file__).resolve().parents[1] / "app"
DB_URL = "postgresql+asyncpg://u:p@h/db"


def test_no_fallback_by_default():
    assert build_fallback(Settings(database_url=DB_URL, fallback_provider="none")) is None


@pytest.mark.parametrize(
    "given", [{"fallback_model": "gpt-5-mini"}, {"fallback_base_url": "https://x/openai/v1/"}]
)
def test_openai_compat_fallback_requires_url_and_model(given):
    s = Settings(database_url=DB_URL, fallback_provider="openai_compat", **given)
    with pytest.raises(ValueError, match="FALLBACK_BASE_URL"):
        build_fallback(s)


def test_factory_wraps_primary_with_openai_compat_fallback():
    s = Settings(
        database_url=DB_URL,
        llm_provider="openai_compat",
        llm_base_url="http://vllm.internal:8000/v1",
        llm_model="midm-2.0-mini",
        fallback_provider="openai_compat",
        fallback_base_url="https://example.openai.azure.com/openai/v1/",
        fallback_api_key="k",
        fallback_model="gpt-5-mini",
    )
    llm = build_llm(s)
    assert isinstance(llm, LLMRouter)
    assert llm.primary.model == "midm-2.0-mini"
    assert isinstance(llm.fallback, OpenAICompatLLM)
    assert llm.fallback.model == "gpt-5-mini"
    assert str(llm.fallback._client.base_url).startswith("https://example.openai.azure.com/")


async def test_router_falls_back_only_for_allowed_intents():
    primary = FakeLLM(script={"faq_answer": [LLMError("down")], "etf_summary": [LLMError("down")]})
    fallback = FakeLLM(model="fallback", script={"faq_answer": ["폴백 답변"]})
    router = LLMRouter(primary, fallback, ["faq"])
    resp = await router.complete([ChatMessage("user", "q")], task="faq_answer", intent="faq")
    assert resp.text == "폴백 답변" and resp.fallback_used
    with pytest.raises(LLMUnavailableError):
        await router.complete([ChatMessage("user", "q")], task="etf_summary", intent="etf_info")


async def test_router_fallback_failure_is_unavailable():
    primary = FakeLLM(script={"faq_answer": [LLMError("down")]})
    fallback = FakeLLM(script={"faq_answer": [LLMError("also down")]})
    router = LLMRouter(primary, fallback, ["faq"])
    with pytest.raises(LLMUnavailableError):
        await router.complete([ChatMessage("user", "q")], task="faq_answer", intent="faq")


async def test_router_does_not_fall_back_without_allowed_intent():
    """의도를 모르는 호출·허용되지 않은 의도가 섞인 호출은 폴백 엔드포인트로 나가지 않는다."""
    fallback = FakeLLM(model="fallback")
    for intent in (None, "etf_info", "faq+etf_info"):
        router = LLMRouter(FakeLLM(script={"judge": [LLMError("down")]}), fallback, ["faq"])
        with pytest.raises(LLMUnavailableError):
            await router.complete([ChatMessage("user", "q")], task="judge", intent=intent)
    assert fallback.calls == []


async def test_disallowed_intent_never_reaches_fallback_in_graph(deps: AgentDeps) -> None:
    down = [LLMError("down")] * 4
    primary = FakeLLM(script={"classify": list(down), "answer": list(down), "judge": list(down)})
    fallback = FakeLLM(model="fallback")
    deps.llm = LLMRouter(primary, fallback, ["faq"])
    st = await run_graph(deps, request_id="t", query="샘플 반도체 최근 공시 알려줘")
    assert st["intents"] == ["disclosure"]  # 분류는 키워드 규칙으로 대체
    assert fallback.calls == []


async def test_multi_intent_answer_does_not_leak_to_fallback(deps: AgentDeps) -> None:
    """faq만 허용일 때 'etf_info+faq' 질문의 ETF 자료가 답변 호출로 폴백에 나가지 않는다."""
    primary = FakeLLM(
        script={
            "classify": ['{"intents": ["etf_info", "faq"]}'],
            "answer": [LLMError("down")],
        }
    )
    fallback = FakeLLM(model="fallback")
    deps.llm = LLMRouter(primary, fallback, ["faq"])
    st = await run_graph(deps, request_id="t", query="샘플 코스피200 괴리율이 뭐야?")
    assert st["intents"] == ["etf_info", "faq"]
    assert fallback.calls == []
    assert [c["intent"] for c in primary.calls if c["task"] == "answer"] == ["etf_info+faq"]


@pytest.mark.parametrize("pkg", ["agents", "tools", "rag"])
def test_domain_code_does_not_import_provider_sdks(pkg):
    """공통 규칙 1: 공급자 SDK는 어댑터(llm/, auth/, storage/, observability/)에서만."""
    banned = {"openai", "azure", "supabase", "langfuse"}
    for path in (APP_DIR / pkg).rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                assert n.split(".")[0] not in banned, f"{path}: {n}"


async def test_graph_records_fallback_and_answer_model(deps: AgentDeps) -> None:
    primary = FakeLLM(
        model="primary", script={"answer": [LLMError("down")], "judge": [LLMError("down")]}
    )
    deps.llm = LLMRouter(primary, FakeLLM(model="fallback"), ["faq"])
    before = LLM_CALLS.labels("answer", "fallback")._value.get()
    st = await run_graph(deps, request_id="t", query="괴리율이 뭐야?")
    assert st["verdict"] == "pass"  # 허용 의도(faq)는 답변·판정 모두 폴백으로 이어진다
    assert st["fallback_used"] is True
    assert st["model"] == "fallback"  # 트레이스에는 실제로 답변을 쓴 모델이 남는다
    assert LLM_CALLS.labels("answer", "fallback")._value.get() == before + 1
    assert b'etf_llm_calls_total{outcome="fallback",task="judge"}' in render()


async def test_graph_without_fallback_keeps_primary_model(deps: AgentDeps) -> None:
    st = await run_graph(deps, request_id="t", query="괴리율이 뭐야?")
    assert st["fallback_used"] is False
    assert st["model"] == deps.llm.model

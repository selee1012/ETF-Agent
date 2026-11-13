"""폴백 라우터와 공급자 SDK import 경계. 네트워크 없이 검증한다."""

import ast
from pathlib import Path

import pytest

from app.llm import build_llm
from app.llm.base import ChatMessage, LLMError, LLMUnavailableError
from app.llm.fake import FakeLLM
from app.llm.openai_compat import OpenAICompatLLM
from app.llm.router import LLMRouter, build_fallback
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

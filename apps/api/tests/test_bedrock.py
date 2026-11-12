"""Bedrock 어댑터·폴백 라우터. 네트워크 없이 botocore Stubber로 요청·응답 형식을 검증한다."""

import ast
import io
import json
from pathlib import Path

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber

from app.llm import build_embedder, build_llm
from app.llm.base import ChatMessage, LLMError, LLMUnavailableError
from app.llm.bedrock import BedrockEmbedder, BedrockLLM, to_converse
from app.llm.fake import FakeLLM
from app.llm.router import LLMRouter, build_fallback
from app.settings import Settings

APP_DIR = Path(__file__).resolve().parents[1] / "app"


def _client():
    return boto3.client(
        "bedrock-runtime",
        region_name="ap-northeast-2",
        aws_access_key_id="test",
        aws_secret_access_key="test",  # noqa: S106 (Stubber 전용 더미)
    )


def _converse_resp(text: str) -> dict:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 11, "outputTokens": 7, "totalTokens": 18},
        "metrics": {"latencyMs": 120},
    }


def _body(obj: dict) -> StreamingBody:
    raw = json.dumps(obj).encode()
    return StreamingBody(io.BytesIO(raw), len(raw))


def test_to_converse_merges_roles_and_system():
    system, turns = to_converse(
        [
            ChatMessage("system", "규칙A"),
            ChatMessage("assistant", "앞선 인사"),  # 맨 앞 assistant는 버린다
            ChatMessage("user", "질문1"),
            ChatMessage("user", "보충"),
            ChatMessage("assistant", "답1"),
            ChatMessage("user", "질문2"),
        ],
        json_mode=True,
    )
    assert system[0]["text"].startswith("규칙A") and "JSON" in system[0]["text"]
    assert [t["role"] for t in turns] == ["user", "assistant", "user"]
    assert turns[0]["content"][0]["text"] == "질문1\n\n보충"


async def test_bedrock_llm_converse_request_and_response():
    client = _client()
    llm = BedrockLLM(region="ap-northeast-2", model_id="test.model-v1", client=client)
    with Stubber(client) as stub:
        stub.add_response(
            "converse",
            _converse_resp("안녕하세요"),
            {
                "modelId": "judge.model-v1",
                "system": [{"text": "sys"}],
                "messages": [{"role": "user", "content": [{"text": "hi"}]}],
                "inferenceConfig": {"maxTokens": 50, "temperature": 0},
            },
        )
        resp = await llm.complete(
            [ChatMessage("system", "sys"), ChatMessage("user", "hi")],
            model="judge.model-v1",
            temperature=0,
            max_tokens=50,
        )
        stub.assert_no_pending_responses()
    assert resp.text == "안녕하세요"
    assert resp.model == "judge.model-v1"
    assert resp.usage == {"prompt_tokens": 11, "completion_tokens": 7}


async def test_bedrock_llm_maps_client_error_to_llm_error():
    client = _client()
    llm = BedrockLLM(region="ap-northeast-2", model_id="test.model-v1", client=client)
    with Stubber(client) as stub:
        stub.add_client_error("converse", service_error_code="ThrottlingException")
        with pytest.raises(LLMError, match="ThrottlingException"):
            await llm.complete([ChatMessage("user", "hi")])


async def test_titan_embedding_body_and_normalize():
    client = _client()
    emb = BedrockEmbedder(
        region="ap-northeast-2", model_id="amazon.titan-embed-text-v2:0", dim=3, client=client
    )
    with Stubber(client) as stub:
        for vec in ([3.0, 4.0, 0.0], [0.0, 0.0, 2.0]):
            stub.add_response(
                "invoke_model",
                {"body": _body({"embedding": vec}), "contentType": "application/json"},
                {
                    "modelId": "amazon.titan-embed-text-v2:0",
                    "body": ANY,
                    "contentType": "application/json",
                    "accept": "application/json",
                },
            )
        out = await emb.embed(["a", "b"])
    # 동시 호출이라 Stubber 응답이 어느 텍스트에 붙을지는 스레드 순서에 따른다.
    got = sorted(tuple(round(x, 6) for x in v) for v in out)
    assert got == [(0.0, 0.0, 1.0), (0.6, 0.8, 0.0)]


async def test_cohere_embedding_and_dim_mismatch():
    client = _client()
    emb = BedrockEmbedder(
        region="ap-northeast-2", model_id="cohere.embed-multilingual-v3", dim=2, client=client
    )
    with Stubber(client) as stub:
        stub.add_response(
            "invoke_model",
            {
                "body": _body({"embeddings": {"float": [[1.0, 0.0], [0.0, 1.0]]}}),
                "contentType": "application/json",
            },
        )
        assert len(await emb.embed(["a", "b"])) == 2
        stub.add_response(
            "invoke_model",
            {
                "body": _body({"embeddings": {"float": [[1.0, 0.0, 0.0]]}}),
                "contentType": "application/json",
            },
        )
        with pytest.raises(LLMError, match="차원 불일치"):
            await emb.embed(["a"])


def test_unsupported_embedding_model_rejected():
    with pytest.raises(ValueError, match="지원하지 않는"):
        BedrockEmbedder(region="ap-northeast-2", model_id="foo.bar", dim=8, client=object())


def test_factory_builds_bedrock_adapters():
    s = Settings(
        database_url="postgresql+asyncpg://u:p@h/db",
        llm_provider="bedrock",
        llm_model="anthropic.claude-test",
        embedding_provider="bedrock",
        embedding_model="amazon.titan-embed-text-v2:0",
    )
    llm = build_llm(s)
    assert isinstance(llm, LLMRouter) and isinstance(llm.primary, BedrockLLM)
    assert llm.primary.model == "anthropic.claude-test"
    assert isinstance(build_embedder(s), BedrockEmbedder)


def test_bedrock_fallback_requires_model_id():
    s = Settings(database_url="postgresql+asyncpg://u:p@h/db", fallback_provider="bedrock")
    with pytest.raises(ValueError, match="BEDROCK_MODEL_ID"):
        build_fallback(s)


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
    banned = {"openai", "boto3", "botocore", "supabase", "langfuse"}
    for path in (APP_DIR / pkg).rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                assert n.split(".")[0] not in banned, f"{path}: {n}"

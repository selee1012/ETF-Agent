"""OpenAI 호환 어댑터 요청 파라미터(OpenAI API 최신 모델 호환 옵션). 네트워크 없이 클라이언트를 바꿔 낀다."""

from types import SimpleNamespace

from app.llm.base import ChatMessage
from app.llm.openai_compat import OpenAICompatEmbedder, OpenAICompatLLM


class _Capture:
    def __init__(self, result):
        self.kwargs: dict = {}
        self._result = result

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self._result


def _chat_result(text: str):
    msg = SimpleNamespace(content=text)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None)


def _llm(**kw) -> tuple[OpenAICompatLLM, _Capture]:
    llm = OpenAICompatLLM(
        base_url="http://x/v1",
        api_key=None,
        model="m",
        timeout=5,
        default_max_tokens=100,
        default_temperature=0.2,
        **kw,
    )
    cap = _Capture(_chat_result("<think>숨김</think>답"))
    llm._client = SimpleNamespace(chat=SimpleNamespace(completions=cap))
    return llm, cap


async def test_default_params_send_max_tokens_and_temperature():
    llm, cap = _llm()
    resp = await llm.complete([ChatMessage("user", "q")])
    assert resp.text == "답"  # <think> 제거
    assert cap.kwargs["max_tokens"] == 100 and cap.kwargs["temperature"] == 0.2
    assert "max_completion_tokens" not in cap.kwargs


async def test_reasoning_model_params():
    llm, cap = _llm(max_tokens_param="max_completion_tokens", omit_temperature=True)
    await llm.complete([ChatMessage("user", "q")], max_tokens=40, temperature=0)
    assert cap.kwargs["max_completion_tokens"] == 40
    assert "max_tokens" not in cap.kwargs and "temperature" not in cap.kwargs


async def test_reasoning_effort_only_when_set():
    llm, cap = _llm()
    await llm.complete([ChatMessage("user", "q")])
    assert "reasoning_effort" not in cap.kwargs
    llm, cap = _llm(
        max_tokens_param="max_completion_tokens", omit_temperature=True, reasoning_effort="none"
    )
    await llm.complete([ChatMessage("user", "q")])
    assert cap.kwargs["reasoning_effort"] == "none"


async def test_embedding_dimensions_flag():
    data = [SimpleNamespace(index=0, embedding=[3.0, 4.0])]
    for flag, expected in ((True, 2), (False, None)):
        emb = OpenAICompatEmbedder(
            base_url="http://x/v1",
            api_key=None,
            model="e",
            dim=2,
            timeout=5,
            request_dimensions=flag,
        )
        cap = _Capture(SimpleNamespace(data=data))
        emb._client = SimpleNamespace(embeddings=cap)
        out = await emb.embed(["a"])
        assert out == [[0.6, 0.8]]
        got = cap.kwargs["dimensions"]
        assert (got if isinstance(got, int) else None) == expected

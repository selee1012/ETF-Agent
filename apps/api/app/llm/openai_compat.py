"""OpenAI 호환 API 어댑터(Ollama /v1, AWS 자체 호스팅 vLLM, OpenAI API). openai SDK는 이 파일에서만 쓴다."""

import math
import re

import openai
from openai import AsyncOpenAI

from app.llm.base import ChatMessage, Embedder, LLMClient, LLMError, LLMResponse
from app.logging import get_logger

log = get_logger(__name__)

# 추론형 모델(qwen3 등)이 내보내는 사고 과정 태그는 답변에서 뺀다.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _client(base_url: str, api_key: str | None, timeout: float) -> AsyncOpenAI:
    # Ollama는 키가 필요 없지만 SDK가 빈 값을 거부하므로 자리표시를 넣는다.
    return AsyncOpenAI(
        base_url=base_url, api_key=api_key or "local", timeout=timeout, max_retries=1
    )


class OpenAICompatLLM(LLMClient):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout: float,
        default_max_tokens: int,
        default_temperature: float,
        max_tokens_param: str = "max_tokens",
        omit_temperature: bool = False,
    ) -> None:
        self.model = model
        self._client = _client(base_url, api_key, timeout)
        self._max_tokens = default_max_tokens
        self._temperature = default_temperature
        self._max_tokens_param = max_tokens_param
        self._omit_temperature = omit_temperature

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        task: str = "generate",
        intent: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        name = model or self.model
        params: dict = {self._max_tokens_param: max_tokens or self._max_tokens}
        if not self._omit_temperature:
            params["temperature"] = self._temperature if temperature is None else temperature
        try:
            resp = await self._client.chat.completions.create(
                model=name,
                messages=[{"role": m.role, "content": m.content} for m in messages],
                response_format={"type": "json_object"} if json_mode else openai.NOT_GIVEN,
                **params,
            )
        except (openai.APIError, openai.APITimeoutError, openai.APIConnectionError) as e:
            # 질의 원문은 남기지 않고 오류 종류만 남긴다.
            log.warning("llm_call_failed", task=task, model=name, error=type(e).__name__)
            raise LLMError(f"LLM 호출 실패: {type(e).__name__}") from e
        text = (resp.choices[0].message.content or "") if resp.choices else ""
        text = _THINK_RE.sub("", text).strip()
        usage = {}
        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
            }
        return LLMResponse(text=text, model=name, usage=usage)


class OpenAICompatEmbedder(Embedder):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        dim: int,
        timeout: float,
        request_dimensions: bool = False,
    ) -> None:
        self.model = model
        self.dim = dim
        self._client = _client(base_url, api_key, timeout)
        self._request_dimensions = request_dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            resp = await self._client.embeddings.create(
                model=self.model,
                input=texts,
                dimensions=self.dim if self._request_dimensions else openai.NOT_GIVEN,
            )
        except (openai.APIError, openai.APITimeoutError, openai.APIConnectionError) as e:
            log.warning("embedding_call_failed", model=self.model, error=type(e).__name__)
            raise LLMError(f"임베딩 호출 실패: {type(e).__name__}") from e
        vectors = [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]
        for v in vectors:
            if len(v) != self.dim:
                raise LLMError(
                    f"임베딩 차원 불일치: 모델 {self.model}={len(v)}, EMBEDDING_DIM={self.dim}"
                )
        return [_normalize(v) for v in vectors]


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]

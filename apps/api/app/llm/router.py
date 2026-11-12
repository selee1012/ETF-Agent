"""1순위 LLM → 폴백 라우터. # P1-AG-06

지금은 FALLBACK_PROVIDER=none만 동작한다: 1순위가 실패하면 LLMUnavailableError를 올리고
그래프가 안전 답변을 내보낸다. Bedrock 폴백은 Phase 1 배포에서 BedrockLLM을 구현해 붙인다.
"""

from app.llm.base import ChatMessage, LLMClient, LLMError, LLMResponse, LLMUnavailableError
from app.settings import FallbackProvider, Settings


class BedrockLLM(LLMClient):
    """자리만 있는 스텁. 구현 시 boto3 bedrock-runtime Converse API를 여기서만 쓴다."""

    def __init__(self, *, region: str, model_id: str | None) -> None:
        self.model = model_id or "bedrock"
        self.region = region

    async def complete(self, messages: list[ChatMessage], **_: object) -> LLMResponse:
        raise NotImplementedError("Bedrock 폴백은 Phase 1 배포 단계에서 구현한다")


def build_fallback(settings: Settings) -> LLMClient | None:
    if settings.fallback_provider is FallbackProvider.BEDROCK:
        return BedrockLLM(region=settings.bedrock_region, model_id=settings.bedrock_model_id)
    return None


class LLMRouter(LLMClient):
    def __init__(
        self, primary: LLMClient, fallback: LLMClient | None, allowed_intents: list[str]
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.allowed_intents = set(allowed_intents)
        self.model = primary.model

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
        kwargs = {
            "task": task,
            "intent": intent,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "json_mode": json_mode,
        }
        try:
            return await self.primary.complete(messages, **kwargs)
        except LLMError as e:
            if self.fallback is None or (intent and intent not in self.allowed_intents):
                raise LLMUnavailableError(str(e)) from e
            # P1 배포 단계: 폴백 호출. 지금은 BedrockLLM이 NotImplementedError를 올린다.
            resp = await self.fallback.complete(messages, **{**kwargs, "model": None})
            resp.fallback_used = True
            return resp

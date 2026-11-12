"""1순위 LLM → 폴백 라우터. # P1-AG-06

- FALLBACK_PROVIDER=none: 1순위가 실패하면 LLMUnavailableError → 그래프가 안전 답변을 낸다.
- FALLBACK_PROVIDER=bedrock: FALLBACK_ALLOWED_INTENTS에 든 의도만 Bedrock(BEDROCK_MODEL_ID)으로
  다시 호출한다(예: 자체 호스팅 sLLM 장애 시 FAQ만 Bedrock으로).
"""

from app.llm.base import ChatMessage, LLMClient, LLMError, LLMResponse, LLMUnavailableError
from app.settings import FallbackProvider, Settings


def build_fallback(settings: Settings) -> LLMClient | None:
    if settings.fallback_provider is FallbackProvider.BEDROCK:
        if not settings.bedrock_model_id:
            raise ValueError("FALLBACK_PROVIDER=bedrock이면 BEDROCK_MODEL_ID가 필요합니다")
        from app.llm.bedrock import BedrockLLM

        return BedrockLLM(
            region=settings.bedrock_region,
            profile=settings.bedrock_profile,
            model_id=settings.bedrock_model_id,
            timeout=settings.llm_timeout_seconds,
            default_max_tokens=settings.llm_max_tokens,
            default_temperature=settings.llm_temperature,
        )
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
            # 폴백은 자기 모델을 쓴다(1순위용 모델 이름·judge 모델 이름을 넘기지 않는다).
            try:
                resp = await self.fallback.complete(messages, **{**kwargs, "model": None})
            except LLMError as fe:
                raise LLMUnavailableError(str(fe)) from fe
            resp.fallback_used = True
            return resp

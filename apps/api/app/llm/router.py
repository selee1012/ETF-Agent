"""1순위 LLM → 폴백 라우터. # P1-AG-06

- FALLBACK_PROVIDER=none: 1순위가 실패하면 LLMUnavailableError → 그래프가 안전 답변을 낸다.
- FALLBACK_PROVIDER=openai_compat: FALLBACK_ALLOWED_INTENTS에 든 의도만 다른 OpenAI 호환 엔드포인트
  (FALLBACK_BASE_URL·FALLBACK_MODEL)로 다시 호출한다(예: 자체 호스팅 sLLM 장애 시 FAQ만 Azure OpenAI로).
"""

from app.llm.base import ChatMessage, LLMClient, LLMError, LLMResponse, LLMUnavailableError
from app.settings import FallbackProvider, Settings


def build_fallback(settings: Settings) -> LLMClient | None:
    if settings.fallback_provider is FallbackProvider.OPENAI_COMPAT:
        if not settings.fallback_base_url or not settings.fallback_model:
            raise ValueError(
                "FALLBACK_PROVIDER=openai_compat이면 FALLBACK_BASE_URL과 FALLBACK_MODEL이 필요합니다"
            )
        from app.llm.openai_compat import OpenAICompatLLM

        key = settings.fallback_api_key
        effort = settings.fallback_reasoning_effort
        return OpenAICompatLLM(
            base_url=settings.fallback_base_url,
            api_key=key.get_secret_value() if key else None,
            model=settings.fallback_model,
            timeout=settings.llm_timeout_seconds,
            default_max_tokens=settings.llm_max_tokens,
            default_temperature=settings.llm_temperature,
            max_tokens_param="max_completion_tokens",
            omit_temperature=True,
            reasoning_effort=None if effort == "off" else effort,
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

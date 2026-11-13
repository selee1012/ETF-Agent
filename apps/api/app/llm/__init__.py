"""LLM·임베딩 어댑터. 에이전트는 base.py의 인터페이스만 쓴다(공통 규칙 1).

공급자 선택은 settings.LLM_PROVIDER / EMBEDDING_PROVIDER(Enum)로만 한다(공통 규칙 3).
- openai_compat: OpenAI API(로컬 기본), Azure OpenAI(고도화 버전 주 모델), 자체 호스팅 vLLM 등 OpenAI 호환 서버
- bedrock: AWS Bedrock(선택지로 남김)
- fake: 테스트·키 없는 환경
"""

from app.llm.base import Embedder, LLMClient
from app.settings import LLMProvider, Settings


def build_llm(settings: Settings, *, model: str | None = None) -> LLMClient:
    """1순위 LLM을 만들고 폴백 라우터로 감싼다."""
    from app.llm.router import LLMRouter, build_fallback

    primary: LLMClient
    if settings.llm_provider is LLMProvider.FAKE:
        from app.llm.fake import FakeLLM

        primary = FakeLLM(model=f"fake({model or settings.llm_model})")
    elif settings.llm_provider is LLMProvider.BEDROCK:
        from app.llm.bedrock import BedrockLLM

        primary = BedrockLLM(
            region=settings.bedrock_region,
            profile=settings.bedrock_profile,
            model_id=model or settings.llm_model,
            timeout=settings.llm_timeout_seconds,
            default_max_tokens=settings.llm_max_tokens,
            default_temperature=settings.llm_temperature,
        )
    else:
        from app.llm.openai_compat import OpenAICompatLLM

        primary = OpenAICompatLLM(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key.get_secret_value() if settings.llm_api_key else None,
            model=model or settings.llm_model,
            timeout=settings.llm_timeout_seconds,
            default_max_tokens=settings.llm_max_tokens,
            default_temperature=settings.llm_temperature,
            max_tokens_param=settings.openai_max_tokens_param,
            omit_temperature=settings.openai_omit_temperature,
            reasoning_effort=(
                None
                if settings.openai_reasoning_effort == "off"
                else settings.openai_reasoning_effort
            ),
        )
    return LLMRouter(primary, build_fallback(settings), settings.fallback_allowed_intents)


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider is LLMProvider.FAKE:
        from app.llm.fake import FakeEmbedder

        return FakeEmbedder(dim=settings.embedding_dim)
    if settings.embedding_provider is LLMProvider.BEDROCK:
        from app.llm.bedrock import BedrockEmbedder

        return BedrockEmbedder(
            region=settings.bedrock_region,
            profile=settings.bedrock_profile,
            model_id=settings.embedding_model,
            dim=settings.embedding_dim,
            timeout=settings.llm_timeout_seconds,
        )
    from app.llm.openai_compat import OpenAICompatEmbedder

    return OpenAICompatEmbedder(
        base_url=settings.embedding_base_url or settings.llm_base_url,
        api_key=settings.llm_api_key.get_secret_value() if settings.llm_api_key else None,
        model=settings.embedding_model,
        dim=settings.embedding_dim,
        timeout=settings.llm_timeout_seconds,
        request_dimensions=settings.embedding_request_dimensions,
    )


__all__ = ["Embedder", "LLMClient", "build_embedder", "build_llm"]

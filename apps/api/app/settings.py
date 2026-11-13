"""환경변수 기반 애플리케이션 설정. 모든 설정값은 이 모듈에서만 읽는다.

어댑터(LLM·인증·저장소·트레이서)는 여기의 Enum 값으로만 고른다
"""

import secrets
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# apps/api/app/settings.py → 레포 루트
# 컨테이너도 /workspace에 같은 구조로 둔다
REPO_ROOT = Path(__file__).resolve().parents[3]


class AppEnv(StrEnum):
    LOCAL = "local"
    DEV = "dev"
    PROD = "prod"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class LLMProvider(StrEnum):
    OPENAI_COMPAT = "openai_compat"  # OpenAI API·Azure OpenAI·자체 호스팅 vLLM 등 OpenAI 호환 서버
    FAKE = "fake"  # 테스트·키 없는 환경


class FallbackProvider(StrEnum):
    NONE = "none"
    OPENAI_COMPAT = (
        "openai_compat"  # 1순위(vLLM 등) 실패 시 다른 OpenAI 호환 엔드포인트(Azure OpenAI)
    )


class AuthProvider(StrEnum):
    LOCAL = "local"  # 개발용 dev-login JWT
    SUPABASE = "supabase"  # 스텁
    ENTRA = "entra"  # 스텁(Microsoft Entra External ID)


class AdminAuth(StrEnum):
    LOCAL = "local"  # local JWT의 role=admin
    CF_ACCESS = "cf_access"  # 스텁


class StorageProvider(StrEnum):
    LOCAL = "local"
    SUPABASE = "supabase"  # 스텁
    AZURE_BLOB = "azure_blob"  # 스텁(Azure Blob Storage)


class Tracer(StrEnum):
    PG = "pg"
    LANGFUSE = "langfuse"  # 스텁


# 쉼표로 구분된 환경변수 값을 리스트로 받는다(JSON 디코딩 비활성화).
CommaList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # 루트 .env → 루트 .env.local(개인 로컬 설정, gitignore) → apps/api/.env 순으로 읽는다.
        # 뒤 파일이 앞 파일을 덮고, 실제 환경변수가 항상 우선한다.
        env_file=("../../.env", "../../.env.local", ".env"),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=False,
    )

    # --- 앱 ---
    app_env: AppEnv = AppEnv.LOCAL
    log_level: LogLevel = LogLevel.INFO
    cors_origins: CommaList = Field(default_factory=lambda: ["http://localhost:5173"])

    # --- DB (필수) ---
    database_url: str

    # --- 인증 ---
    auth_provider: AuthProvider = AuthProvider.LOCAL
    admin_auth: AdminAuth = AdminAuth.LOCAL
    # local JWT 서명 키. 비우면 local 환경에서만 프로세스마다 임의 생성(재시작 시 재로그인 필요)
    local_jwt_secret: SecretStr | None = None
    local_jwt_ttl_minutes: int = Field(default=60 * 12, gt=0)
    # dev-login 시 role=admin을 받을 이메일(쉼표 구분)
    admin_emails: CommaList = Field(default_factory=lambda: ["admin@local.test"])
    # Supabase Auth (스텁에서 사용 예정)
    supabase_url: str | None = None
    supabase_jwks_url: str | None = None
    supabase_jwt_secret: SecretStr | None = None
    # Microsoft Entra External ID (스텁에서 사용 예정)
    entra_tenant_id: str | None = None
    entra_client_id: str | None = None
    # Cloudflare Access (스텁에서 사용 예정)
    cf_access_team_domain: str | None = None
    cf_access_aud: str | None = None

    # --- LLM ---
    llm_provider: LLMProvider = LLMProvider.OPENAI_COMPAT
    # 기본: OpenAI API의 가장 가벼운 추론형 모델 + 생각 분량 none(응답 속도 우선). 품질은 프롬프트·RAG로 보강
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr | None = None
    llm_model: str = "gpt-5.4-nano"
    judge_model: str | None = None  # 비우면 llm_model과 같음
    llm_timeout_seconds: float = Field(default=60.0, gt=0)
    llm_max_tokens: int = Field(default=1200, gt=0)  # FAQ 상세 설명 기준
    llm_temperature: float = Field(default=0.2, ge=0, le=2)
    # OpenAI API 최신 모델(gpt-5·o 계열) 호환: max_tokens 대신 max_completion_tokens, 온도 생략.
    # vLLM 등 예전 형식 서버는 max_tokens / false / (빈 값)으로 바꾼다.
    openai_max_tokens_param: Literal["max_tokens", "max_completion_tokens"] = (
        "max_completion_tokens"
    )
    openai_omit_temperature: bool = True
    # 추론형 모델의 생각 분량. none이 가장 빠르다(5.1+, gpt-5는 minimal). off면 보내지 않는다(vLLM 등)
    openai_reasoning_effort: Literal["off", "none", "minimal", "low", "medium", "high"] = "none"
    # 임베딩: 비우면 llm_provider를 따른다
    embedding_provider: LLMProvider | None = None
    embedding_base_url: str | None = None  # 비우면 llm_base_url
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = Field(default=1024, gt=0)
    # true면 임베딩 요청에 dimensions=EMBEDDING_DIM을 보낸다(OpenAI text-embedding-3 축소용)
    embedding_request_dimensions: bool = True

    # --- LLM 폴백 (예: 자체 호스팅 vLLM 장애 시 Azure OpenAI) ---
    fallback_provider: FallbackProvider = FallbackProvider.NONE
    fallback_base_url: str | None = None  # 예: https://<리소스>.openai.azure.com/openai/v1/
    fallback_api_key: SecretStr | None = None
    fallback_model: str | None = None  # Azure OpenAI는 배포 이름
    # 폴백은 gpt-5 계열 형식(max_completion_tokens·온도 생략)으로 부른다. off면 생각 분량을 보내지 않는다
    fallback_reasoning_effort: Literal["off", "none", "minimal", "low", "medium", "high"] = (
        "minimal"
    )
    fallback_allowed_intents: CommaList = Field(default_factory=lambda: ["faq"])

    # --- 어댑터 선택 ---
    storage_provider: StorageProvider = StorageProvider.LOCAL
    storage_local_dir: Path = REPO_ROOT / "var" / "storage"
    tracer: Tracer = Tracer.PG

    # --- 에이전트 ---
    prompts_dir: Path = REPO_ROOT / "prompts"
    history_turns: int = Field(default=4, ge=0)
    stream_token_delay_ms: int = Field(
        default=0, ge=0
    )  # 토큰 이벤트 사이 지연(타이핑 효과)  # 멀티턴: 최근 N턴(질문+답변 쌍)
    rag_top_k: int = Field(default=4, gt=0)
    rag_vector_weight: float = Field(default=0.7, ge=0, le=1)
    rag_min_score: float = Field(default=0.25, ge=0, le=1)
    entity_fuzzy_threshold: int = Field(default=80, ge=0, le=100)
    inquiry_channel: str = "고객센터(샘플) 1588-0000 · 홈페이지 1:1 문의"
    # 일반 대화 모드(개인용 로컬 전용): ETF 범위 밖 질문·근거 없는 질문에도 LLM이 자유롭게 답한다.
    # 고위험·ETF 추천은 계속 템플릿, 금칙 표현·개인정보 룰 가드는 그대로 적용. APP_ENV=local에서만 허용.
    general_chat_enabled: bool = False
    general_chat_temperature: float = Field(default=0.7, ge=0, le=2)

    # --- 외부 데이터 API ---
    data_go_kr_api_key: SecretStr | None = None
    dart_api_key: SecretStr | None = None
    external_timeout_seconds: float = Field(default=15.0, gt=0)

    @field_validator("cors_origins", "fallback_allowed_intents", "admin_emails", mode="before")
    @classmethod
    def _split_commas(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL은 postgresql+asyncpg:// 스킴이어야 합니다")
        return value

    @model_validator(mode="after")
    def _derive_defaults(self) -> Settings:
        if self.supabase_jwks_url is None and self.supabase_url:
            base = self.supabase_url.rstrip("/")
            self.supabase_jwks_url = f"{base}/auth/v1/.well-known/jwks.json"
        if self.judge_model is None:
            self.judge_model = self.llm_model
        if self.embedding_provider is None:
            self.embedding_provider = self.llm_provider
        if self.embedding_base_url is None:
            self.embedding_base_url = self.llm_base_url
        if self.general_chat_enabled and self.app_env is not AppEnv.LOCAL:
            raise ValueError("GENERAL_CHAT_ENABLED는 APP_ENV=local에서만 켤 수 있습니다")
        if self.local_jwt_secret is None:
            if self.auth_provider is AuthProvider.LOCAL and self.app_env is not AppEnv.LOCAL:
                raise ValueError("APP_ENV가 local이 아니면 LOCAL_JWT_SECRET이 필요합니다")
            self.local_jwt_secret = SecretStr(secrets.token_urlsafe(32))
        return self

    @property
    def judge_model_name(self) -> str:
        return self.judge_model or self.llm_model


@lru_cache
def get_settings() -> Settings:
    """프로세스 전역 설정 싱글턴. 테스트에서는 get_settings.cache_clear()로 초기화한다."""
    return Settings()  # 필수값(DATABASE_URL)은 환경변수/.env에서 채워진다

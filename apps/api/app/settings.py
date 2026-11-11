"""환경변수 기반 애플리케이션 설정. 모든 설정값은 이 모듈에서만 읽는다."""

from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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
    OPENAI_COMPAT = "openai_compat"
    FAKE = "fake"


class FallbackProvider(StrEnum):
    BEDROCK = "bedrock"
    NONE = "none"


class AuthProvider(StrEnum):
    SUPABASE = "supabase"
    COGNITO = "cognito"


class StorageProvider(StrEnum):
    SUPABASE = "supabase"
    S3 = "s3"


class Tracer(StrEnum):
    PG = "pg"
    LANGFUSE = "langfuse"


# 쉼표로 구분된 환경변수 값을 리스트로 받는다(JSON 디코딩 비활성화).
CommaList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # 루트 .env → apps/api/.env 순으로 읽고, 실제 환경변수가 항상 우선한다.
        env_file=("../../.env", ".env"),
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

    # --- Supabase Auth ---
    supabase_url: str | None = None
    supabase_jwks_url: str | None = None
    supabase_jwt_secret: SecretStr | None = None

    # --- LLM ---
    llm_provider: LLMProvider = LLMProvider.OPENAI_COMPAT
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: SecretStr | None = None
    llm_model: str = "qwen3:8b"
    judge_model: str = "qwen3:8b"
    embedding_model: str = "bge-m3"
    embedding_dim: int = Field(default=1024, gt=0)

    # --- LLM 폴백 ---
    fallback_provider: FallbackProvider = FallbackProvider.BEDROCK
    bedrock_region: str = "ap-northeast-2"
    bedrock_model_id: str | None = None
    fallback_allowed_intents: CommaList = Field(default_factory=lambda: ["faq"])

    # --- 어댑터 선택 ---
    auth_provider: AuthProvider = AuthProvider.SUPABASE
    storage_provider: StorageProvider = StorageProvider.SUPABASE
    tracer: Tracer = Tracer.PG

    # --- Cloudflare Access ---
    cf_access_team_domain: str | None = None
    cf_access_aud: str | None = None

    # --- 외부 데이터 API ---
    data_go_kr_api_key: SecretStr | None = None
    dart_api_key: SecretStr | None = None

    @field_validator("cors_origins", "fallback_allowed_intents", mode="before")
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
    def _derive_jwks_url(self) -> Settings:
        if self.supabase_jwks_url is None and self.supabase_url:
            base = self.supabase_url.rstrip("/")
            self.supabase_jwks_url = f"{base}/auth/v1/.well-known/jwks.json"
        return self


@lru_cache
def get_settings() -> Settings:
    """프로세스 전역 설정 싱글턴. 테스트에서는 get_settings.cache_clear()로 초기화한다."""
    return Settings()  # 필수값(DATABASE_URL)은 환경변수/.env에서 채워진다

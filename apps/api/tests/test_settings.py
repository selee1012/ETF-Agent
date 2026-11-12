"""설정 로딩·필수값·Enum 검증."""

import pytest
from pydantic import ValidationError

from app.settings import (
    AdminAuth,
    AppEnv,
    AuthProvider,
    FallbackProvider,
    LLMProvider,
    Settings,
    StorageProvider,
    Tracer,
)

DB_URL = "postgresql+asyncpg://u:p@localhost:5432/db"


def load() -> Settings:
    # .env 파일을 무시하고 환경변수만으로 로딩한다.
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_loads_required_value_and_defaults(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE_URL", DB_URL)

    s = load()

    assert s.database_url == DB_URL
    assert s.app_env is AppEnv.LOCAL
    assert s.llm_provider is LLMProvider.OPENAI_COMPAT
    assert s.fallback_provider is FallbackProvider.NONE
    assert s.auth_provider is AuthProvider.LOCAL
    assert s.admin_auth is AdminAuth.LOCAL
    assert s.storage_provider is StorageProvider.LOCAL
    assert s.judge_model == s.llm_model
    assert s.embedding_provider is s.llm_provider
    assert s.tracer is Tracer.PG
    assert s.embedding_dim == 1024
    assert s.bedrock_region == "ap-northeast-2"
    assert s.fallback_allowed_intents == ["faq"]


def test_missing_database_url_fails(clean_env: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError, match="database_url"):
        load()


def test_rejects_sync_driver_url(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    with pytest.raises(ValidationError, match="asyncpg"):
        load()


@pytest.mark.parametrize(
    ("env", "value", "field", "expected"),
    [
        ("LLM_PROVIDER", "fake", "llm_provider", LLMProvider.FAKE),
        ("LLM_PROVIDER", "bedrock", "llm_provider", LLMProvider.BEDROCK),
        ("FALLBACK_PROVIDER", "bedrock", "fallback_provider", FallbackProvider.BEDROCK),
        ("ADMIN_AUTH", "cf_access", "admin_auth", AdminAuth.CF_ACCESS),
        ("AUTH_PROVIDER", "cognito", "auth_provider", AuthProvider.COGNITO),
        ("STORAGE_PROVIDER", "s3", "storage_provider", StorageProvider.S3),
        ("TRACER", "langfuse", "tracer", Tracer.LANGFUSE),
        ("APP_ENV", "dev", "app_env", AppEnv.DEV),
    ],
)
def test_parses_adapter_enums(
    clean_env: pytest.MonkeyPatch, env: str, value: str, field: str, expected: object
) -> None:
    clean_env.setenv("DATABASE_URL", DB_URL)
    clean_env.setenv("LOCAL_JWT_SECRET", "x" * 32)
    clean_env.setenv(env, value)

    assert getattr(load(), field) is expected


@pytest.mark.parametrize(
    ("env", "value"),
    [
        ("LLM_PROVIDER", "openai"),
        ("FALLBACK_PROVIDER", "vertex"),
        ("AUTH_PROVIDER", "auth0"),
        ("ADMIN_AUTH", "basic"),
        ("STORAGE_PROVIDER", "gcs"),
        ("TRACER", "datadog"),
        ("APP_ENV", "staging"),
        ("LOG_LEVEL", "TRACE"),
    ],
)
def test_rejects_unknown_enum_values(clean_env: pytest.MonkeyPatch, env: str, value: str) -> None:
    clean_env.setenv("DATABASE_URL", DB_URL)
    clean_env.setenv(env, value)

    with pytest.raises(ValidationError):
        load()


def test_comma_separated_lists(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE_URL", DB_URL)
    clean_env.setenv("CORS_ORIGINS", "http://localhost:5173, https://etf.pages.dev")
    clean_env.setenv("FALLBACK_ALLOWED_INTENTS", "faq,glossary")

    s = load()

    assert s.cors_origins == ["http://localhost:5173", "https://etf.pages.dev"]
    assert s.fallback_allowed_intents == ["faq", "glossary"]


def test_empty_values_fall_back_to_defaults(clean_env: pytest.MonkeyPatch) -> None:
    # .env.example을 그대로 복사하면 빈 값이 들어오므로 기본값으로 처리돼야 한다.
    clean_env.setenv("DATABASE_URL", DB_URL)
    clean_env.setenv("LLM_PROVIDER", "")
    clean_env.setenv("EMBEDDING_DIM", "")

    s = load()

    assert s.llm_provider is LLMProvider.OPENAI_COMPAT
    assert s.embedding_dim == 1024


def test_jwks_url_derived_from_supabase_url(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE_URL", DB_URL)
    clean_env.setenv("SUPABASE_URL", "https://abc.supabase.co/")

    assert load().supabase_jwks_url == "https://abc.supabase.co/auth/v1/.well-known/jwks.json"


def test_secrets_are_masked(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE_URL", DB_URL)
    clean_env.setenv("DART_API_KEY", "dummy-value")

    s = load()

    assert "dummy-value" not in repr(s)
    assert s.dart_api_key is not None
    assert s.dart_api_key.get_secret_value() == "dummy-value"


def test_non_local_env_requires_jwt_secret(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE_URL", DB_URL)
    clean_env.setenv("APP_ENV", "prod")
    with pytest.raises(ValidationError, match="LOCAL_JWT_SECRET"):
        load()


def test_judge_model_defaults_to_llm_model(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE_URL", DB_URL)
    clean_env.setenv("LLM_MODEL", "qwen3:4b")
    assert load().judge_model_name == "qwen3:4b"
    clean_env.setenv("JUDGE_MODEL", "judge-x")
    assert load().judge_model_name == "judge-x"

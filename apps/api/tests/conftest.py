"""공용 fixture.

- make test가 넘긴 TEST_DATABASE_URL(없으면 DATABASE_URL)의 DB 이름 뒤에 _test를 붙인 DB를
  세션마다 새로 만들고 Alembic 마이그레이션 → 샘플 시드 → 샘플 문서 ingest(fake 임베딩)를 한다.
- LLM_PROVIDER=fake, EMBEDDING_PROVIDER=fake로 고정한다.
"""

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine

API_DIR = Path(__file__).resolve().parents[1]


def _test_db_url() -> str:
    base = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not base:
        raise RuntimeError("TEST_DATABASE_URL 또는 DATABASE_URL이 필요합니다(make test 사용)")
    url = make_url(base)
    name = url.database or "etf_agent"
    if not name.endswith("_test"):
        url = url.set(database=f"{name}_test")
    return url.render_as_string(hide_password=False)


TEST_DB_URL = _test_db_url()
# 앱 설정을 테스트 환경으로 고정(.env 값보다 환경변수가 우선한다)
os.environ.update(
    {
        "DATABASE_URL": TEST_DB_URL,
        "APP_ENV": "local",
        "LLM_PROVIDER": "fake",
        "EMBEDDING_PROVIDER": "fake",
        "AUTH_PROVIDER": "local",
        "ADMIN_AUTH": "local",
        "STORAGE_PROVIDER": "local",
        "TRACER": "pg",
        "FALLBACK_PROVIDER": "none",
        "LOCAL_JWT_SECRET": "test-only-secret-" + uuid.uuid4().hex,
        "ADMIN_EMAILS": "admin@local.test",
        "CORS_ORIGINS": "http://localhost:5173",
        "STREAM_TOKEN_DELAY_MS": "0",
        "LOG_LEVEL": "WARNING",
    }
)

# .env·.env.local(개인 설정)의 값이 테스트에 섞이지 않도록 dotenv 파일을 읽지 않는다.
from app.settings import Settings as _Settings  # noqa: E402

_Settings.model_config["env_file"] = ()

from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app import cache  # noqa: E402
from app.agents.state import AgentDeps  # noqa: E402
from app.db import dispose_engine, get_sessionmaker  # noqa: E402
from app.llm.fake import FakeEmbedder, FakeLLM  # noqa: E402
from app.main import create_app  # noqa: E402
from app.settings import Settings, get_settings  # noqa: E402


async def _recreate_database() -> None:
    url = make_url(TEST_DB_URL)
    admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
            await conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        await admin.dispose()


@pytest.fixture(scope="session", autouse=True)
async def database(tmp_path_factory: pytest.TempPathFactory) -> AsyncIterator[None]:
    os.environ["STORAGE_LOCAL_DIR"] = str(tmp_path_factory.mktemp("storage"))
    get_settings.cache_clear()
    await _recreate_database()
    subprocess.run(  # noqa: ASYNC221 (세션 시작 시 1회 마이그레이션)
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_DIR,
        env={**os.environ},
        check=True,
        capture_output=True,
    )
    from jobs.ingest import ingest_paths
    from jobs.seed import SAMPLES_DIR, run

    maker = get_sessionmaker()
    await run(maker)
    settings = get_settings()
    await ingest_paths(maker, FakeEmbedder(dim=settings.embedding_dim), SAMPLES_DIR / "docs")
    await dispose_engine()
    yield
    await dispose_engine()


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    cache.clear_all()


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Settings 필드에 해당하는 환경변수를 모두 지워 테스트를 외부 환경과 격리한다."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    return monkeypatch


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def fake_llm(settings: Settings) -> FakeLLM:
    return FakeLLM(model="fake-test")


@pytest.fixture
def deps(settings: Settings, fake_llm: FakeLLM) -> AgentDeps:
    return AgentDeps(
        settings=settings,
        llm=fake_llm,
        embedder=FakeEmbedder(dim=settings.embedding_dim),
        maker=get_sessionmaker(),
    )


@pytest.fixture
async def app(settings: Settings, fake_llm: FakeLLM) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    application.state.container.llm = fake_llm
    yield application
    await dispose_engine()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def login(client: AsyncClient, email: str = "user@local.test") -> dict[str, str]:
    resp = await client.post("/auth/dev-login", json={"email": email})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def user_headers(client: AsyncClient) -> dict[str, str]:
    return await login(client, f"user-{uuid.uuid4().hex[:8]}@local.test")


@pytest.fixture
async def admin_headers(client: AsyncClient) -> dict[str, str]:
    return await login(client, "admin@local.test")

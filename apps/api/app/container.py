"""어댑터 조립. settings의 Enum 값으로만 구현체를 고른다"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import AdminVerifier, AuthBackend, build_admin_verifier, build_auth
from app.db import get_sessionmaker
from app.llm import build_embedder, build_llm
from app.llm.base import Embedder, LLMClient
from app.observability import Tracer, build_tracer
from app.settings import Settings
from app.storage import Storage, build_storage


@dataclass(slots=True)
class Container:
    settings: Settings
    maker: async_sessionmaker[AsyncSession]
    llm: LLMClient
    embedder: Embedder
    auth: AuthBackend
    admin_verifier: AdminVerifier
    storage: Storage
    tracer: Tracer


def build_container(settings: Settings) -> Container:
    maker = get_sessionmaker()
    return Container(
        settings=settings,
        maker=maker,
        llm=build_llm(settings),
        embedder=build_embedder(settings),
        auth=build_auth(settings),
        admin_verifier=build_admin_verifier(settings),
        storage=build_storage(settings),
        tracer=build_tracer(settings, maker),
    )

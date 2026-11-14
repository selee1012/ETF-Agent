"""SQLAlchemy async 엔진·세션 팩토리와 FastAPI 세션 의존성."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.settings import get_settings


class Base(DeclarativeBase):
    """모든 ORM 모델의 베이스. Alembic autogenerate가 이 metadata를 본다."""


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_recycle=1800,
        # SQLAlchemy가 DB 오류 메시지에 붙이는 바인드 값 목록(대화 내용·검색 질의)을 뺀다.
        # 드라이버가 주는 DETAIL(중복 키 값 등)까지 가리지는 않는다.
        hide_parameters=True,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """요청 단위 세션. 커밋은 호출 측(리포지토리/서비스)이 명시적으로 한다."""
    async with get_sessionmaker()() as session:
        yield session


async def dispose_engine() -> None:
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()

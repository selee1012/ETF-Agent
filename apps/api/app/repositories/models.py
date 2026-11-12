"""SQLAlchemy ORM 모델. # P1-DA-01

traces 테이블에는 질의 원문 컬럼을 두지 않는다(공통 규칙 4).
messages·feedback의 텍스트는 privacy.mask_pii()를 거친 값만 저장한다.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.settings import get_settings


def _embedding_dim() -> int:
    return get_settings().embedding_dim


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EtfMaster(Base):
    __tablename__ = "etf_master"

    ticker: Mapped[str] = mapped_column(String(12), primary_key=True)  # 종목코드
    isin: Mapped[str | None] = mapped_column(String(12), unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}", nullable=False)
    # 이름·별칭을 공백으로 이은 검색용 텍스트(trgm 인덱스 대상, 앱이 유지)
    alias_text: Mapped[str] = mapped_column(Text, server_default="", nullable=False)
    issuer: Mapped[str | None] = mapped_column(Text)  # 운용사
    underlying_index: Mapped[str | None] = mapped_column(Text)  # 기초지수
    total_expense_ratio: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))  # 총보수(%, 연)
    category: Mapped[str | None] = mapped_column(Text)  # 분류
    listed_date: Mapped[date | None] = mapped_column(Date)  # 상장일
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), server_default="sample", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PriceDaily(Base):
    __tablename__ = "prices_daily"

    ticker: Mapped[str] = mapped_column(
        ForeignKey("etf_master.ticker", ondelete="CASCADE"), primary_key=True
    )
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    close_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # 종가(원)
    nav: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # 순자산가치(원)
    premium_discount: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))  # 괴리율(%)
    volume: Mapped[int | None] = mapped_column(BigInteger)  # 거래량(주)
    net_assets: Mapped[int | None] = mapped_column(BigInteger)  # 순자산총액(원)
    source: Mapped[str] = mapped_column(String(32), server_default="sample", nullable=False)


class Disclosure(TimestampMixin, Base):
    __tablename__ = "disclosures"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str | None] = mapped_column(
        ForeignKey("etf_master.ticker", ondelete="SET NULL"), index=True
    )
    constituent_name: Mapped[str | None] = mapped_column(Text)  # 구성종목 공시일 때 종목명
    title: Mapped[str] = mapped_column(Text, nullable=False)
    disclosed_at: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    url: Mapped[str | None] = mapped_column(Text)  # 원문 URL
    summary: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), server_default="sample", nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(64), unique=True)  # DART rcept_no 등


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_uri: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # 저장소 키·경로
    title: Mapped[str] = mapped_column(Text, nullable=False)
    doc_type: Mapped[str] = mapped_column(String(32), server_default="faq", nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class Chunk(TimestampMixin, Base):
    __tablename__ = "chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(_embedding_dim()), nullable=False)
    # 출처 메타: 문서명, 섹션(heading), 페이지 등
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}", nullable=False)

    document: Mapped[Document] = relationship(back_populates="chunks")


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), server_default="user", nullable=False)


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)  # 마스킹된 첫 질문 일부
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Message(TimestampMixin, Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)  # mask_pii() 적용 후
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    intent: Mapped[str | None] = mapped_column(Text)
    guard_verdict: Mapped[str | None] = mapped_column(String(32))
    sources: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default="[]", nullable=False
    )
    # 멀티턴용 메타(인식 엔티티 티커, 설명 수준 등). 원문은 넣지 않는다.
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}", nullable=False)


class Feedback(TimestampMixin, Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), index=True
    )
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # like | dislike | correction
    correction_text: Mapped[str | None] = mapped_column(Text)  # mask_pii() 적용 후


class Trace(TimestampMixin, Base):
    """요청 1건당 1행. 질의 원문 컬럼은 의도적으로 없다. # P1-OP-01"""

    __tablename__ = "traces"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    intent: Mapped[str | None] = mapped_column(Text, index=True)
    agents: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}", nullable=False)
    retrieved_doc_ids: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default="{}", nullable=False
    )
    guard_verdict: Mapped[str | None] = mapped_column(String(32), index=True)
    guard_reasons: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default="{}", nullable=False
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    model: Mapped[str | None] = mapped_column(Text)
    fallback_used: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)

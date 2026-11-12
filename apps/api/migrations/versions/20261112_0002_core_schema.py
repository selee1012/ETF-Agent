"""core schema: pg_trgm, ETF·문서·대화·트레이스 테이블 # P1-DA-01

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-12

chunks.embedding 차원은 마이그레이션 시점의 EMBEDDING_DIM을 따른다.
임베딩 모델을 차원이 다른 것으로 바꾸면 새 마이그레이션으로 컬럼을 바꾸고 다시 ingest 한다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql as pg

from app.settings import get_settings

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _updated() -> sa.Column:
    return sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    dim = get_settings().embedding_dim
    if op.get_context().as_sql:
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    else:
        has_extensions_schema = (
            op.get_bind()
            .execute(sa.text("SELECT 1 FROM pg_namespace WHERE nspname = 'extensions'"))
            .scalar()
        )
        schema = " WITH SCHEMA extensions" if has_extensions_schema else ""
        op.execute(f"CREATE EXTENSION IF NOT EXISTS pg_trgm{schema}")

    op.create_table(
        "etf_master",
        sa.Column("ticker", sa.String(12), primary_key=True),
        sa.Column("isin", sa.String(12), unique=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("aliases", pg.ARRAY(sa.Text), server_default="{}", nullable=False),
        sa.Column("alias_text", sa.Text, server_default="", nullable=False),
        sa.Column("issuer", sa.Text),
        sa.Column("underlying_index", sa.Text),
        sa.Column("total_expense_ratio", sa.Numeric(6, 4)),
        sa.Column("category", sa.Text),
        sa.Column("listed_date", sa.Date),
        sa.Column("description", sa.Text),
        sa.Column("source", sa.String(32), server_default="sample", nullable=False),
        _updated(),
    )
    op.execute("CREATE INDEX ix_etf_master_name_trgm ON etf_master USING gin (name gin_trgm_ops)")
    op.execute(
        "CREATE INDEX ix_etf_master_alias_trgm ON etf_master USING gin (alias_text gin_trgm_ops)"
    )
    op.create_index("ix_etf_master_category", "etf_master", ["category"])

    op.create_table(
        "prices_daily",
        sa.Column(
            "ticker",
            sa.String(12),
            sa.ForeignKey("etf_master.ticker", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("trade_date", sa.Date, primary_key=True),
        sa.Column("close_price", sa.Numeric(14, 2)),
        sa.Column("nav", sa.Numeric(14, 2)),
        sa.Column("premium_discount", sa.Numeric(8, 4)),
        sa.Column("volume", sa.BigInteger),
        sa.Column("net_assets", sa.BigInteger),
        sa.Column("source", sa.String(32), server_default="sample", nullable=False),
    )
    op.create_index("ix_prices_daily_trade_date", "prices_daily", ["trade_date"])

    op.create_table(
        "disclosures",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(12), sa.ForeignKey("etf_master.ticker", ondelete="SET NULL")),
        sa.Column("constituent_name", sa.Text),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("disclosed_at", sa.Date, nullable=False),
        sa.Column("url", sa.Text),
        sa.Column("summary", sa.Text),
        sa.Column("source", sa.String(32), server_default="sample", nullable=False),
        sa.Column("external_id", sa.String(64), unique=True),
        _ts(),
    )
    op.create_index("ix_disclosures_ticker", "disclosures", ["ticker"])
    op.create_index("ix_disclosures_disclosed_at", "disclosures", ["disclosed_at"])

    op.create_table(
        "documents",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source_uri", sa.Text, unique=True, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("doc_type", sa.String(32), server_default="faq", nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding_model", sa.Text, nullable=False),
        sa.Column("meta", pg.JSONB, server_default="{}", nullable=False),
        _ts(),
        _updated(),
    )

    op.create_table(
        "chunks",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "document_id",
            sa.BigInteger,
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", Vector(dim), nullable=False),
        sa.Column("meta", pg.JSONB, server_default="{}", nullable=False),
        _ts(),
        sa.UniqueConstraint("document_id", "chunk_index"),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    # 코사인 거리 HNSW(데이터가 적어도 바로 쓸 수 있고 재학습이 필요 없다)
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute("CREATE INDEX ix_chunks_content_trgm ON chunks USING gin (content gin_trgm_ops)")

    op.create_table(
        "users",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.Text, unique=True, nullable=False),
        sa.Column("role", sa.String(16), server_default="user", nullable=False),
        _ts(),
    )

    op.create_table(
        "conversations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text, nullable=False),
        _ts(),
        _updated(),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])

    op.create_table(
        "messages",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("request_id", sa.String(64)),
        sa.Column("intent", sa.Text),
        sa.Column("guard_verdict", sa.String(32)),
        sa.Column("sources", pg.JSONB, server_default="[]", nullable=False),
        sa.Column("meta", pg.JSONB, server_default="{}", nullable=False),
        _ts(),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_request_id", "messages", ["request_id"])

    op.create_table(
        "feedback",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "message_id", pg.UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="SET NULL")
        ),
        sa.Column("request_id", sa.String(64)),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("correction_text", sa.Text),
        _ts(),
        sa.CheckConstraint("kind IN ('like', 'dislike', 'correction')", name="ck_feedback_kind"),
    )
    op.create_index("ix_feedback_message_id", "feedback", ["message_id"])
    op.create_index("ix_feedback_request_id", "feedback", ["request_id"])
    op.create_index("ix_feedback_user_id", "feedback", ["user_id"])

    # P1-OP-01 질의 원문 컬럼 없음
    op.create_table(
        "traces",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(64), unique=True, nullable=False),
        sa.Column("user_id", pg.UUID(as_uuid=True)),
        sa.Column("intent", sa.Text),
        sa.Column("agents", pg.ARRAY(sa.Text), server_default="{}", nullable=False),
        sa.Column("retrieved_doc_ids", pg.ARRAY(sa.Text), server_default="{}", nullable=False),
        sa.Column("guard_verdict", sa.String(32)),
        sa.Column("guard_reasons", pg.ARRAY(sa.Text), server_default="{}", nullable=False),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("model", sa.Text),
        sa.Column("fallback_used", sa.Boolean, server_default="false", nullable=False),
        _ts(),
    )
    op.create_index("ix_traces_user_id", "traces", ["user_id"])
    op.create_index("ix_traces_intent", "traces", ["intent"])
    op.create_index("ix_traces_guard_verdict", "traces", ["guard_verdict"])
    op.create_index("ix_traces_created_at", "traces", ["created_at"])


def downgrade() -> None:
    for table in (
        "traces",
        "feedback",
        "messages",
        "conversations",
        "users",
        "chunks",
        "documents",
        "disclosures",
        "prices_daily",
        "etf_master",
    ):
        op.drop_table(table)
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")

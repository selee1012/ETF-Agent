"""enable pgvector extension

Revision ID: 0001
Revises:
Create Date: 2026-11-11

Supabase는 확장을 `extensions` 스키마에 두는 것이 권장이므로, 그 스키마가 있으면 거기에 만들고
없으면(로컬 pgvector 컨테이너·CI) 기본 스키마에 만든다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_context().as_sql:  # 오프라인(--sql) 모드는 DB 조회가 불가하므로 기본 스키마로 출력
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        return
    has_extensions_schema = (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM pg_namespace WHERE nspname = 'extensions'"))
        .scalar()
    )
    if has_extensions_schema:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions")
    else:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")

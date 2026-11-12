"""users.level: 사용자가 처음 로그인할 때 고르는 설명 수준 # P1-API-01

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-12

NULL이면 아직 고르지 않은 상태(웹이 온보딩 화면을 띄운다). 값: beginner | intermediate | expert
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("level", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "level")

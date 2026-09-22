"""얼굴 인증 임베딩 저장 테이블을 추가합니다.

Revision ID: 20260804_0012
Revises: 20260804_0011
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0012"
down_revision: str | None = "20260804_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_face_credentials",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade() -> None:
    op.drop_table("user_face_credentials")

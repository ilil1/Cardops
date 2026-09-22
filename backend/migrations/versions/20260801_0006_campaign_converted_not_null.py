"""Make campaign target conversion state mandatory.

Revision ID: 20260801_0006
Revises: 20260801_0005
Create Date: 2026-08-01
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260801_0006"
down_revision: str | None = "20260801_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _converted_nullable() -> bool:
    column = next(
        column
        for column in sa.inspect(op.get_bind()).get_columns("campaign_targets")
        if column["name"] == "converted"
    )
    return bool(column["nullable"])


def upgrade() -> None:
    """NULL 전환 상태를 false로 보정하고 필수 boolean으로 고정합니다."""
    op.execute(
        sa.text(
            "UPDATE campaign_targets SET converted = 0 WHERE converted IS NULL"
        )
    )
    if not _converted_nullable():
        return
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("campaign_targets") as batch_op:
            batch_op.alter_column(
                "converted",
                existing_type=sa.Boolean(),
                existing_nullable=True,
                existing_server_default=sa.text("0"),
                nullable=False,
            )
    else:
        op.alter_column(
            "campaign_targets",
            "converted",
            existing_type=sa.Boolean(),
            existing_nullable=True,
            existing_server_default=sa.text("0"),
            nullable=False,
        )


def downgrade() -> None:
    """전환 상태를 다시 nullable로 되돌립니다."""
    if not _converted_nullable():
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table("campaign_targets") as batch_op:
                batch_op.alter_column(
                    "converted",
                    existing_type=sa.Boolean(),
                    existing_nullable=False,
                    existing_server_default=sa.text("0"),
                    nullable=True,
                )
        else:
            op.alter_column(
                "campaign_targets",
                "converted",
                existing_type=sa.Boolean(),
                existing_nullable=False,
                existing_server_default=sa.text("0"),
                nullable=True,
            )

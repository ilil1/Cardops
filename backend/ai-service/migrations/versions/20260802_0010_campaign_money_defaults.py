"""Restore monetary server defaults after the MySQL decimal conversion.

Revision ID: 20260802_0010
Revises: 20260802_0009
Create Date: 2026-08-02
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql.elements import TextClause


revision: str = "20260802_0010"
down_revision: str | None = "20260802_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


MONEY_COLUMNS = (
    "fixed_cost",
    "cost_per_contact",
    "revenue_per_conversion",
)


def _set_defaults(server_default: TextClause | None) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("campaigns") as batch_op:
            for column_name in MONEY_COLUMNS:
                batch_op.alter_column(
                    column_name,
                    existing_type=sa.Numeric(18, 2),
                    existing_nullable=False,
                    server_default=server_default,
                )
        return

    for column_name in MONEY_COLUMNS:
        op.alter_column(
            "campaigns",
            column_name,
            existing_type=sa.Numeric(18, 2),
            existing_nullable=False,
            server_default=server_default,
        )


def upgrade() -> None:
    _set_defaults(sa.text("0"))


def downgrade() -> None:
    _set_defaults(None)

"""Add experiment groups, outcome timestamps, retention, and campaign economics.

Revision ID: 20260801_0008
Revises: 20260801_0007
Create Date: 2026-08-01
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260801_0008"
down_revision: str | None = "20260801_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_column(table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name
        for column in _inspector().get_columns(table_name)
    )


def _has_index(table_name: str, index_name: str) -> bool:
    return any(
        index.get("name") == index_name
        for index in _inspector().get_indexes(table_name)
    )


def _has_check(table_name: str, constraint_name: str) -> bool:
    return any(
        constraint.get("name") == constraint_name
        for constraint in _inspector().get_check_constraints(table_name)
    )


def _add_campaign_columns() -> None:
    columns = (
        sa.Column("segment_code", sa.String(length=40), nullable=True),
        sa.Column(
            "experiment_enabled",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "control_group_ratio",
            sa.Float(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("experiment_seed", sa.String(length=64), nullable=True),
        sa.Column(
            "fixed_cost",
            sa.Float(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "cost_per_contact",
            sa.Float(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "revenue_per_conversion",
            sa.Float(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "retention_window_days",
            sa.Integer(),
            server_default=sa.text("30"),
            nullable=False,
        ),
    )
    for column in columns:
        if not _has_column("campaigns", column.name):
            op.add_column("campaigns", column)
    if not _has_index("campaigns", "ix_campaigns_segment"):
        op.create_index(
            "ix_campaigns_segment",
            "campaigns",
            ["segment_code"],
            unique=False,
        )


def _add_target_columns() -> None:
    columns = (
        sa.Column(
            "experiment_group",
            sa.String(length=20),
            server_default=sa.text("'treatment'"),
            nullable=False,
        ),
        sa.Column("contacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retained", sa.Boolean(), nullable=True),
        sa.Column(
            "retention_checked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("outcome_revenue", sa.Float(), nullable=True),
    )
    for column in columns:
        if not _has_column("campaign_targets", column.name):
            op.add_column("campaign_targets", column)


def _replace_target_checks() -> None:
    """기존 결과 코드 제약을 확장하고 A/B 그룹 제약을 추가합니다."""
    bind = op.get_bind()
    dialect = bind.dialect.name
    result_sql = (
        "result_code IS NULL OR result_code IN "
        "('contacted', 'converted', 'not_converted', 'no_response', "
        "'declined', 'opted_out', 'invalid_contact')"
    )
    group_sql = "experiment_group IN ('treatment', 'control')"
    if dialect == "sqlite":
        with op.batch_alter_table("campaign_targets") as batch_op:
            if _has_check("campaign_targets", "ck_campaign_targets_result_code"):
                batch_op.drop_constraint(
                    "ck_campaign_targets_result_code",
                    type_="check",
                )
            batch_op.create_check_constraint(
                "ck_campaign_targets_result_code",
                result_sql,
            )
            if not _has_check(
                "campaign_targets",
                "ck_campaign_targets_experiment_group",
            ):
                batch_op.create_check_constraint(
                    "ck_campaign_targets_experiment_group",
                    group_sql,
                )
        return

    if _has_check("campaign_targets", "ck_campaign_targets_result_code"):
        op.drop_constraint(
            "ck_campaign_targets_result_code",
            "campaign_targets",
            type_="check",
        )
    op.create_check_constraint(
        "ck_campaign_targets_result_code",
        "campaign_targets",
        result_sql,
    )
    if not _has_check("campaign_targets", "ck_campaign_targets_experiment_group"):
        op.create_check_constraint(
            "ck_campaign_targets_experiment_group",
            "campaign_targets",
            group_sql,
        )


def upgrade() -> None:
    """성과 측정에 필요한 A/B 배정·유지·비용 구조를 추가합니다."""
    _add_campaign_columns()
    _add_target_columns()
    _replace_target_checks()


def downgrade() -> None:
    """성과 측정 확장을 역순으로 제거합니다."""
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("campaign_targets") as batch_op:
            if _has_check("campaign_targets", "ck_campaign_targets_experiment_group"):
                batch_op.drop_constraint(
                    "ck_campaign_targets_experiment_group",
                    type_="check",
                )
            if _has_check("campaign_targets", "ck_campaign_targets_result_code"):
                batch_op.drop_constraint(
                    "ck_campaign_targets_result_code",
                    type_="check",
                )
            batch_op.create_check_constraint(
                "ck_campaign_targets_result_code",
                "result_code IS NULL OR result_code IN "
                "('converted', 'not_converted', 'no_response', 'declined', "
                "'invalid_contact')",
            )
            for name in (
                "outcome_revenue",
                "retention_checked_at",
                "retained",
                "converted_at",
                "completed_at",
                "contacted_at",
                "experiment_group",
            ):
                if _has_column("campaign_targets", name):
                    batch_op.drop_column(name)
    else:
        if _has_check("campaign_targets", "ck_campaign_targets_experiment_group"):
            op.drop_constraint(
                "ck_campaign_targets_experiment_group",
                "campaign_targets",
                type_="check",
            )
        if _has_check("campaign_targets", "ck_campaign_targets_result_code"):
            op.drop_constraint(
                "ck_campaign_targets_result_code",
                "campaign_targets",
                type_="check",
            )
        op.create_check_constraint(
            "ck_campaign_targets_result_code",
            "campaign_targets",
            "result_code IS NULL OR result_code IN "
            "('converted', 'not_converted', 'no_response', 'declined', "
            "'invalid_contact')",
        )
        for name in (
            "outcome_revenue",
            "retention_checked_at",
            "retained",
            "converted_at",
            "completed_at",
            "contacted_at",
            "experiment_group",
        ):
            if _has_column("campaign_targets", name):
                op.drop_column("campaign_targets", name)

    if _has_index("campaigns", "ix_campaigns_segment"):
        op.drop_index("ix_campaigns_segment", table_name="campaigns")
    for name in (
        "retention_window_days",
        "revenue_per_conversion",
        "cost_per_contact",
        "fixed_cost",
        "experiment_seed",
        "control_group_ratio",
        "experiment_enabled",
        "segment_code",
    ):
        if _has_column("campaigns", name):
            op.drop_column("campaigns", name)

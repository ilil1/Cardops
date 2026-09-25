"""Add customer contact preferences and segment bulk targeting runs.

Revision ID: 20260801_0007
Revises: 20260801_0006
Create Date: 2026-08-01
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260801_0007"
down_revision: str | None = "20260801_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return _inspector().has_table(table_name)


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


def _has_foreign_key(table_name: str, constraint_name: str) -> bool:
    return any(
        foreign_key.get("name") == constraint_name
        for foreign_key in _inspector().get_foreign_keys(table_name)
    )


def _add_customer_contact_columns() -> None:
    """수신 거부는 보수적인 기본값으로, 접촉 시각은 미확인으로 backfill합니다."""
    if not _has_column("customers", "marketing_opt_out"):
        op.add_column(
            "customers",
            sa.Column(
                "marketing_opt_out",
                sa.Boolean(),
                server_default=sa.text("0"),
                nullable=False,
            ),
        )
    if not _has_column("customers", "last_contacted_at"):
        op.add_column(
            "customers",
            sa.Column("last_contacted_at", sa.DateTime(timezone=True), nullable=True),
        )


def _create_bulk_targeting_runs() -> None:
    if not _has_table("bulk_targeting_runs"):
        op.create_table(
            "bulk_targeting_runs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("segment_code", sa.String(length=40), nullable=False),
            sa.Column(
                "status",
                sa.String(length=20),
                server_default=sa.text("'previewed'"),
                nullable=False,
            ),
            sa.Column("campaign_id", sa.Integer(), nullable=True),
            sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
            sa.Column("rerun_of_id", sa.Integer(), nullable=True),
            sa.Column("source_as_of_date", sa.Date(), nullable=True),
            sa.Column("rules_json", sa.JSON(), nullable=False),
            sa.Column("preview_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column("eligible_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column("created_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column(
                "skipped_active_campaign_count",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            ),
            sa.Column(
                "skipped_recent_contact_count",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            ),
            sa.Column(
                "skipped_opt_out_count",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            ),
            sa.Column(
                "cancelled_target_count",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "segment_code IN ('high_risk_retention', 'medium_reactivation', "
                "'low_risk_upsell')",
                name="ck_bulk_targeting_runs_segment",
            ),
            sa.CheckConstraint(
                "status IN ('previewed', 'executed', 'cancelled')",
                name="ck_bulk_targeting_runs_status",
            ),
            sa.ForeignKeyConstraint(
                ["campaign_id"],
                ["campaigns.id"],
                name="fk_bulk_targeting_runs_campaign",
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["requested_by_user_id"],
                ["users.id"],
                name="fk_bulk_targeting_runs_requested_by_user",
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["rerun_of_id"],
                ["bulk_targeting_runs.id"],
                name="fk_bulk_targeting_runs_rerun_of",
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_bulk_targeting_runs"),
        )

    if not _has_index("bulk_targeting_runs", "ix_bulk_targeting_runs_status_created"):
        op.create_index(
            "ix_bulk_targeting_runs_status_created",
            "bulk_targeting_runs",
            ["status", "created_at"],
            unique=False,
        )
    if not _has_index("bulk_targeting_runs", "ix_bulk_targeting_runs_campaign"):
        op.create_index(
            "ix_bulk_targeting_runs_campaign",
            "bulk_targeting_runs",
            ["campaign_id"],
            unique=False,
        )
    if not _has_index("bulk_targeting_runs", "ix_bulk_targeting_runs_rerun_of"):
        op.create_index(
            "ix_bulk_targeting_runs_rerun_of",
            "bulk_targeting_runs",
            ["rerun_of_id"],
            unique=False,
        )


def _add_target_run_column() -> None:
    if _has_column("campaign_targets", "bulk_targeting_run_id"):
        return
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("campaign_targets") as batch_op:
            batch_op.add_column(
                sa.Column("bulk_targeting_run_id", sa.Integer(), nullable=True)
            )
            batch_op.create_foreign_key(
                "fk_campaign_targets_bulk_targeting_run",
                "bulk_targeting_runs",
                ["bulk_targeting_run_id"],
                ["id"],
                ondelete="SET NULL",
            )
    else:
        op.add_column(
            "campaign_targets",
            sa.Column("bulk_targeting_run_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            "fk_campaign_targets_bulk_targeting_run",
            "campaign_targets",
            "bulk_targeting_runs",
            ["bulk_targeting_run_id"],
            ["id"],
            ondelete="SET NULL",
        )

    if not _has_index("campaign_targets", "ix_campaign_targets_bulk_targeting_run"):
        op.create_index(
            "ix_campaign_targets_bulk_targeting_run",
            "campaign_targets",
            ["bulk_targeting_run_id", "status"],
            unique=False,
        )


def upgrade() -> None:
    """고객 접촉 정책과 세그먼트 일괄 타기팅 배치 구조를 추가합니다."""
    _add_customer_contact_columns()
    _create_bulk_targeting_runs()
    _add_target_run_column()


def downgrade() -> None:
    """일괄 타기팅 구조를 역순으로 제거합니다."""
    if _has_index("campaign_targets", "ix_campaign_targets_bulk_targeting_run"):
        op.drop_index(
            "ix_campaign_targets_bulk_targeting_run",
            table_name="campaign_targets",
        )
    if _has_column("campaign_targets", "bulk_targeting_run_id"):
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table("campaign_targets") as batch_op:
                if _has_foreign_key(
                    "campaign_targets",
                    "fk_campaign_targets_bulk_targeting_run",
                ):
                    batch_op.drop_constraint(
                        "fk_campaign_targets_bulk_targeting_run",
                        type_="foreignkey",
                    )
                batch_op.drop_column("bulk_targeting_run_id")
        else:
            if _has_foreign_key(
                "campaign_targets",
                "fk_campaign_targets_bulk_targeting_run",
            ):
                op.drop_constraint(
                    "fk_campaign_targets_bulk_targeting_run",
                    "campaign_targets",
                    type_="foreignkey",
                )
            op.drop_column("campaign_targets", "bulk_targeting_run_id")

    if _has_table("bulk_targeting_runs"):
        for index_name in (
            "ix_bulk_targeting_runs_rerun_of",
            "ix_bulk_targeting_runs_campaign",
            "ix_bulk_targeting_runs_status_created",
        ):
            if _has_index("bulk_targeting_runs", index_name):
                op.drop_index(index_name, table_name="bulk_targeting_runs")
        op.drop_table("bulk_targeting_runs")

    for column_name in ("last_contacted_at", "marketing_opt_out"):
        if _has_column("customers", column_name):
            op.drop_column("customers", column_name)

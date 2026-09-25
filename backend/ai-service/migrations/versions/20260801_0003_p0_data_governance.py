"""Add approval defaults, policy lineage, and customer feature snapshots.

Revision ID: 20260801_0003
Revises: 20260801_0002
Create Date: 2026-08-01
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260801_0003"
down_revision: str | None = "20260801_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector():
    """현재 연결에서 부분 적용된 DDL도 안전하게 확인합니다."""
    return sa.inspect(op.get_bind())


def _has_column(table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name
        for column in _inspector().get_columns(table_name)
    )


def _has_foreign_key(table_name: str, constraint_name: str) -> bool:
    return any(
        foreign_key.get("name") == constraint_name
        for foreign_key in _inspector().get_foreign_keys(table_name)
    )


def _alter_user_defaults(*, role_default: str, active_default: str) -> None:
    """기존 행은 보존하고 이후 직접 생성되는 계정의 기본값만 변경합니다."""
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("users") as batch_op:
            batch_op.alter_column(
                "role",
                server_default=sa.text(f"'{role_default}'"),
            )
            batch_op.alter_column(
                "is_active",
                server_default=sa.text(active_default),
            )
        return

    op.alter_column(
        "users",
        "role",
        server_default=sa.text(f"'{role_default}'"),
    )
    op.alter_column(
        "users",
        "is_active",
        server_default=sa.text(active_default),
    )


def _add_model_run_policy_columns() -> None:
    """정책 변경으로 결과가 재사용되지 않도록 실행 메타데이터를 추가합니다."""
    for column in (
        sa.Column("decision_policy_sha256", sa.String(length=64), nullable=True),
        sa.Column("medium_threshold", sa.Float(), nullable=True),
        sa.Column("high_threshold", sa.Float(), nullable=True),
        sa.Column("activity_gap_quantile", sa.Float(), nullable=True),
    ):
        if not _has_column("model_runs", column.name):
            op.add_column("model_runs", column)


def _add_snapshot_reference() -> None:
    """기존 분석 이력은 보존하면서 새 분석부터 입력 스냅샷을 참조하게 합니다."""
    constraint_name = "fk_customer_insights_snapshot"
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("customer_insights") as batch_op:
            if not _has_column("customer_insights", "customer_snapshot_id"):
                batch_op.add_column(
                    sa.Column("customer_snapshot_id", sa.Integer(), nullable=True)
                )
            if not _has_foreign_key("customer_insights", constraint_name):
                batch_op.create_foreign_key(
                    constraint_name,
                    "customer_feature_snapshots",
                    ["customer_snapshot_id"],
                    ["id"],
                    ondelete="RESTRICT",
                )
        return

    if not _has_column("customer_insights", "customer_snapshot_id"):
        op.add_column(
            "customer_insights",
            sa.Column("customer_snapshot_id", sa.Integer(), nullable=True),
        )
    if not _has_foreign_key("customer_insights", constraint_name):
        op.create_foreign_key(
            constraint_name,
            "customer_insights",
            "customer_feature_snapshots",
            ["customer_snapshot_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def upgrade() -> None:
    """P0 보안·정확성 강화를 위한 계정·정책·입력 계보를 추가합니다."""
    _alter_user_defaults(role_default="analyst", active_default="0")

    if not _inspector().has_table("customer_feature_snapshots"):
        op.create_table(
            "customer_feature_snapshots",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("customer_id", sa.BigInteger(), nullable=False),
            sa.Column("feature_sha256", sa.String(length=64), nullable=False),
            sa.Column("source_dataset_sha256", sa.String(length=64), nullable=True),
            sa.Column("customer_age", sa.Integer(), nullable=False),
            sa.Column("gender", sa.String(length=1), nullable=False),
            sa.Column("dependent_count", sa.Integer(), nullable=False),
            sa.Column("education_level", sa.String(length=30), nullable=False),
            sa.Column("marital_status", sa.String(length=20), nullable=False),
            sa.Column("income_category", sa.String(length=30), nullable=False),
            sa.Column("card_category", sa.String(length=20), nullable=False),
            sa.Column("months_on_book", sa.Integer(), nullable=False),
            sa.Column("total_relationship_count", sa.Integer(), nullable=False),
            sa.Column("months_inactive_12_mon", sa.Integer(), nullable=False),
            sa.Column("contacts_count_12_mon", sa.Integer(), nullable=False),
            sa.Column("credit_limit", sa.Float(), nullable=False),
            sa.Column("total_revolving_bal", sa.Integer(), nullable=False),
            sa.Column("avg_open_to_buy", sa.Float(), nullable=False),
            sa.Column("total_amt_chng_q4_q1", sa.Float(), nullable=False),
            sa.Column("total_trans_amt", sa.Integer(), nullable=False),
            sa.Column("total_trans_ct", sa.Integer(), nullable=False),
            sa.Column("total_ct_chng_q4_q1", sa.Float(), nullable=False),
            sa.Column("avg_utilization_ratio", sa.Float(), nullable=False),
            sa.Column(
                "as_of_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["customer_id"],
                ["customers.customer_id"],
                name="fk_customer_feature_snapshots_customer_id_customers",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_customer_feature_snapshots"),
            sa.UniqueConstraint(
                "customer_id",
                "feature_sha256",
                name="uq_customer_feature_snapshots_customer_feature",
            ),
        )
    if not any(
        index["name"] == "ix_customer_feature_snapshots_customer_as_of"
        for index in _inspector().get_indexes("customer_feature_snapshots")
    ):
        op.create_index(
            "ix_customer_feature_snapshots_customer_as_of",
            "customer_feature_snapshots",
            ["customer_id", "as_of_at"],
            unique=False,
        )

    _add_model_run_policy_columns()
    _add_snapshot_reference()


def downgrade() -> None:
    """P0 governance 변경을 역순으로 제거합니다."""
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("customer_insights") as batch_op:
            batch_op.drop_constraint(
                "fk_customer_insights_snapshot",
                type_="foreignkey",
            )
            batch_op.drop_column("customer_snapshot_id")
    else:
        op.drop_constraint(
            "fk_customer_insights_snapshot",
            "customer_insights",
            type_="foreignkey",
        )
        op.drop_column("customer_insights", "customer_snapshot_id")

    for column_name in (
        "activity_gap_quantile",
        "high_threshold",
        "medium_threshold",
        "decision_policy_sha256",
    ):
        op.drop_column("model_runs", column_name)

    op.drop_index(
        "ix_customer_feature_snapshots_customer_as_of",
        table_name="customer_feature_snapshots",
    )
    op.drop_table("customer_feature_snapshots")
    _alter_user_defaults(role_default="operations", active_default="1")

"""Add scoring batches, decision policies, and explicit scoring dates.

Revision ID: 20260801_0004
Revises: 20260801_0003
Create Date: 2026-08-01
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260801_0004"
down_revision: str | None = "20260801_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector():
    """부분 적용된 DDL을 재실행할 수 있도록 현재 스키마를 확인합니다."""
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return _inspector().has_table(table_name)


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


def _unique_columns(table_name: str, constraint_name: str) -> list[str] | None:
    for constraint in _inspector().get_unique_constraints(table_name):
        if constraint.get("name") == constraint_name:
            return list(constraint.get("column_names") or [])
    return None


def _add_snapshot_as_of_date() -> None:
    """기존 스냅샷은 as_of_at 날짜를 사용해 시점을 backfill합니다."""
    if not _has_column("customer_feature_snapshots", "as_of_date"):
        op.add_column(
            "customer_feature_snapshots",
            sa.Column("as_of_date", sa.Date(), nullable=True),
        )

    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            sa.text(
                "UPDATE customer_feature_snapshots "
                "SET as_of_date = date(as_of_at) "
                "WHERE as_of_date IS NULL"
            )
        )
    else:
        op.execute(
            sa.text(
                "UPDATE customer_feature_snapshots "
                "SET as_of_date = DATE(as_of_at) "
                "WHERE as_of_date IS NULL"
            )
        )

    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("customer_feature_snapshots") as batch_op:
            batch_op.alter_column(
                "as_of_date",
                existing_type=sa.Date(),
                nullable=False,
            )
    else:
        op.alter_column(
            "customer_feature_snapshots",
            "as_of_date",
            existing_type=sa.Date(),
            nullable=False,
        )

    constraint_name = "uq_customer_feature_snapshots_customer_feature"
    desired_columns = ["customer_id", "feature_sha256", "as_of_date"]
    existing_columns = _unique_columns(
        "customer_feature_snapshots",
        constraint_name,
    )
    if existing_columns == desired_columns:
        return

    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("customer_feature_snapshots") as batch_op:
            if existing_columns is not None:
                batch_op.drop_constraint(constraint_name, type_="unique")
            batch_op.create_unique_constraint(constraint_name, desired_columns)
    else:
        if existing_columns is not None:
            op.drop_constraint(
                constraint_name,
                "customer_feature_snapshots",
                type_="unique",
            )
        op.create_unique_constraint(
            constraint_name,
            "customer_feature_snapshots",
            desired_columns,
        )


def _create_decision_policies() -> None:
    if not _has_table("decision_policies"):
        op.create_table(
            "decision_policies",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("version", sa.String(length=50), nullable=False),
            sa.Column("policy_sha256", sa.String(length=64), nullable=False),
            sa.Column("medium_threshold", sa.Float(), nullable=False),
            sa.Column("high_threshold", sa.Float(), nullable=False),
            sa.Column("activity_gap_quantile", sa.Float(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id", name="pk_decision_policies"),
            sa.UniqueConstraint(
                "policy_sha256",
                name="uq_decision_policies_policy_sha256",
            ),
        )
    if not any(
        index["name"] == "ix_decision_policies_version_created_at"
        for index in _inspector().get_indexes("decision_policies")
    ):
        op.create_index(
            "ix_decision_policies_version_created_at",
            "decision_policies",
            ["version", "created_at"],
            unique=False,
        )


def _create_scoring_batches() -> None:
    if not _has_table("scoring_batches"):
        op.create_table(
            "scoring_batches",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("batch_key_sha256", sa.String(length=64), nullable=False),
            sa.Column("as_of_date", sa.Date(), nullable=False),
            sa.Column("source_dataset_sha256", sa.String(length=64), nullable=True),
            sa.Column("dataset_sha256", sa.String(length=64), nullable=True),
            sa.Column("decision_policy_id", sa.Integer(), nullable=False),
            sa.Column(
                "status",
                sa.String(length=20),
                server_default=sa.text("'running'"),
                nullable=False,
            ),
            sa.Column("processed_rows", sa.Integer(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.CheckConstraint(
                "status IN ('running', 'succeeded', 'failed')",
                name="ck_scoring_batches_status",
            ),
            sa.ForeignKeyConstraint(
                ["decision_policy_id"],
                ["decision_policies.id"],
                name="fk_scoring_batches_policy",
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_scoring_batches"),
            sa.UniqueConstraint(
                "batch_key_sha256",
                name="uq_scoring_batches_batch_key_sha256",
            ),
        )
    existing_indexes = {
        index["name"] for index in _inspector().get_indexes("scoring_batches")
    }
    if "ix_scoring_batches_as_of_date" not in existing_indexes:
        op.create_index(
            "ix_scoring_batches_as_of_date",
            "scoring_batches",
            ["as_of_date"],
            unique=False,
        )
    if "ix_scoring_batches_status_started_at" not in existing_indexes:
        op.create_index(
            "ix_scoring_batches_status_started_at",
            "scoring_batches",
            ["status", "started_at"],
            unique=False,
        )


def _add_batch_links() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("model_runs") as batch_op:
            if not _has_column("model_runs", "scoring_batch_id"):
                batch_op.add_column(
                    sa.Column("scoring_batch_id", sa.Integer(), nullable=True)
                )
            if not _has_foreign_key("model_runs", "fk_model_runs_batch"):
                batch_op.create_foreign_key(
                    "fk_model_runs_batch",
                    "scoring_batches",
                    ["scoring_batch_id"],
                    ["id"],
                    ondelete="RESTRICT",
                )
        with op.batch_alter_table("customer_insights") as batch_op:
            if not _has_column("customer_insights", "scoring_batch_id"):
                batch_op.add_column(
                    sa.Column("scoring_batch_id", sa.Integer(), nullable=True)
                )
            if not _has_column("customer_insights", "as_of_date"):
                batch_op.add_column(
                    sa.Column("as_of_date", sa.Date(), nullable=True)
                )
            if not _has_foreign_key("customer_insights", "fk_insights_batch"):
                batch_op.create_foreign_key(
                    "fk_insights_batch",
                    "scoring_batches",
                    ["scoring_batch_id"],
                    ["id"],
                    ondelete="RESTRICT",
                )
        return

    if not _has_column("model_runs", "scoring_batch_id"):
        op.add_column(
            "model_runs",
            sa.Column("scoring_batch_id", sa.Integer(), nullable=True),
        )
    if not _has_foreign_key("model_runs", "fk_model_runs_batch"):
        op.create_foreign_key(
            "fk_model_runs_batch",
            "model_runs",
            "scoring_batches",
            ["scoring_batch_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    if not _has_column("customer_insights", "scoring_batch_id"):
        op.add_column(
            "customer_insights",
            sa.Column("scoring_batch_id", sa.Integer(), nullable=True),
        )
    if not _has_column("customer_insights", "as_of_date"):
        op.add_column(
            "customer_insights",
            sa.Column("as_of_date", sa.Date(), nullable=True),
        )
    if not _has_foreign_key("customer_insights", "fk_insights_batch"):
        op.create_foreign_key(
            "fk_insights_batch",
            "customer_insights",
            "scoring_batches",
            ["scoring_batch_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def upgrade() -> None:
    """배치·정책·입력 시점을 하나의 분석 계보로 연결합니다."""
    _add_snapshot_as_of_date()
    _create_decision_policies()
    _create_scoring_batches()
    _add_batch_links()


def downgrade() -> None:
    """분석 계보 확장을 역순으로 제거합니다."""
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("customer_insights") as batch_op:
            batch_op.drop_constraint("fk_insights_batch", type_="foreignkey")
            batch_op.drop_column("as_of_date")
            batch_op.drop_column("scoring_batch_id")
        with op.batch_alter_table("model_runs") as batch_op:
            batch_op.drop_constraint("fk_model_runs_batch", type_="foreignkey")
            batch_op.drop_column("scoring_batch_id")
    else:
        op.drop_constraint("fk_insights_batch", "customer_insights", type_="foreignkey")
        op.drop_column("customer_insights", "as_of_date")
        op.drop_column("customer_insights", "scoring_batch_id")
        op.drop_constraint("fk_model_runs_batch", "model_runs", type_="foreignkey")
        op.drop_column("model_runs", "scoring_batch_id")

    op.drop_index(
        "ix_scoring_batches_status_started_at",
        table_name="scoring_batches",
    )
    op.drop_index("ix_scoring_batches_as_of_date", table_name="scoring_batches")
    op.drop_table("scoring_batches")
    op.drop_index(
        "ix_decision_policies_version_created_at",
        table_name="decision_policies",
    )
    op.drop_table("decision_policies")

    constraint_name = "uq_customer_feature_snapshots_customer_feature"
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("customer_feature_snapshots") as batch_op:
            batch_op.drop_constraint(constraint_name, type_="unique")
            batch_op.create_unique_constraint(
                constraint_name,
                ["customer_id", "feature_sha256"],
            )
            batch_op.drop_column("as_of_date")
    else:
        op.drop_constraint(
            constraint_name,
            "customer_feature_snapshots",
            type_="unique",
        )
        op.create_unique_constraint(
            constraint_name,
            "customer_feature_snapshots",
            ["customer_id", "feature_sha256"],
        )
        op.drop_column("customer_feature_snapshots", "as_of_date")

"""Add roles and customer analytics operations tables.

Revision ID: 20260801_0002
Revises: 20260801_0001
Create Date: 2026-08-01
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260801_0002"
down_revision: str | None = "20260801_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ROLE_CHECK = "role IN ('admin', 'analyst', 'operations', 'marketing')"


def _add_user_role() -> None:
    """기존 사용자에 최소권한 operations 역할을 부여합니다."""
    role_column = sa.Column(
        "role",
        sa.String(length=20),
        server_default=sa.text("'operations'"),
        nullable=False,
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(role_column)
            batch_op.create_check_constraint("ck_users_role", ROLE_CHECK)
    else:
        op.add_column("users", role_column)
        op.create_check_constraint("ck_users_role", "users", ROLE_CHECK)


def _drop_user_role() -> None:
    """역할 컬럼과 제약조건을 제거합니다."""
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_constraint("ck_users_role", type_="check")
            batch_op.drop_column("role")
    else:
        op.drop_constraint("ck_users_role", "users", type_="check")
        op.drop_column("users", "role")


def upgrade() -> None:
    """고객 분석과 캠페인 운영을 위한 1단계 스키마를 구성합니다."""
    _add_user_role()

    op.create_table(
        "customers",
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
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
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "customer_age BETWEEN 18 AND 120",
            name="ck_customers_age",
        ),
        sa.CheckConstraint("gender IN ('F', 'M')", name="ck_customers_gender"),
        sa.CheckConstraint("dependent_count >= 0", name="ck_customers_dependents"),
        sa.CheckConstraint("months_on_book >= 0", name="ck_customers_months_on_book"),
        sa.CheckConstraint(
            "total_relationship_count >= 0",
            name="ck_customers_relationship_count",
        ),
        sa.CheckConstraint(
            "months_inactive_12_mon >= 0",
            name="ck_customers_inactive_months",
        ),
        sa.CheckConstraint(
            "contacts_count_12_mon >= 0",
            name="ck_customers_contacts_count",
        ),
        sa.CheckConstraint("credit_limit >= 0", name="ck_customers_credit_limit"),
        sa.CheckConstraint(
            "total_revolving_bal >= 0",
            name="ck_customers_revolving_balance",
        ),
        sa.CheckConstraint("avg_open_to_buy >= 0", name="ck_customers_open_to_buy"),
        sa.CheckConstraint(
            "total_amt_chng_q4_q1 >= 0",
            name="ck_customers_amount_change",
        ),
        sa.CheckConstraint(
            "total_trans_amt >= 0",
            name="ck_customers_transaction_amount",
        ),
        sa.CheckConstraint(
            "total_trans_ct >= 0",
            name="ck_customers_transaction_count",
        ),
        sa.CheckConstraint(
            "total_ct_chng_q4_q1 >= 0",
            name="ck_customers_count_change",
        ),
        sa.CheckConstraint(
            "avg_utilization_ratio BETWEEN 0 AND 1",
            name="ck_customers_utilization_ratio",
        ),
        sa.PrimaryKeyConstraint("customer_id", name="pk_customers"),
    )
    op.create_index(
        "ix_customers_card_category",
        "customers",
        ["card_category"],
        unique=False,
    )

    op.create_table(
        "model_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=False),
        sa.Column("artifact_path", sa.String(length=500), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("dataset_sha256", sa.String(length=64), nullable=True),
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
            name="ck_model_runs_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_runs"),
    )
    op.create_index(
        "ix_model_runs_task_started_at",
        "model_runs",
        ["task", "started_at"],
        unique=False,
    )

    op.create_table(
        "customer_insights",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("classification_run_id", sa.Integer(), nullable=False),
        sa.Column("regression_run_id", sa.Integer(), nullable=False),
        sa.Column("clustering_run_id", sa.Integer(), nullable=False),
        sa.Column("churn_probability", sa.Float(), nullable=False),
        sa.Column("risk_level", sa.String(length=20), nullable=False),
        sa.Column("expected_transaction_count", sa.Float(), nullable=False),
        sa.Column("activity_gap", sa.Float(), nullable=False),
        sa.Column("cluster_name", sa.String(length=100), nullable=False),
        sa.Column("cluster_confidence", sa.Float(), nullable=True),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=True),
        sa.Column(
            "scored_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "churn_probability BETWEEN 0 AND 1",
            name="ck_customer_insights_churn_probability",
        ),
        sa.CheckConstraint(
            "risk_level IN ('low', 'medium', 'high')",
            name="ck_customer_insights_risk_level",
        ),
        sa.CheckConstraint(
            "expected_transaction_count >= 0",
            name="ck_customer_insights_expected_transaction_count",
        ),
        sa.CheckConstraint(
            "cluster_confidence IS NULL OR cluster_confidence BETWEEN 0 AND 1",
            name="ck_customer_insights_cluster_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["classification_run_id"],
            ["model_runs.id"],
            name="fk_customer_insights_classification_run_id_model_runs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["clustering_run_id"],
            ["model_runs.id"],
            name="fk_customer_insights_clustering_run_id_model_runs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.customer_id"],
            name="fk_customer_insights_customer_id_customers",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["regression_run_id"],
            ["model_runs.id"],
            name="fk_customer_insights_regression_run_id_model_runs",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_customer_insights"),
    )
    op.create_index(
        "ix_customer_insights_cluster_name",
        "customer_insights",
        ["cluster_name"],
        unique=False,
    )
    op.create_index(
        "ix_customer_insights_customer_scored_at",
        "customer_insights",
        ["customer_id", "scored_at"],
        unique=False,
    )
    op.create_index(
        "ix_customer_insights_risk_level",
        "customer_insights",
        ["risk_level"],
        unique=False,
    )

    op.create_table(
        "campaign_targets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("customer_insight_id", sa.Integer(), nullable=False),
        sa.Column("campaign_name", sa.String(length=150), nullable=False),
        sa.Column("assigned_to_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.String(length=100), nullable=True),
        sa.Column("result_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'assigned', 'contacted', 'completed', 'cancelled')",
            name="ck_campaign_targets_status",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to_user_id"],
            ["users.id"],
            name="fk_campaign_targets_assigned_to_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.customer_id"],
            name="fk_campaign_targets_customer_id_customers",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["customer_insight_id"],
            ["customer_insights.id"],
            name="fk_campaign_targets_customer_insight_id_customer_insights",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_campaign_targets"),
        sa.UniqueConstraint(
            "customer_insight_id",
            "campaign_name",
            name="uq_campaign_targets_insight_campaign",
        ),
    )
    op.create_index(
        "ix_campaign_targets_assigned_to",
        "campaign_targets",
        ["assigned_to_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_campaign_targets_customer",
        "campaign_targets",
        ["customer_id"],
        unique=False,
    )
    op.create_index(
        "ix_campaign_targets_status",
        "campaign_targets",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    """1단계 고객 운영 스키마를 역순으로 제거합니다."""
    op.drop_index("ix_campaign_targets_status", table_name="campaign_targets")
    op.drop_index("ix_campaign_targets_customer", table_name="campaign_targets")
    op.drop_index("ix_campaign_targets_assigned_to", table_name="campaign_targets")
    op.drop_table("campaign_targets")

    op.drop_index("ix_customer_insights_risk_level", table_name="customer_insights")
    op.drop_index(
        "ix_customer_insights_customer_scored_at",
        table_name="customer_insights",
    )
    op.drop_index("ix_customer_insights_cluster_name", table_name="customer_insights")
    op.drop_table("customer_insights")

    op.drop_index("ix_model_runs_task_started_at", table_name="model_runs")
    op.drop_table("model_runs")

    op.drop_index("ix_customers_card_category", table_name="customers")
    op.drop_table("customers")

    _drop_user_role()

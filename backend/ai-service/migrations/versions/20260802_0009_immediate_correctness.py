"""Harden point-in-time targeting, campaign experiments, finance, and auth audit.

Revision ID: 20260802_0009
Revises: 20260801_0008
Create Date: 2026-08-02
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260802_0009"
down_revision: str | None = "20260801_0008"
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


def _has_unique(table_name: str, constraint_name: str) -> bool:
    return any(
        constraint.get("name") == constraint_name
        for constraint in _inspector().get_unique_constraints(table_name)
    )


def _has_foreign_key(table_name: str, constraint_name: str) -> bool:
    return any(
        constraint.get("name") == constraint_name
        for constraint in _inspector().get_foreign_keys(table_name)
    )


def _has_check(table_name: str, constraint_name: str) -> bool:
    return any(
        constraint.get("name") == constraint_name
        for constraint in _inspector().get_check_constraints(table_name)
    )


def _add_policy_json() -> None:
    if not _has_column("decision_policies", "policy_json"):
        op.add_column(
            "decision_policies",
            sa.Column("policy_json", sa.JSON(), nullable=True),
        )
    op.execute(sa.text("UPDATE decision_policies SET policy_json = '{}' WHERE policy_json IS NULL"))
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("decision_policies") as batch_op:
            batch_op.alter_column(
                "policy_json",
                existing_type=sa.JSON(),
                nullable=False,
            )
    else:
        op.alter_column(
            "decision_policies",
            "policy_json",
            existing_type=sa.JSON(),
            nullable=False,
        )


def _add_scoring_retry_lineage() -> None:
    """논리적 재사용 키와 실행 시도를 분리해 실패 배치를 재시도할 수 있게 합니다."""
    if not _has_column("scoring_batches", "reuse_key_sha256"):
        op.add_column(
            "scoring_batches",
            sa.Column("reuse_key_sha256", sa.String(length=64), nullable=True),
        )
    if not _has_column("scoring_batches", "attempt_number"):
        op.add_column(
            "scoring_batches",
            sa.Column(
                "attempt_number",
                sa.Integer(),
                server_default=sa.text("1"),
                nullable=True,
            ),
        )
    op.execute(
        sa.text(
            "UPDATE scoring_batches "
            "SET reuse_key_sha256 = batch_key_sha256 "
            "WHERE reuse_key_sha256 IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE scoring_batches SET attempt_number = 1 "
            "WHERE attempt_number IS NULL"
        )
    )
    needs_unique = not _has_unique(
        "scoring_batches",
        "uq_scoring_batches_reuse_attempt",
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("scoring_batches") as batch_op:
            batch_op.alter_column(
                "reuse_key_sha256",
                existing_type=sa.String(length=64),
                nullable=False,
            )
            batch_op.alter_column(
                "attempt_number",
                existing_type=sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            )
            if needs_unique:
                batch_op.create_unique_constraint(
                    "uq_scoring_batches_reuse_attempt",
                    ["reuse_key_sha256", "attempt_number"],
                )
    else:
        op.alter_column(
            "scoring_batches",
            "reuse_key_sha256",
            existing_type=sa.String(length=64),
            nullable=False,
        )
        op.alter_column(
            "scoring_batches",
            "attempt_number",
            existing_type=sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        )
        if needs_unique:
            op.create_unique_constraint(
                "uq_scoring_batches_reuse_attempt",
                "scoring_batches",
                ["reuse_key_sha256", "attempt_number"],
            )
    if not _has_index("scoring_batches", "ix_scoring_batches_reuse_status"):
        op.create_index(
            "ix_scoring_batches_reuse_status",
            "scoring_batches",
            ["reuse_key_sha256", "status"],
            unique=False,
        )


def _add_bulk_scoring_batch() -> None:
    if not _has_column("bulk_targeting_runs", "scoring_batch_id"):
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table("bulk_targeting_runs") as batch_op:
                batch_op.add_column(
                    sa.Column("scoring_batch_id", sa.Integer(), nullable=True)
                )
                batch_op.create_foreign_key(
                    "fk_bulk_targeting_runs_scoring_batch",
                    "scoring_batches",
                    ["scoring_batch_id"],
                    ["id"],
                    ondelete="RESTRICT",
                )
        else:
            op.add_column(
                "bulk_targeting_runs",
                sa.Column("scoring_batch_id", sa.Integer(), nullable=True),
            )
            op.create_foreign_key(
                "fk_bulk_targeting_runs_scoring_batch",
                "bulk_targeting_runs",
                "scoring_batches",
                ["scoring_batch_id"],
                ["id"],
                ondelete="RESTRICT",
            )

    op.execute(
        sa.text(
            """
            UPDATE bulk_targeting_runs
            SET scoring_batch_id = (
                SELECT ci.scoring_batch_id
                FROM campaign_targets AS ct
                JOIN customer_insights AS ci ON ci.id = ct.customer_insight_id
                WHERE ct.bulk_targeting_run_id = bulk_targeting_runs.id
                  AND ci.scoring_batch_id IS NOT NULL
                LIMIT 1
            )
            WHERE scoring_batch_id IS NULL
            """
        )
    )
    if not _has_index(
        "bulk_targeting_runs",
        "ix_bulk_targeting_runs_scoring_batch",
    ):
        op.create_index(
            "ix_bulk_targeting_runs_scoring_batch",
            "bulk_targeting_runs",
            ["scoring_batch_id"],
            unique=False,
        )


def _create_bulk_candidates() -> None:
    if _has_table("bulk_targeting_candidates"):
        return
    op.create_table(
        "bulk_targeting_candidates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("customer_insight_id", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column(
            "selected",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("exclusion_reason", sa.String(length=30), nullable=True),
        sa.Column(
            "execution_status",
            sa.String(length=20),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("campaign_target_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "exclusion_reason IS NULL OR exclusion_reason IN "
            "('opted_out', 'active_campaign', 'recent_contact')",
            name="ck_bulk_targeting_candidates_exclusion_reason",
        ),
        sa.CheckConstraint(
            "execution_status IN ('pending', 'created', 'skipped', 'cancelled')",
            name="ck_bulk_targeting_candidates_execution_status",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["bulk_targeting_runs.id"],
            name="fk_bulk_targeting_candidates_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.customer_id"],
            name="fk_bulk_targeting_candidates_customer",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["customer_insight_id"],
            ["customer_insights.id"],
            name="fk_bulk_targeting_candidates_insight",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_target_id"],
            ["campaign_targets.id"],
            name="fk_bulk_targeting_candidates_target",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bulk_targeting_candidates"),
        sa.UniqueConstraint(
            "run_id",
            "customer_id",
            name="uq_bulk_targeting_candidates_run_customer",
        ),
    )
    op.create_index(
        "ix_bulk_targeting_candidates_run_rank",
        "bulk_targeting_candidates",
        ["run_id", "rank"],
        unique=False,
    )


def _add_campaign_customer_unique() -> None:
    if _has_unique(
        "campaign_targets",
        "uq_campaign_targets_campaign_customer",
    ):
        return
    duplicates = op.get_bind().execute(
        sa.text(
            """
            SELECT campaign_id, customer_id, COUNT(*) AS row_count
            FROM campaign_targets
            WHERE campaign_id IS NOT NULL
            GROUP BY campaign_id, customer_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicates is not None:
        raise RuntimeError(
            "Cannot enforce one customer per campaign because duplicate "
            "campaign_targets already exist. Resolve them before migrating."
        )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("campaign_targets") as batch_op:
            batch_op.create_unique_constraint(
                "uq_campaign_targets_campaign_customer",
                ["campaign_id", "customer_id"],
            )
    else:
        op.create_unique_constraint(
            "uq_campaign_targets_campaign_customer",
            "campaign_targets",
            ["campaign_id", "customer_id"],
        )


def _add_experiment_assignment_version() -> None:
    """기존 A/B 배정은 보존하고 새 캠페인부터 재실행 안정 알고리즘을 사용합니다."""
    if not _has_column("campaigns", "experiment_assignment_version"):
        op.add_column(
            "campaigns",
            sa.Column(
                "experiment_assignment_version",
                sa.String(length=40),
                nullable=True,
            ),
        )
    op.execute(
        sa.text(
            "UPDATE campaigns "
            "SET experiment_assignment_version = 'sha256_campaign_customer_v1' "
            "WHERE experiment_assignment_version IS NULL"
        )
    )
    constraint_name = "ck_campaigns_experiment_assignment_version"
    needs_check = not _has_check("campaigns", constraint_name)
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("campaigns") as batch_op:
            batch_op.alter_column(
                "experiment_assignment_version",
                existing_type=sa.String(length=40),
                nullable=False,
                server_default=sa.text("'sha256_seed_customer_v1'"),
            )
            if needs_check:
                batch_op.create_check_constraint(
                    constraint_name,
                    "experiment_assignment_version IN "
                    "('sha256_campaign_customer_v1', 'sha256_seed_customer_v1')",
                )
    else:
        op.alter_column(
            "campaigns",
            "experiment_assignment_version",
            existing_type=sa.String(length=40),
            nullable=False,
            server_default=sa.text("'sha256_seed_customer_v1'"),
        )
        if needs_check:
            op.create_check_constraint(
                constraint_name,
                "campaigns",
                "experiment_assignment_version IN "
                "('sha256_campaign_customer_v1', 'sha256_seed_customer_v1')",
            )


def _convert_money_to_decimal() -> None:
    campaign_columns = (
        "fixed_cost",
        "cost_per_contact",
        "revenue_per_conversion",
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("campaigns") as batch_op:
            for column_name in campaign_columns:
                batch_op.alter_column(
                    column_name,
                    existing_type=sa.Float(),
                    type_=sa.Numeric(18, 2),
                    existing_nullable=False,
                )
        with op.batch_alter_table("campaign_targets") as batch_op:
            batch_op.alter_column(
                "outcome_revenue",
                existing_type=sa.Float(),
                type_=sa.Numeric(18, 2),
                existing_nullable=True,
            )
        return
    for column_name in campaign_columns:
        op.alter_column(
            "campaigns",
            column_name,
            existing_type=sa.Float(),
            type_=sa.Numeric(18, 2),
            existing_nullable=False,
        )
    op.alter_column(
        "campaign_targets",
        "outcome_revenue",
        existing_type=sa.Float(),
        type_=sa.Numeric(18, 2),
        existing_nullable=True,
    )


def _create_auth_events() -> None:
    if _has_table("auth_events"):
        return
    op.create_table(
        "auth_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(length=50), nullable=True),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('signup_requested', 'login_succeeded', 'login_failed', "
            "'login_rate_limited', 'logout', 'user_updated')",
            name="ck_auth_events_type",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_auth_events_user",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_auth_events_actor_user",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_events"),
    )
    op.create_index(
        "ix_auth_events_type_created",
        "auth_events",
        ["event_type", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_auth_events_username_created",
        "auth_events",
        ["username", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_auth_events_ip_created",
        "auth_events",
        ["ip_address", "created_at"],
        unique=False,
    )


def upgrade() -> None:
    # MySQL DDL은 트랜잭션 rollback이 제한적이므로 데이터 충돌을 모든 스키마
    # 변경보다 먼저 검사합니다.
    _add_campaign_customer_unique()
    _add_policy_json()
    _add_scoring_retry_lineage()
    _add_bulk_scoring_batch()
    _create_bulk_candidates()
    _add_experiment_assignment_version()
    _convert_money_to_decimal()
    _create_auth_events()


def downgrade() -> None:
    if _has_table("auth_events"):
        op.drop_table("auth_events")

    if _has_column("campaigns", "experiment_assignment_version"):
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table("campaigns") as batch_op:
                if _has_check(
                    "campaigns",
                    "ck_campaigns_experiment_assignment_version",
                ):
                    batch_op.drop_constraint(
                        "ck_campaigns_experiment_assignment_version",
                        type_="check",
                    )
                batch_op.drop_column("experiment_assignment_version")
        else:
            if _has_check(
                "campaigns",
                "ck_campaigns_experiment_assignment_version",
            ):
                op.drop_constraint(
                    "ck_campaigns_experiment_assignment_version",
                    "campaigns",
                    type_="check",
                )
            op.drop_column("campaigns", "experiment_assignment_version")

    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("campaign_targets") as batch_op:
            if _has_unique(
                "campaign_targets",
                "uq_campaign_targets_campaign_customer",
            ):
                batch_op.drop_constraint(
                    "uq_campaign_targets_campaign_customer",
                    type_="unique",
                )
            batch_op.alter_column(
                "outcome_revenue",
                existing_type=sa.Numeric(18, 2),
                type_=sa.Float(),
                existing_nullable=True,
            )
        with op.batch_alter_table("campaigns") as batch_op:
            for column_name in (
                "fixed_cost",
                "cost_per_contact",
                "revenue_per_conversion",
            ):
                batch_op.alter_column(
                    column_name,
                    existing_type=sa.Numeric(18, 2),
                    type_=sa.Float(),
                    existing_nullable=False,
                )
    else:
        if _has_unique(
            "campaign_targets",
            "uq_campaign_targets_campaign_customer",
        ):
            op.drop_constraint(
                "uq_campaign_targets_campaign_customer",
                "campaign_targets",
                type_="unique",
            )
        for column_name in (
            "fixed_cost",
            "cost_per_contact",
            "revenue_per_conversion",
        ):
            op.alter_column(
                "campaigns",
                column_name,
                existing_type=sa.Numeric(18, 2),
                type_=sa.Float(),
                existing_nullable=False,
            )
        op.alter_column(
            "campaign_targets",
            "outcome_revenue",
            existing_type=sa.Numeric(18, 2),
            type_=sa.Float(),
            existing_nullable=True,
        )

    if _has_table("bulk_targeting_candidates"):
        op.drop_table("bulk_targeting_candidates")
    if _has_index(
        "bulk_targeting_runs",
        "ix_bulk_targeting_runs_scoring_batch",
    ):
        op.drop_index(
            "ix_bulk_targeting_runs_scoring_batch",
            table_name="bulk_targeting_runs",
        )
    if _has_column("bulk_targeting_runs", "scoring_batch_id"):
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table("bulk_targeting_runs") as batch_op:
                if _has_foreign_key(
                    "bulk_targeting_runs",
                    "fk_bulk_targeting_runs_scoring_batch",
                ):
                    batch_op.drop_constraint(
                        "fk_bulk_targeting_runs_scoring_batch",
                        type_="foreignkey",
                    )
                batch_op.drop_column("scoring_batch_id")
        else:
            if _has_foreign_key(
                "bulk_targeting_runs",
                "fk_bulk_targeting_runs_scoring_batch",
            ):
                op.drop_constraint(
                    "fk_bulk_targeting_runs_scoring_batch",
                    "bulk_targeting_runs",
                    type_="foreignkey",
                )
            op.drop_column("bulk_targeting_runs", "scoring_batch_id")
    if _has_column("decision_policies", "policy_json"):
        op.drop_column("decision_policies", "policy_json")

    if _has_index("scoring_batches", "ix_scoring_batches_reuse_status"):
        op.drop_index(
            "ix_scoring_batches_reuse_status",
            table_name="scoring_batches",
        )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("scoring_batches") as batch_op:
            if _has_unique(
                "scoring_batches",
                "uq_scoring_batches_reuse_attempt",
            ):
                batch_op.drop_constraint(
                    "uq_scoring_batches_reuse_attempt",
                    type_="unique",
                )
            if _has_column("scoring_batches", "attempt_number"):
                batch_op.drop_column("attempt_number")
            if _has_column("scoring_batches", "reuse_key_sha256"):
                batch_op.drop_column("reuse_key_sha256")
    else:
        if _has_unique(
            "scoring_batches",
            "uq_scoring_batches_reuse_attempt",
        ):
            op.drop_constraint(
                "uq_scoring_batches_reuse_attempt",
                "scoring_batches",
                type_="unique",
            )
        if _has_column("scoring_batches", "attempt_number"):
            op.drop_column("scoring_batches", "attempt_number")
        if _has_column("scoring_batches", "reuse_key_sha256"):
            op.drop_column("scoring_batches", "reuse_key_sha256")

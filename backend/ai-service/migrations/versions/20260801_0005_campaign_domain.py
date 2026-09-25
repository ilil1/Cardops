"""Add campaigns, campaign events, and target domain metadata.

Revision ID: 20260801_0005
Revises: 20260801_0004
Create Date: 2026-08-01
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260801_0005"
down_revision: str | None = "20260801_0004"
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


def _has_index(table_name: str, index_name: str) -> bool:
    return any(
        index.get("name") == index_name
        for index in _inspector().get_indexes(table_name)
    )


def _create_campaigns() -> None:
    if not _has_table("campaigns"):
        op.create_table(
            "campaigns",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(length=150), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("channel", sa.String(length=30), nullable=True),
            sa.Column(
                "status",
                sa.String(length=20),
                server_default=sa.text("'draft'"),
                nullable=False,
            ),
            sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
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
                "status IN ('draft', 'scheduled', 'active', 'paused', 'completed', 'cancelled')",
                name="ck_campaigns_status",
            ),
            sa.CheckConstraint(
                "end_at IS NULL OR start_at IS NULL OR end_at >= start_at",
                name="ck_campaigns_period",
            ),
            sa.ForeignKeyConstraint(
                ["created_by_user_id"],
                ["users.id"],
                name="fk_campaigns_created_by_user",
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_campaigns"),
            sa.UniqueConstraint("name", name="uq_campaigns_name"),
        )

    if not _has_index("campaigns", "ix_campaigns_status_period"):
        op.create_index(
            "ix_campaigns_status_period",
            "campaigns",
            ["status", "start_at", "end_at"],
            unique=False,
        )
    if not _has_index("campaigns", "ix_campaigns_created_by"):
        op.create_index(
            "ix_campaigns_created_by",
            "campaigns",
            ["created_by_user_id"],
            unique=False,
        )


def _add_target_columns() -> None:
    """기존 campaign_targets에 새 도메인 식별자와 결과 집계 필드를 추가합니다."""
    has_campaign_id = _has_column("campaign_targets", "campaign_id")
    has_result_code = _has_column("campaign_targets", "result_code")
    has_converted = _has_column("campaign_targets", "converted")
    has_campaign_fk = _has_foreign_key(
        "campaign_targets",
        "fk_campaign_targets_campaign",
    )

    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("campaign_targets") as batch_op:
            if not has_campaign_id:
                batch_op.add_column(
                    sa.Column("campaign_id", sa.Integer(), nullable=True)
                )
            if not has_result_code:
                batch_op.add_column(
                    sa.Column("result_code", sa.String(length=30), nullable=True)
                )
            if not has_converted:
                batch_op.add_column(
                    sa.Column(
                        "converted",
                        sa.Boolean(),
                        server_default=sa.text("0"),
                        nullable=False,
                    )
                )
            if not has_campaign_fk:
                batch_op.create_foreign_key(
                    "fk_campaign_targets_campaign",
                    "campaigns",
                    ["campaign_id"],
                    ["id"],
                    ondelete="RESTRICT",
                )
        return

    if not has_campaign_id:
        op.add_column(
            "campaign_targets",
            sa.Column("campaign_id", sa.Integer(), nullable=True),
        )
    if not has_result_code:
        op.add_column(
            "campaign_targets",
            sa.Column("result_code", sa.String(length=30), nullable=True),
        )
    if not has_converted:
        op.add_column(
            "campaign_targets",
            sa.Column(
                "converted",
                sa.Boolean(),
                server_default=sa.text("0"),
                nullable=False,
            ),
        )
    if not has_campaign_fk:
        op.create_foreign_key(
            "fk_campaign_targets_campaign",
            "campaign_targets",
            "campaigns",
            ["campaign_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def _backfill_campaigns() -> None:
    """기존 campaign_name 값을 실제 캠페인과 연결합니다."""
    op.execute(
        sa.text(
            "INSERT INTO campaigns "
            "(name, status, created_at, updated_at) "
            "SELECT target.campaign_name, 'active', "
            "MIN(target.created_at), MAX(target.updated_at) "
            "FROM campaign_targets AS target "
            "LEFT JOIN campaigns AS campaign "
            "ON campaign.name = target.campaign_name "
            "WHERE campaign.id IS NULL "
            "GROUP BY target.campaign_name"
        )
    )
    op.execute(
        sa.text(
            "UPDATE campaign_targets AS target "
            "SET campaign_id = ("
            "SELECT campaign.id FROM campaigns AS campaign "
            "WHERE campaign.name = target.campaign_name"
            ") WHERE target.campaign_id IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE campaign_targets "
            "SET converted = 0 WHERE converted IS NULL"
        )
    )


def _create_events() -> None:
    if not _has_table("campaign_events"):
        op.create_table(
            "campaign_events",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("campaign_id", sa.Integer(), nullable=False),
            sa.Column("campaign_target_id", sa.Integer(), nullable=True),
            sa.Column("event_type", sa.String(length=30), nullable=False),
            sa.Column("from_status", sa.String(length=20), nullable=True),
            sa.Column("to_status", sa.String(length=20), nullable=True),
            sa.Column("actor_user_id", sa.Integer(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.CheckConstraint(
                "event_type IN ('created', 'status_changed', 'assigned', "
                "'result_updated', 'conversion_updated')",
                name="ck_campaign_events_type",
            ),
            sa.ForeignKeyConstraint(
                ["campaign_id"],
                ["campaigns.id"],
                name="fk_campaign_events_campaign",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["campaign_target_id"],
                ["campaign_targets.id"],
                name="fk_campaign_events_target",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["actor_user_id"],
                ["users.id"],
                name="fk_campaign_events_actor",
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_campaign_events"),
        )

    if not _has_index("campaign_events", "ix_campaign_events_campaign_created"):
        op.create_index(
            "ix_campaign_events_campaign_created",
            "campaign_events",
            ["campaign_id", "created_at"],
            unique=False,
        )
    if not _has_index("campaign_events", "ix_campaign_events_target_created"):
        op.create_index(
            "ix_campaign_events_target_created",
            "campaign_events",
            ["campaign_target_id", "created_at"],
            unique=False,
        )


def _backfill_events() -> None:
    """기존 대상도 최소 생성 이력을 갖도록 보정합니다."""
    op.execute(
        sa.text(
            "INSERT INTO campaign_events "
            "(campaign_id, campaign_target_id, event_type, to_status, created_at) "
            "SELECT target.campaign_id, target.id, 'created', target.status, "
            "target.created_at FROM campaign_targets AS target "
            "WHERE target.campaign_id IS NOT NULL "
            "AND NOT EXISTS ("
            "SELECT 1 FROM campaign_events AS event "
            "WHERE event.campaign_target_id = target.id "
            "AND event.event_type = 'created'"
            ")"
        )
    )


def _create_target_indexes() -> None:
    if not _has_index("campaign_targets", "ix_campaign_targets_campaign_status"):
        op.create_index(
            "ix_campaign_targets_campaign_status",
            "campaign_targets",
            ["campaign_id", "status"],
            unique=False,
        )
    if not _has_index("campaign_targets", "ix_campaign_targets_campaign_customer"):
        op.create_index(
            "ix_campaign_targets_campaign_customer",
            "campaign_targets",
            ["campaign_id", "customer_id"],
            unique=False,
        )


def upgrade() -> None:
    """캠페인 기본 정보·이력·집계 가능한 대상 도메인을 추가합니다."""
    _create_campaigns()
    _add_target_columns()
    _backfill_campaigns()
    _create_events()
    _backfill_events()
    _create_target_indexes()


def downgrade() -> None:
    """캠페인 도메인 확장을 역순으로 제거합니다."""
    if _has_table("campaign_events"):
        if _has_index("campaign_events", "ix_campaign_events_target_created"):
            op.drop_index(
                "ix_campaign_events_target_created",
                table_name="campaign_events",
            )
        if _has_index("campaign_events", "ix_campaign_events_campaign_created"):
            op.drop_index(
                "ix_campaign_events_campaign_created",
                table_name="campaign_events",
            )
        op.drop_table("campaign_events")

    if _has_index("campaign_targets", "ix_campaign_targets_campaign_customer"):
        op.drop_index(
            "ix_campaign_targets_campaign_customer",
            table_name="campaign_targets",
        )
    if _has_index("campaign_targets", "ix_campaign_targets_campaign_status"):
        op.drop_index(
            "ix_campaign_targets_campaign_status",
            table_name="campaign_targets",
        )

    has_campaign_id = _has_column("campaign_targets", "campaign_id")
    has_result_code = _has_column("campaign_targets", "result_code")
    has_converted = _has_column("campaign_targets", "converted")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("campaign_targets") as batch_op:
            if has_campaign_id:
                batch_op.drop_constraint(
                    "fk_campaign_targets_campaign",
                    type_="foreignkey",
                )
                batch_op.drop_column("campaign_id")
            if has_result_code:
                batch_op.drop_column("result_code")
            if has_converted:
                batch_op.drop_column("converted")
    else:
        if has_campaign_id:
            op.drop_constraint(
                "fk_campaign_targets_campaign",
                "campaign_targets",
                type_="foreignkey",
            )
            op.drop_column("campaign_targets", "campaign_id")
        if has_result_code:
            op.drop_column("campaign_targets", "result_code")
        if has_converted:
            op.drop_column("campaign_targets", "converted")

    if _has_table("campaigns"):
        if _has_index("campaigns", "ix_campaigns_created_by"):
            op.drop_index("ix_campaigns_created_by", table_name="campaigns")
        if _has_index("campaigns", "ix_campaigns_status_period"):
            op.drop_index("ix_campaigns_status_period", table_name="campaigns")
        op.drop_table("campaigns")

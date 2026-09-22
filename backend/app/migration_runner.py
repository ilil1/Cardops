"""기존 users 데이터를 보존하면서 Alembic migration을 최신 상태로 적용합니다."""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from .config import PROJECT_ROOT, get_database_url


ALEMBIC_INI_PATH = PROJECT_ROOT / "backend" / "alembic.ini"
BASELINE_REVISION = "20260801_0001"
BASELINE_USER_COLUMNS = {
    "id",
    "username",
    "display_name",
    "password_hash",
    "is_active",
    "created_at",
    "updated_at",
}
MANAGED_TABLES_AFTER_BASELINE = {
    "customers",
    "model_runs",
    "customer_insights",
    "campaign_targets",
    "customer_feature_snapshots",
    "decision_policies",
    "scoring_batches",
    "campaigns",
    "campaign_events",
    "bulk_targeting_runs",
    "bulk_targeting_candidates",
    "auth_events",
}


def build_alembic_config(database_url: str) -> Config:
    """지정된 DB URL을 명시적으로 사용하는 Alembic 설정을 만듭니다."""
    config = Config(str(ALEMBIC_INI_PATH))
    config.attributes["database_url"] = database_url
    return config


def _current_revision(database_url: str) -> tuple[str | None, set[str]]:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            revision = MigrationContext.configure(connection).get_current_revision()
            tables = set(inspect(connection).get_table_names())
        return revision, tables
    finally:
        engine.dispose()


def _bootstrap_existing_users(database_url: str, config: Config) -> bool:
    """create_all로 만들어진 기존 users DB를 Alembic 기준선에 안전하게 연결합니다."""
    revision, tables = _current_revision(database_url)
    if revision is not None or "users" not in tables:
        return False

    unexpected_managed_tables = MANAGED_TABLES_AFTER_BASELINE & tables
    if unexpected_managed_tables:
        names = ", ".join(sorted(unexpected_managed_tables))
        raise RuntimeError(
            "Cannot baseline a partially migrated database. Existing managed tables: "
            f"{names}."
        )

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        user_columns = {
            column["name"] for column in inspect(engine).get_columns("users")
        }
    finally:
        engine.dispose()

    missing_columns = BASELINE_USER_COLUMNS - user_columns
    if missing_columns:
        names = ", ".join(sorted(missing_columns))
        raise RuntimeError(
            "The existing users table does not match the expected baseline. "
            f"Missing columns: {names}."
        )

    command.stamp(config, BASELINE_REVISION)
    return True


def upgrade_database(database_url: str, *, bootstrap_existing: bool = True) -> str:
    """필요하면 기존 users를 stamp하고 DB를 최신 revision으로 올립니다."""
    config = build_alembic_config(database_url)
    if bootstrap_existing:
        _bootstrap_existing_users(database_url, config)

    command.upgrade(config, "head")
    revision, _ = _current_revision(database_url)
    if revision is None:
        raise RuntimeError("Alembic migration completed without a database revision.")
    return revision


def main() -> None:
    """환경변수 DATABASE_URL의 데이터베이스에 migration을 적용합니다."""
    database_url = get_database_url()
    if not database_url:
        raise RuntimeError("DATABASE_URL must be configured before running migrations.")

    revision = upgrade_database(database_url)
    print(f"Database migration complete: {revision}")


if __name__ == "__main__":
    main()

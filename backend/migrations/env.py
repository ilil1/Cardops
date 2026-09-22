"""Alembic이 CardOps SQLAlchemy metadata와 DB 연결을 사용하는 방법을 정의합니다."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from backend.app import models  # noqa: F401
from backend.app.config import get_database_url
from backend.app.database import Base


config = context.config

if config.config_file_name and config.get_section("loggers"):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _normalized_timestamp_default(value: str | None) -> str | None:
    if value is None:
        return None
    return value.lower().replace(" ", "").strip("()")


def _normalized_scalar_default(value: str | None) -> str | None:
    """MySQL이 숫자 기본값에 붙이는 따옴표·괄호 차이를 정규화합니다."""
    if value is None:
        return None
    return value.lower().replace(" ", "").strip("()'\"")


def _compare_server_default(
    migration_context,
    inspected_column,
    metadata_column,
    inspected_default,
    metadata_default,
    rendered_metadata_default,
):
    """MySQL의 now()/CURRENT_TIMESTAMP 동의어를 변경으로 오인하지 않습니다."""
    if migration_context.dialect.name == "mysql":
        inspected = _normalized_timestamp_default(inspected_default)
        rendered = _normalized_timestamp_default(rendered_metadata_default)
        timestamp_defaults = {"now", "current_timestamp"}
        if inspected in timestamp_defaults and rendered in timestamp_defaults:
            return False
        inspected_scalar = _normalized_scalar_default(inspected_default)
        rendered_scalar = _normalized_scalar_default(rendered_metadata_default)
        if inspected_scalar == rendered_scalar:
            return False
        try:
            if (
                inspected_scalar is not None
                and rendered_scalar is not None
                and Decimal(inspected_scalar) == Decimal(rendered_scalar)
            ):
                return False
        except InvalidOperation:
            pass
    return None


def _database_url() -> str:
    """프로그램 주입값, 환경변수, ini 순으로 연결 주소를 선택합니다."""
    injected_url = config.attributes.get("database_url")
    if injected_url:
        return str(injected_url)

    environment_url = get_database_url() or os.getenv("DATABASE_URL")
    if environment_url:
        return environment_url

    return config.get_main_option("sqlalchemy.url")


def run_migrations_offline() -> None:
    """DB 연결 없이 SQL 스크립트를 생성하는 offline 모드입니다."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=_compare_server_default,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """실제 DB 연결에서 migration을 실행하는 online 모드입니다."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=_compare_server_default,
            render_as_batch=connection.dialect.name == "sqlite",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

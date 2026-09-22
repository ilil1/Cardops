"""SQLAlchemy 엔진과 요청 단위 세션을 관리합니다."""

from __future__ import annotations

from collections.abc import Generator

from fastapi import HTTPException, Request, status
from sqlalchemy import MetaData, create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """애플리케이션 테이블이 상속하는 SQLAlchemy 선언 기반입니다."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def initialize_database(
    database_url: str,
) -> tuple[Engine, sessionmaker[Session]]:
    """Alembic으로 준비된 DB에 연결할 엔진과 세션 팩터리를 만듭니다."""
    # 함수 호출 시점에 모델을 가져와 Base.metadata에 모든 관리 테이블이
    # 등록되도록 합니다. 실제 생성·변경은 create_all이 아니라 Alembic이 맡습니다.
    from . import models  # noqa: F401

    engine = create_engine(
        database_url,
        pool_pre_ping=True,
    )
    table_names = set(inspect(engine).get_table_names())
    required_tables = set(Base.metadata.tables)
    missing_tables = sorted(required_tables - table_names)
    if "alembic_version" not in table_names or missing_tables:
        engine.dispose()
        missing = ", ".join(missing_tables) if missing_tables else "none"
        raise RuntimeError(
            "Database schema is not migrated. Run "
            "`python -m backend.app.migration_runner` before starting the API. "
            f"Missing tables: {missing}."
        )

    return engine, sessionmaker(
        bind=engine,
        class_=Session,
        expire_on_commit=False,
    )


def get_db(request: Request) -> Generator[Session, None, None]:
    """현재 애플리케이션이 준비한 DB 세션을 요청 단위로 제공합니다."""
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The database is not configured.",
        )

    session = session_factory()
    try:
        yield session
    finally:
        session.close()

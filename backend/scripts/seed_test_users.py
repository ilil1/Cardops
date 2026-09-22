"""로컬 개발용 역할별 테스트 계정을 MySQL에 생성하거나 갱신합니다."""

from __future__ import annotations

from dataclasses import dataclass
import os

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.app.api.routes.auth import hash_password
from backend.app.config import (
    get_allow_test_user_seeding,
    get_app_env,
    get_database_url,
    get_poc_seed_enabled,
)
from backend.app.database import initialize_database
from backend.app.enums import UserRole
from backend.app.models import User


@dataclass(frozen=True)
class TestUser:
    """시드할 로컬 테스트 계정 정보입니다."""

    username: str
    display_name: str
    password_env: str
    role: UserRole


TEST_USER_SPECS = (
    TestUser(
        username="test_admin",
        display_name="테스트 관리자",
        password_env="TEST_ADMIN_PASSWORD",
        role=UserRole.ADMIN,
    ),
    TestUser(
        username="test_analyst",
        display_name="테스트 분석팀",
        password_env="TEST_ANALYST_PASSWORD",
        role=UserRole.ANALYST,
    ),
    TestUser(
        username="test_operations",
        display_name="테스트 운영팀",
        password_env="TEST_OPERATIONS_PASSWORD",
        role=UserRole.OPERATIONS,
    ),
    TestUser(
        username="test_marketing",
        display_name="테스트 마케팅팀",
        password_env="TEST_MARKETING_PASSWORD",
        role=UserRole.MARKETING,
    ),
)


def _validate_local_seeding(database_url: str) -> None:
    """운영 환경이나 원격 DB에 테스트 계정이 생성되지 않도록 차단합니다."""
    if get_poc_seed_enabled():
        return
    if not get_allow_test_user_seeding():
        raise RuntimeError(
            "Test user seeding is disabled. Set ALLOW_TEST_USER_SEEDING=true "
            "only in a local development environment."
        )
    if get_app_env() not in {"local", "development", "test"}:
        raise RuntimeError(
            "Test user seeding is only allowed when APP_ENV is local, development, or test."
        )
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" and url.host not in {
        "127.0.0.1",
        "localhost",
        "mysql",
    }:
        raise RuntimeError("Test users can only be seeded into a local database host.")


def _passwords() -> dict[str, str]:
    passwords: dict[str, str] = {}
    missing: list[str] = []
    for spec in TEST_USER_SPECS:
        value = os.getenv(spec.password_env, "")
        if len(value) < 12:
            missing.append(spec.password_env)
        else:
            passwords[spec.password_env] = value
    if missing:
        raise RuntimeError(
            "Set strong local test passwords (12+ characters): " + ", ".join(missing)
        )
    return passwords


def seed_test_users(session: Session) -> list[User]:
    """테스트 계정을 역할별로 생성하고 재실행 시 최신 상태로 갱신합니다."""
    bind = session.get_bind()
    bind_url = bind.url if hasattr(bind, "url") else bind.engine.url
    _validate_local_seeding(str(bind_url))
    passwords = _passwords()
    users: list[User] = []
    for test_user in TEST_USER_SPECS:
        user = session.scalar(
            select(User).where(User.username == test_user.username),
        )
        if user is None:
            user = User(username=test_user.username)
            session.add(user)

        user.display_name = test_user.display_name
        user.password_hash = hash_password(passwords[test_user.password_env])
        user.role = test_user.role.value
        user.is_active = True
        users.append(user)

    session.commit()
    return users


def main() -> None:
    """환경변수 DATABASE_URL의 DB에 로컬 테스트 계정을 저장합니다."""
    database_url = get_database_url()
    if not database_url:
        raise RuntimeError("DATABASE_URL must be configured before seeding test users.")

    _validate_local_seeding(database_url)
    engine, session_factory = initialize_database(database_url)
    try:
        with session_factory() as session:
            users = seed_test_users(session)
    finally:
        engine.dispose()

    print("Test users seeded:")
    for user in users:
        print(f"- {user.username} ({user.role})")


if __name__ == "__main__":
    main()

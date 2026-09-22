"""회원가입, 로그인, 로그아웃과 인증 쿠키를 제공하는 API입니다."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from jwt import InvalidTokenError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...config import (
    AUTH_COOKIE_NAME,
    get_auth_cookie_secure,
    get_jwt_secret,
    get_login_rate_limit,
)
from ...database import get_db
from ...enums import UserRole
from ...models import AuthEvent, User
from ...schemas import (
    AuthResponse,
    LoginRequest,
    SignupRequest,
    TeamMemberResponse,
    UserAdminUpdateRequest,
    UserResponse,
)


auth_router = APIRouter(
    prefix="/api/v1/auth",
    tags=["auth"],
)
password_hasher = PasswordHasher()
DUMMY_PASSWORD_HASH = password_hasher.hash("cardops-invalid-login-placeholder")
ACCESS_TOKEN_ALGORITHM = "HS256"
DEFAULT_SESSION_SECONDS = 60 * 60 * 8
REMEMBERED_SESSION_SECONDS = 60 * 60 * 24 * 30


def hash_password(password: str) -> str:
    """비밀번호를 Argon2id 해시로 변환합니다."""
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """입력 비밀번호가 저장된 Argon2 해시와 일치하는지 확인합니다."""
    try:
        return password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError):
        return False


def _require_jwt_secret(request: Request) -> str:
    """애플리케이션 상태 또는 환경변수에서 JWT 서명 키를 가져옵니다."""
    secret = getattr(request.app.state, "jwt_secret", None) or get_jwt_secret()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured.",
        )
    return secret


def _create_access_token(
    user_id: int,
    secret: str,
    lifetime_seconds: int,
) -> str:
    """사용자 식별자와 만료 시각을 포함한 JWT를 생성합니다."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(seconds=lifetime_seconds),
    }
    return jwt.encode(payload, secret, algorithm=ACCESS_TOKEN_ALGORITHM)


def _set_auth_cookie(response: Response, token: str, max_age: int) -> None:
    """브라우저 JavaScript에서 읽을 수 없는 인증 쿠키를 설정합니다."""
    secure = get_auth_cookie_secure()
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        # Render 프론트/백엔드는 서로 다른 origin이므로 배포 HTTPS에서는
        # cross-origin fetch에서도 인증 쿠키가 전달되도록 SameSite=None을 사용합니다.
        # 로컬 HTTP에서는 Secure 쿠키가 동작하지 않으므로 기존 lax를 유지합니다.
        samesite="none" if secure else "lax",
        path="/",
    )


def _authentication_error() -> HTTPException:
    """인증 실패 시 계정 존재 여부가 노출되지 않는 공통 오류를 반환합니다."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid username or password.",
    )


def _client_ip(request: Request) -> str | None:
    """신뢰할 수 없는 전달 헤더 대신 ASGI가 확인한 원격 주소를 사용합니다."""
    return request.client.host[:64] if request.client is not None else None


def _add_auth_event(
    db: Session,
    *,
    event_type: str,
    username: str | None,
    request: Request | None,
    user: User | None = None,
    actor: User | None = None,
    metadata_json: dict[str, object] | None = None,
) -> None:
    db.add(
        AuthEvent(
            user_id=user.id if user is not None else None,
            username=username,
            event_type=event_type,
            ip_address=_client_ip(request) if request is not None else None,
            actor_user_id=actor.id if actor is not None else None,
            metadata_json=metadata_json,
        )
    )


def _enforce_login_rate_limit(
    db: Session,
    *,
    username: str,
    request: Request,
) -> None:
    """최근 실패를 사용자·IP 조합과 IP 전체 기준으로 제한합니다."""
    # max_attempts, _ip_max_attempts, window_seconds = get_login_rate_limit()
    # cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    # ip_address = _client_ip(request)
    # pair_conditions = [
    #     AuthEvent.event_type == "login_failed",
    #     AuthEvent.created_at >= cutoff,
    #     AuthEvent.username == username,
    # ]
    # if ip_address is None:
    #     pair_conditions.append(AuthEvent.ip_address.is_(None))
    # else:
    #     pair_conditions.append(AuthEvent.ip_address == ip_address)
    # success_conditions = [
    #     AuthEvent.event_type == "login_succeeded",
    #     AuthEvent.created_at >= cutoff,
    #     AuthEvent.username == username,
    # ]
    # if ip_address is None:
    #     success_conditions.append(AuthEvent.ip_address.is_(None))
    # else:
    #     success_conditions.append(AuthEvent.ip_address == ip_address)
    # latest_success_at = db.scalar(
    #     select(func.max(AuthEvent.created_at)).where(*success_conditions)
    # )
    # if latest_success_at is not None:
    #     pair_conditions.append(AuthEvent.created_at > latest_success_at)
    # pair_failures = int(
    #     db.scalar(select(func.count(AuthEvent.id)).where(*pair_conditions)) or 0
    # )
    # ip_failures = 0
    # # IP 전체 기준 제한은 비활성화합니다.
    # # if ip_address is not None:
    # #     ip_failures = int(
    # #         db.scalar(
    # #             select(func.count(AuthEvent.id)).where(
    # #                 AuthEvent.event_type == "login_failed",
    # #                 AuthEvent.created_at >= cutoff,
    # #                 AuthEvent.ip_address == ip_address,
    # #             )
    # #         )
    # #         or 0
    # #     )
    # if pair_failures < max_attempts:
    #     return
    # _add_auth_event(
    #     db,
    #     event_type="login_rate_limited",
    #     username=username,
    #     request=request,
    #     metadata_json={
    #         "pair_failures": pair_failures,
    #         "ip_failures": ip_failures,
    #         "window_seconds": window_seconds,
    #     },
    # )
    # db.commit()
    # raise HTTPException(
    #     status_code=status.HTTP_429_TOO_MANY_REQUESTS,
    #     detail="Too many login attempts. Try again later.",
    #     headers={"Retry-After": str(window_seconds)},
    # )
    return


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """HttpOnly 인증 쿠키를 검증하고 현재 사용자를 반환합니다."""
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is required.",
        )

    secret = _require_jwt_secret(request)
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[ACCESS_TOKEN_ALGORITHM],
        )
        subject = payload.get("sub")
        user_id = int(subject) if subject is not None else 0
    except (InvalidTokenError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication.",
        ) from None

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The authenticated user is no longer available.",
        )
    return user


def require_roles(*allowed_roles: UserRole):
    """지정된 업무 역할만 접근할 수 있는 FastAPI 의존성을 만듭니다."""

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in {role.value for role in allowed_roles}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission for this operation.",
            )
        return current_user

    return dependency


@auth_router.get(
    "/users",
    response_model=list[TeamMemberResponse],
    summary="팀 계정 목록 조회",
)
def list_team_members(
    include_inactive: bool = Query(
        default=False,
        description="관리자만 비활성 계정까지 포함할 수 있습니다.",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TeamMemberResponse]:
    """담당자 선택과 관리자 화면에서 사용할 팀 계정을 조회합니다."""
    if include_inactive and current_user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can view inactive users.",
        )

    query = select(User)
    if not include_inactive:
        query = query.where(User.is_active.is_(True))
    users = db.scalars(
        query.order_by(
            User.is_active.desc(),
            User.role.asc(),
            User.display_name.asc(),
            User.id.asc(),
        ),
    ).all()
    return [TeamMemberResponse.model_validate(user) for user in users]


@auth_router.patch(
    "/users/{user_id}",
    response_model=TeamMemberResponse,
    summary="팀 계정 역할·활성 상태 변경",
)
def update_team_member(
    user_id: int,
    payload: UserAdminUpdateRequest,
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> TeamMemberResponse:
    """관리자가 팀 계정의 역할과 활성 상태를 변경합니다."""
    active_admins = db.scalars(
        select(User)
        .where(
            User.role == UserRole.ADMIN.value,
            User.is_active.is_(True),
        )
        .order_by(User.id)
        .with_for_update()
    ).all()
    user = next((admin for admin in active_admins if admin.id == user_id), None)
    if user is None:
        user = db.scalar(
            select(User).where(User.id == user_id).with_for_update()
        )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The team member was not found.",
        )

    next_role = payload.role.value if payload.role is not None else user.role
    next_is_active = payload.is_active if payload.is_active is not None else user.is_active
    if user.role == UserRole.ADMIN.value and next_role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Administrator roles cannot be changed to another role.",
        )
    if user.id == current_user.id and not next_is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own account.",
        )

    is_removing_admin = (
        user.role == UserRole.ADMIN.value
        and (next_role != UserRole.ADMIN.value or not next_is_active)
    )
    if is_removing_admin:
        active_admin_count = len(active_admins)
        if active_admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one active administrator must remain.",
            )

    previous = {"role": user.role, "is_active": bool(user.is_active)}
    if payload.role is not None:
        user.role = next_role
    if payload.is_active is not None:
        user.is_active = next_is_active
    _add_auth_event(
        db,
        event_type="user_updated",
        username=user.username,
        request=None,
        user=user,
        actor=current_user,
        metadata_json={
            "before": previous,
            "after": {"role": user.role, "is_active": bool(user.is_active)},
        },
    )
    db.commit()
    db.refresh(user)
    return TeamMemberResponse.model_validate(user)


@auth_router.post(
    "/signup",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="팀 계정 회원가입",
)
def signup(
    payload: SignupRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> AuthResponse:
    """새 팀 계정을 만들고 사용자 정보를 반환합니다."""
    existing_user = db.scalar(
        select(User).where(User.username == payload.username),
    )
    if existing_user is not None:
        _add_auth_event(
            db,
            event_type="signup_requested",
            username=payload.username,
            request=request,
            user=existing_user,
            metadata_json={"accepted": False, "reason": "duplicate_username"},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The username is already registered.",
        )

    user = User(
        username=payload.username,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        role=UserRole.ANALYST.value,
        is_active=False,
    )
    db.add(user)
    try:
        db.flush()
        _add_auth_event(
            db,
            event_type="signup_requested",
            username=user.username,
            request=request,
            user=user,
            metadata_json={"accepted": True, "approval_status": "pending"},
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The username is already registered.",
        ) from None

    db.refresh(user)
    return AuthResponse(user=UserResponse.model_validate(user))


@auth_router.post(
    "/login",
    response_model=AuthResponse,
    summary="팀 계정 로그인",
)
def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
) -> AuthResponse:
    """자격 증명을 검증하고 HttpOnly 세션 쿠키를 발급합니다."""
    _enforce_login_rate_limit(db, username=payload.username, request=request)
    user = db.scalar(
        select(User).where(User.username == payload.username),
    )
    password_valid = verify_password(
        payload.password,
        user.password_hash if user is not None else DUMMY_PASSWORD_HASH,
    )
    if user is None or not user.is_active or not password_valid:
        _add_auth_event(
            db,
            event_type="login_failed",
            username=payload.username,
            request=request,
            user=user,
            metadata_json={"reason": "invalid_credentials"},
        )
        db.commit()
        raise _authentication_error()

    lifetime = (
        REMEMBERED_SESSION_SECONDS
        if payload.remember_me
        else DEFAULT_SESSION_SECONDS
    )
    token = _create_access_token(
        user_id=user.id,
        secret=_require_jwt_secret(request),
        lifetime_seconds=lifetime,
    )
    if password_hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    _add_auth_event(
        db,
        event_type="login_succeeded",
        username=user.username,
        request=request,
        user=user,
        metadata_json={"remember_me": payload.remember_me},
    )
    db.commit()
    _set_auth_cookie(response, token, lifetime)
    return AuthResponse(user=UserResponse.model_validate(user))


@auth_router.get(
    "/me",
    response_model=UserResponse,
    summary="현재 로그인 사용자 조회",
)
def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """현재 인증 쿠키에 연결된 사용자 정보를 반환합니다."""
    return UserResponse.model_validate(current_user)


@auth_router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="로그아웃",
)
def logout(
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
) -> None:
    """브라우저의 인증 쿠키를 삭제합니다."""
    token = request.cookies.get(AUTH_COOKIE_NAME)
    secret = getattr(request.app.state, "jwt_secret", None)
    user = None
    if token and secret:
        try:
            payload = jwt.decode(token, secret, algorithms=[ACCESS_TOKEN_ALGORITHM])
            subject = payload.get("sub")
            user = db.get(User, int(subject)) if subject is not None else None
        except (InvalidTokenError, TypeError, ValueError):
            user = None
    if user is not None:
        _add_auth_event(
            db,
            event_type="logout",
            username=user.username,
            request=request,
            user=user,
        )
        db.commit()
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path="/",
    )

"""얼굴 인증 API — 얼굴만으로 회원가입, 1:N 식별 로그인.

세션 발급(JWT 쿠키), 레이트리밋, 감사로그는 전부 기존 auth 모듈을
재사용합니다. 얼굴은 "무엇을 아는가(비밀번호)"를 "무엇인가(생체)"로
바꿀 뿐, 가입 승인 절차와 로그인 이후의 권한 체계는 동일합니다.

보안 경계:
- 임베딩은 서버가 원본 이미지에서 직접 추출합니다. 클라이언트 임베딩을
  받으면 벡터 재전송만으로 로그인되므로 절대 허용하지 않습니다.
- 실패는 login_failed(metadata.method="face")로 기록되어 기존 IP
  레이트리밋에 그대로 합산됩니다.
- 얼굴 가입 계정은 아무도 모르는 무작위 비밀번호 해시를 저장해
  비밀번호 로그인 경로를 사실상 봉인합니다.
- 라이브니스 검사는 없습니다(로컬 데모 범위). 사진 재생 공격을 막지
  못한다는 한계를 UI에도 표기합니다.
"""

from __future__ import annotations

import secrets

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..api.routes.auth import (
    DEFAULT_SESSION_SECONDS,
    _add_auth_event,
    _create_access_token,
    _enforce_login_rate_limit,
    _require_jwt_secret,
    _set_auth_cookie,
    hash_password,
)
from ..database import get_db
from ..enums import UserRole
from ..models import User
from ..schemas import (
    USERNAME_PATTERN,
    AuthResponse,
    UserResponse,
    normalize_username,
)
from .engine import (
    SIMILARITY_THRESHOLD,
    FaceAuthError,
    FaceModelUnavailableError,
    average_embeddings,
    decode_base64_image,
    get_face_engine,
    identify,
)
from .models import UserFaceCredential

face_auth_router = APIRouter(prefix="/api/v1/auth/face", tags=["face-auth"])

# 얼굴 로그인은 시도 시점에 사용자명이 없으므로, 레이트리밋의 사용자·IP
# 조합 키로 이 센티널을 사용합니다. IP 전체 제한은 그대로 적용됩니다.
FACE_LOGIN_RATE_KEY = "@face-login"
MAX_SIGNUP_FRAMES = 50


class FaceLoginRequest(BaseModel):
    image: str = Field(min_length=32, description="JPEG/PNG의 base64 또는 data URL")


class FaceDetectRequest(BaseModel):
    image: str = Field(min_length=32)


class FaceDetectResponse(BaseModel):
    face_count: int


class FaceSignupRequest(BaseModel):
    """비밀번호 없이 얼굴만으로 가입하는 요청입니다."""

    username: str = Field(min_length=3, max_length=50, pattern=USERNAME_PATTERN)
    display_name: str = Field(min_length=1, max_length=100)
    images: list[str] = Field(min_length=1, max_length=MAX_SIGNUP_FRAMES)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_signup_username(cls, value: object) -> object:
        return normalize_username(value)

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_display_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class FaceAvailabilityResponse(BaseModel):
    available: bool
    any_enrolled: bool


def _face_error_response(error: FaceAuthError) -> HTTPException:
    if isinstance(error, FaceModelUnavailableError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="얼굴 인증 모델이 준비되지 않았습니다. 관리자에게 문의하세요.",
        )
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=str(error),
    )


def _embed_frames(images: list[str]) -> np.ndarray:
    """가입용 다중 프레임에서 평균 임베딩을 추출합니다(프레임당 얼굴 1개 강제)."""
    engine = get_face_engine()
    embeddings: list[np.ndarray] = []
    for data in images:
        image = decode_base64_image(data)
        embeddings.append(engine.embed_image(image, require_single=True))
    return average_embeddings(embeddings)


def _find_similar_enrollment(
    db: Session,
    embedding: np.ndarray,
) -> int | None:
    """새 임베딩과 임계값 이상으로 비슷한 기존 등록자의 user_id를 찾습니다.

    같은 얼굴이 두 계정에 등록되면 1:N 식별의 1·2위 마진 규칙에 걸려
    두 계정 모두 얼굴 로그인이 막힙니다. 가입 시점에 차단해야 합니다.
    승인 대기(비활성) 계정의 등록도 포함해 비교합니다.
    """
    rows = db.execute(
        select(UserFaceCredential.user_id, UserFaceCredential.embedding)
    ).all()
    for user_id, stored in rows:
        similarity = float(np.dot(embedding, np.asarray(stored, dtype=np.float32)))
        if similarity >= SIMILARITY_THRESHOLD:
            return int(user_id)
    return None


def _load_enrolled_embeddings(db: Session) -> dict[int, np.ndarray]:
    rows = db.execute(
        select(UserFaceCredential.user_id, UserFaceCredential.embedding)
        .join(User, User.id == UserFaceCredential.user_id)
        .where(User.is_active.is_(True))
    ).all()
    return {
        int(user_id): np.asarray(embedding, dtype=np.float32)
        for user_id, embedding in rows
    }


@face_auth_router.get(
    "/availability",
    response_model=FaceAvailabilityResponse,
    summary="얼굴 인증 사용 가능 여부(비로그인)",
)
def face_availability(db: Session = Depends(get_db)) -> FaceAvailabilityResponse:
    enrolled = int(db.scalar(select(func.count(UserFaceCredential.id))) or 0)
    return FaceAvailabilityResponse(
        available=get_face_engine().is_available(),
        any_enrolled=enrolled > 0,
    )


@face_auth_router.post(
    "/detect",
    response_model=FaceDetectResponse,
    summary="프레임 내 얼굴 개수 확인(자동 인증 폴링용)",
)
def face_detect(payload: FaceDetectRequest) -> FaceDetectResponse:
    """검출만 수행합니다 — 매칭·감사로그·레이트리밋과 무관합니다.

    자동 인증 UI가 "얼굴이 화면에 있는가"를 주기적으로 확인하는 용도입니다.
    실패 시 레이트리밋에 집계되는 로그인 시도는 얼굴이 확인된 뒤 1회만
    발생하도록 클라이언트가 이 엔드포인트로 먼저 거릅니다.
    """
    try:
        image = decode_base64_image(payload.image)
        faces = get_face_engine().detect(image)
    except FaceAuthError as error:
        raise _face_error_response(error) from error
    return FaceDetectResponse(face_count=len(faces))


@face_auth_router.post(
    "/signup",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="얼굴만으로 회원가입(비밀번호 없음, 관리자 승인 대기)",
)
def face_signup(
    payload: FaceSignupRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> AuthResponse:
    existing_user = db.scalar(select(User).where(User.username == payload.username))
    if existing_user is not None:
        _add_auth_event(
            db,
            event_type="signup_requested",
            username=payload.username,
            request=request,
            user=existing_user,
            metadata_json={
                "accepted": False,
                "reason": "duplicate_username",
                "method": "face",
            },
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 사용 중인 아이디입니다.",
        )

    try:
        mean_embedding = _embed_frames(payload.images)
    except FaceAuthError as error:
        raise _face_error_response(error) from error

    duplicate_user_id = _find_similar_enrollment(db, mean_embedding)
    if duplicate_user_id is not None:
        _add_auth_event(
            db,
            event_type="signup_requested",
            username=payload.username,
            request=request,
            metadata_json={
                "accepted": False,
                "reason": "duplicate_face",
                "method": "face",
            },
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 다른 계정에 등록된 얼굴입니다.",
        )

    user = User(
        username=payload.username,
        display_name=payload.display_name,
        # 얼굴 전용 계정 — 아무도 모르는 무작위 비밀번호를 해시로 저장해
        # 비밀번호 경로를 사실상 봉인합니다.
        password_hash=hash_password(secrets.token_urlsafe(32)),
        role=UserRole.ANALYST.value,
        is_active=False,
    )
    db.add(user)
    try:
        db.flush()
        db.add(
            UserFaceCredential(
                user_id=user.id,
                embedding=mean_embedding.tolist(),
                sample_count=len(payload.images),
            )
        )
        _add_auth_event(
            db,
            event_type="signup_requested",
            username=user.username,
            request=request,
            user=user,
            metadata_json={
                "accepted": True,
                "approval_status": "pending",
                "method": "face",
                "sample_count": len(payload.images),
            },
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 사용 중인 아이디입니다.",
        ) from None

    db.refresh(user)
    return AuthResponse(user=UserResponse.model_validate(user))


@face_auth_router.post(
    "/login",
    response_model=AuthResponse,
    summary="얼굴 1:N 식별 로그인",
)
def face_login(
    payload: FaceLoginRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
) -> AuthResponse:
    _enforce_login_rate_limit(db, username=FACE_LOGIN_RATE_KEY, request=request)

    def _reject(reason: str) -> HTTPException:
        _add_auth_event(
            db,
            event_type="login_failed",
            username=FACE_LOGIN_RATE_KEY,
            request=request,
            metadata_json={"method": "face", "reason": reason},
        )
        db.commit()
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="등록된 얼굴과 일치하지 않습니다.",
        )

    try:
        image = decode_base64_image(payload.image)
        probe = get_face_engine().embed_image(image, require_single=False)
    except FaceAuthError as error:
        raise _face_error_response(error) from error

    enrolled = _load_enrolled_embeddings(db)
    if not enrolled:
        raise _reject("no_enrollment")
    match = identify(probe, enrolled)
    if match is None:
        raise _reject("no_match")

    user = db.get(User, match.user_id)
    if user is None or not user.is_active:
        raise _reject("inactive_user")

    token = _create_access_token(
        user_id=user.id,
        secret=_require_jwt_secret(request),
        lifetime_seconds=DEFAULT_SESSION_SECONDS,
    )
    _add_auth_event(
        db,
        event_type="login_succeeded",
        username=user.username,
        request=request,
        user=user,
        metadata_json={
            "method": "face",
            "similarity": round(match.similarity, 4),
            "margin": round(match.margin, 4) if match.margin is not None else None,
        },
    )
    db.commit()
    _set_auth_cookie(response, token, DEFAULT_SESSION_SECONDS)
    return AuthResponse(user=UserResponse.model_validate(user))

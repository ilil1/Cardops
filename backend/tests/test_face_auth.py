"""얼굴 인증 매칭 로직과 API 흐름을 검증합니다.

ONNX 모델은 무겁고 결정적 테스트가 어려우므로, 라우트 테스트에서는
임베딩 추출기(FaceEngine)를 가짜로 바꾸고 가입·매칭·세션 발급 로직만
검증합니다. 순수 매칭 규칙(임계값·마진)은 단위 테스트로 직접 확인합니다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.face import routes as face_routes
from backend.app.face.engine import (
    SIMILARITY_THRESHOLD,
    TOP2_MARGIN,
    average_embeddings,
    identify,
)
from backend.app.face.models import UserFaceCredential
from backend.app.main import create_app
from backend.app.migration_runner import upgrade_database
from backend.app.models import User
from backend.tests.test_api import (  # noqa: F401
    FakeClassifier,
    make_manifest,
    write_manifest,
)

# 라우트의 min_length=32 검증을 통과하는 무의미한 base64 페이로드입니다.
FAKE_IMAGE = "ZmFrZS1pbWFnZS1wYXlsb2FkLWZvci10ZXN0cw=="


def _unit(vector: list[float]) -> np.ndarray:
    array = np.asarray(vector, dtype=np.float32)
    return array / np.linalg.norm(array)


# ------------------------------------------------------------------ 단위: 매칭
def test_identify_rejects_below_threshold() -> None:
    """임계값 미만 유사도는 등록자가 있어도 거부합니다."""
    enrolled = {1: _unit([1.0, 0.0, 0.0])}
    probe = _unit([0.0, 1.0, 0.0])  # 코사인 0.0

    assert identify(probe, enrolled) is None


def test_identify_accepts_single_enrollee_above_threshold() -> None:
    """등록자가 1명이면 마진 규칙 없이 임계값만 적용합니다."""
    target = _unit([1.0, 0.2, 0.1])
    enrolled = {7: target}

    result = identify(target, enrolled)

    assert result is not None
    assert result.user_id == 7
    assert result.similarity == pytest.approx(1.0, abs=1e-5)
    assert result.margin is None


def test_identify_rejects_when_top2_margin_is_narrow() -> None:
    """1·2위 격차가 좁으면(등록자끼리 비슷하면) 오인식 방지를 위해 거부합니다."""
    base = _unit([1.0, 0.0, 0.0])
    # 두 등록자가 거의 같은 방향 → probe가 어느 쪽인지 확신할 수 없습니다.
    enrolled = {1: base, 2: _unit([1.0, 0.02, 0.0])}

    assert identify(base, enrolled, threshold=0.4, margin=TOP2_MARGIN) is None


def test_identify_accepts_with_clear_margin() -> None:
    """1위가 임계값을 넘고 2위와 충분히 벌어지면 그 사용자로 식별합니다."""
    enrolled = {1: _unit([1.0, 0.0, 0.0]), 2: _unit([0.0, 1.0, 0.0])}
    probe = _unit([0.95, 0.05, 0.0])

    result = identify(probe, enrolled)

    assert result is not None
    assert result.user_id == 1
    assert result.similarity >= SIMILARITY_THRESHOLD
    assert result.margin is not None and result.margin >= TOP2_MARGIN


def test_average_embeddings_is_renormalized() -> None:
    """다중 프레임 평균은 다시 단위 벡터가 되어야 내적=코사인이 성립합니다."""
    frames = [_unit([1.0, 0.0]), _unit([0.8, 0.2]), _unit([0.9, 0.1])]

    mean = average_embeddings(frames)

    assert np.linalg.norm(mean) == pytest.approx(1.0, abs=1e-6)


# ------------------------------------------------------------------ 라우트
class FakeEngine:
    """다음 호출이 반환할 임베딩을 테스트가 직접 지정하는 가짜 추출기입니다."""

    def __init__(self) -> None:
        self.next_embedding: np.ndarray | None = None
        self.next_face_count: int = 1

    def is_available(self) -> bool:
        return True

    def detect(self, image):  # noqa: ANN001
        return [object()] * self.next_face_count

    def embed_image(self, image, *, require_single: bool) -> np.ndarray:  # noqa: ANN001
        assert self.next_embedding is not None, "테스트가 next_embedding을 설정해야 합니다"
        return self.next_embedding


@pytest.fixture()
def face_client(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, FakeEngine]]:
    """가짜 얼굴 엔진을 주입한 SQLite 기반 TestClient입니다."""
    import joblib

    model_dir: Path = tmp_path_factory.mktemp("face-models")
    artifact_path = model_dir / "classification_xgboost.joblib"
    joblib.dump(FakeClassifier(), artifact_path)
    write_manifest(model_dir, make_manifest(artifact_path))

    database_path = tmp_path_factory.mktemp("face-auth") / "face.sqlite3"
    database_url = f"sqlite:///{database_path}"
    upgrade_database(database_url)

    engine = FakeEngine()
    monkeypatch.setattr(face_routes, "get_face_engine", lambda: engine)
    # 이미지 디코딩은 엔진을 가짜로 바꿨으므로 통과만 하면 됩니다.
    monkeypatch.setattr(
        face_routes, "decode_base64_image", lambda data: np.zeros((4, 4, 3))
    )

    with TestClient(
        create_app(
            model_dir=model_dir,
            database_url=database_url,
            jwt_secret="face-test-jwt-secret-0123456789abcdef",
        )
    ) as client:
        yield client, engine


def _create_active_user(client: TestClient, username: str) -> None:
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "username": username,
            "display_name": username,
            "password": "strong-password-123",
        },
    )
    assert response.status_code == 201
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        user = session.scalar(select(User).where(User.username == username))
        user.is_active = True
        session.commit()


def test_face_signup_pending_then_login_after_activation(
    face_client: tuple[TestClient, FakeEngine],
) -> None:
    """얼굴 가입은 승인 대기로 생성되고, 승인 후에만 얼굴 로그인이 됩니다."""
    client, engine = face_client
    my_face = _unit([1.0] + [0.0] * 511)

    engine.next_embedding = my_face
    signup = client.post(
        "/api/v1/auth/face/signup",
        json={
            "username": "Face_Only_User",
            "display_name": "얼굴가입",
            "images": [FAKE_IMAGE] * 3,
        },
    )
    assert signup.status_code == 201
    assert signup.json()["user"]["username"] == "face_only_user"

    session_factory = client.app.state.session_factory
    with session_factory() as session:
        user = session.scalar(select(User).where(User.username == "face_only_user"))
        assert user is not None and user.is_active is False
        credential = session.scalar(
            select(UserFaceCredential).where(UserFaceCredential.user_id == user.id)
        )
        assert credential is not None and credential.sample_count == 3
        assert len(credential.embedding) == 512
        assert float(
            np.linalg.norm(np.asarray(credential.embedding))
        ) == pytest.approx(1.0, abs=1e-5)

    # 승인 전 — 활성 사용자만 매칭 대상이므로 로그인 불가.
    engine.next_embedding = my_face
    assert (
        client.post("/api/v1/auth/face/login", json={"image": FAKE_IMAGE}).status_code
        == 401
    )

    with session_factory() as session:
        user = session.scalar(select(User).where(User.username == "face_only_user"))
        user.is_active = True
        session.commit()

    engine.next_embedding = my_face
    approved = client.post("/api/v1/auth/face/login", json={"image": FAKE_IMAGE})
    assert approved.status_code == 200
    assert approved.json()["user"]["username"] == "face_only_user"
    # 세션 쿠키가 실제로 동작하는지 확인합니다.
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "face_only_user"

    # 다른 얼굴(직교 벡터) → 401 거부.
    assert client.post("/api/v1/auth/logout").status_code == 204
    engine.next_embedding = _unit([0.0, 1.0] + [0.0] * 510)
    rejected = client.post("/api/v1/auth/face/login", json={"image": FAKE_IMAGE})
    assert rejected.status_code == 401


def test_face_signup_rejects_duplicate_username(
    face_client: tuple[TestClient, FakeEngine],
) -> None:
    client, engine = face_client
    _create_active_user(client, "taken_name")

    engine.next_embedding = _unit([1.0] + [0.0] * 511)
    response = client.post(
        "/api/v1/auth/face/signup",
        json={
            "username": "taken_name",
            "display_name": "중복",
            "images": [FAKE_IMAGE] * 3,
        },
    )
    assert response.status_code == 409


def test_face_signup_rejects_duplicate_face(
    face_client: tuple[TestClient, FakeEngine],
) -> None:
    """같은 얼굴로 두 계정을 만들면 마진 규칙상 둘 다 로그인이 막히므로 차단합니다."""
    client, engine = face_client
    shared_face = _unit([1.0] + [0.0] * 511)

    engine.next_embedding = shared_face
    first = client.post(
        "/api/v1/auth/face/signup",
        json={"username": "face_a", "display_name": "A", "images": [FAKE_IMAGE] * 3},
    )
    assert first.status_code == 201

    engine.next_embedding = shared_face
    second = client.post(
        "/api/v1/auth/face/signup",
        json={"username": "face_b", "display_name": "B", "images": [FAKE_IMAGE] * 3},
    )
    assert second.status_code == 409
    assert "얼굴" in second.json()["detail"]


def test_face_login_without_any_enrollment_is_rejected(
    face_client: tuple[TestClient, FakeEngine],
) -> None:
    """아무도 등록하지 않았으면 얼굴 로그인은 항상 401입니다."""
    client, engine = face_client
    engine.next_embedding = _unit([1.0] + [0.0] * 511)

    response = client.post("/api/v1/auth/face/login", json={"image": FAKE_IMAGE})

    assert response.status_code == 401


def test_face_availability_is_public(
    face_client: tuple[TestClient, FakeEngine],
) -> None:
    """가용성 조회는 로그인 없이 접근 가능하며 등록 여부 힌트만 줍니다."""
    client, _ = face_client

    response = client.get("/api/v1/auth/face/availability")

    assert response.status_code == 200
    assert response.json() == {"available": True, "any_enrolled": False}


def test_face_detect_reports_count_without_rate_limit(
    face_client: tuple[TestClient, FakeEngine],
) -> None:
    """검출 폴링은 얼굴 개수만 돌려주고 로그인 실패 집계에 잡히지 않습니다."""
    client, engine = face_client

    engine.next_face_count = 0
    empty = client.post("/api/v1/auth/face/detect", json={"image": FAKE_IMAGE})
    assert empty.status_code == 200
    assert empty.json() == {"face_count": 0}

    engine.next_face_count = 2
    crowded = client.post("/api/v1/auth/face/detect", json={"image": FAKE_IMAGE})
    assert crowded.status_code == 200
    assert crowded.json() == {"face_count": 2}

    # 검출을 아무리 반복해도 로그인 레이트리밋(login_failed)이 쌓이지 않아야
    # 자동 인증 폴링이 안전합니다.
    for _ in range(10):
        assert (
            client.post(
                "/api/v1/auth/face/detect", json={"image": FAKE_IMAGE}
            ).status_code
            == 200
        )
    engine.next_face_count = 1
    engine.next_embedding = _unit([1.0] + [0.0] * 511)
    login = client.post("/api/v1/auth/face/login", json={"image": FAKE_IMAGE})
    assert login.status_code == 401  # 등록자 없음 — 429가 아니어야 합니다

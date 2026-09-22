"""얼굴 인증용 임베딩 저장 테이블.

기존 backend/app/models.py를 수정하지 않기 위해 face 패키지 안에서 같은
Base에 등록합니다. routes.py가 이 모듈을 import하는 순간 매퍼가 등록되므로
별도의 연결 코드가 필요 없습니다.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from ..models import User


class UserFaceCredential(Base):
    """얼굴 로그인용 임베딩을 사용자당 하나 저장합니다.

    원본 얼굴 이미지는 저장하지 않습니다 — 512차원 L2 정규화 임베딩만
    보관하며, 임베딩에서 원본 얼굴을 복원할 수 없습니다.
    """

    __tablename__ = "user_face_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    # 512개 float 리스트. 벡터 검색 확장이 없는 MySQL이므로 JSON으로 두고
    # 매칭은 애플리케이션에서 수행합니다(팀 규모에서는 전수 비교로 충분).
    embedding: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    # 가입 시 사용한 프레임 수 — 품질 추적용.
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=func.now(),
    )

    user: Mapped[User] = relationship()

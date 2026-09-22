"""여러 API 라우터가 공유하는 FastAPI 의존성입니다."""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from ..model_registry import ModelRegistry


def get_registry(request: Request) -> ModelRegistry:
    """애플리케이션 시작 시 준비된 모델 레지스트리를 반환합니다."""
    registry = getattr(request.app.state, "model_registry", None)
    if registry is None or not registry.is_loaded:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The model registry is not ready.",
        )
    return registry

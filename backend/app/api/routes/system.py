"""생존·준비 상태 확인 API입니다."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...config import APP_NAME, APP_VERSION
from ...model_registry import ModelRegistry
from ...schemas import HealthResponse, LivenessResponse
from ..dependencies import get_registry


router = APIRouter(tags=["system"])


@router.get(
    "/live",
    response_model=LivenessResponse,
    summary="API 프로세스 생존 여부 확인",
)
def liveness() -> LivenessResponse:
    """모델 상태와 무관한 API 프로세스의 기본 생존 정보를 반환합니다."""
    return LivenessResponse(
        status="ok",
        service=APP_NAME,
        version=APP_VERSION,
    )


@router.get(
    "/ready",
    response_model=HealthResponse,
    summary="API와 모델의 요청 처리 준비 여부 확인",
)
def readiness(
    registry: ModelRegistry = Depends(get_registry),
) -> HealthResponse:
    """현재 적재된 모델의 준비 상태와 식별 정보를 반환합니다."""
    return HealthResponse(
        status="ok",
        service=APP_NAME,
        version=APP_VERSION,
        **registry.health(),
    )

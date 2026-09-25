"""온라인 고객 이탈 예측 API입니다."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ...model_registry import ModelPredictionError, ModelRegistry
from ...schemas import PredictionRequest, PredictionResponse
from ..dependencies import get_registry


router = APIRouter(prefix="/api/v1/predictions", tags=["predictions"])


@router.post(
    "",
    response_model=PredictionResponse,
    summary="고객 이탈 가능성 예측",
)
def create_prediction(
    payload: PredictionRequest,
    registry: ModelRegistry = Depends(get_registry),
) -> PredictionResponse:
    """검증된 고객 정보로 이탈 여부와 이탈 확률을 예측합니다."""
    try:
        result = registry.predict(payload.to_model_input())
    except ModelPredictionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The model could not produce a prediction.",
        ) from exc
    return PredictionResponse.model_validate(result)

"""모델 배치 실행 상태를 제공하는 인증 API입니다."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .auth import get_current_user
from ...database import get_db
from ...enums import ModelRunStatus
from ...models import ModelRun, User
from ...schemas import (
    LatestBatchResponse,
    ModelRunResponse,
    ScoringBatchHistoryItem,
    ScoringBatchHistoryResponse,
)
from ...services.model_run_service import (
    fetch_latest_scoring_batch,
    fetch_latest_successful_batch,
    fetch_scoring_batch_history,
)


model_runs_router = APIRouter(
    prefix="/api/v1/model-runs",
    tags=["model-runs"],
)


def _to_model_run_response(run: ModelRun) -> ModelRunResponse:
    return ModelRunResponse.model_validate(run)


@model_runs_router.get(
    "/latest",
    response_model=LatestBatchResponse,
    summary="최근 성공 모델 배치 조회",
)
def get_latest_batch(
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LatestBatchResponse:
    """대시보드에서 데이터 갱신 시각과 사용 모델을 확인할 수 있게 합니다."""
    scoring_batch = fetch_latest_scoring_batch(db)
    if scoring_batch is not None:
        runs = sorted(
            scoring_batch.model_runs,
            key=lambda run: (run.task, run.id),
        )
        if not runs:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No successful model batch was found.",
            )
        return LatestBatchResponse(
            scoring_batch_id=scoring_batch.id,
            attempt_number=scoring_batch.attempt_number,
            as_of_date=scoring_batch.as_of_date,
            decision_policy_id=scoring_batch.decision_policy_id,
            decision_policy_sha256=(
                scoring_batch.decision_policy.policy_sha256
            ),
            status=ModelRunStatus.SUCCEEDED,
            started_at=scoring_batch.started_at,
            completed_at=scoring_batch.completed_at,
            processed_rows=scoring_batch.processed_rows,
            dataset_sha256=scoring_batch.dataset_sha256,
            runs=[_to_model_run_response(run) for run in runs],
        )

    runs = fetch_latest_successful_batch(db)
    if not runs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No successful model batch was found.",
        )

    started_at = min(run.started_at for run in runs)
    completed_values = [run.completed_at for run in runs if run.completed_at]
    completed_at: datetime | None = max(completed_values) if completed_values else None
    processed_rows = max(
        (run.processed_rows for run in runs if run.processed_rows is not None),
        default=None,
    )
    dataset_sha256 = next(
        (run.dataset_sha256 for run in runs if run.dataset_sha256),
        None,
    )
    return LatestBatchResponse(
        scoring_batch_id=None,
        attempt_number=None,
        as_of_date=None,
        decision_policy_id=None,
        decision_policy_sha256=None,
        status=runs[0].status,
        started_at=started_at,
        completed_at=completed_at,
        processed_rows=processed_rows,
        dataset_sha256=dataset_sha256,
        runs=[_to_model_run_response(run) for run in runs],
    )


@model_runs_router.get(
    "/history",
    response_model=ScoringBatchHistoryResponse,
    summary="모델 배치 실행 이력 조회",
)
def get_scoring_batch_history(
    limit: int = Query(default=20, ge=1, le=100),
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ScoringBatchHistoryResponse:
    """상태(running/succeeded/failed)와 무관하게 최근 배치 이력을 반환합니다."""
    batches = fetch_scoring_batch_history(db, limit=limit)
    return ScoringBatchHistoryResponse(
        items=[ScoringBatchHistoryItem.model_validate(batch) for batch in batches]
    )

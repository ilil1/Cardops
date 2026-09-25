"""모델 배치 실행 이력 조회 규칙입니다."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..enums import ModelRunStatus
from ..models import ModelRun, ScoringBatch


def fetch_latest_scoring_batch(db: Session) -> ScoringBatch | None:
    """새 계보 구조에서 가장 최근 성공한 scoring batch를 반환합니다."""
    return db.scalar(
        select(ScoringBatch)
        .options(
            selectinload(ScoringBatch.model_runs),
            selectinload(ScoringBatch.decision_policy),
        )
        .where(ScoringBatch.status == ModelRunStatus.SUCCEEDED.value)
        .order_by(
            ScoringBatch.as_of_date.desc(),
            ScoringBatch.completed_at.desc(),
            ScoringBatch.id.desc(),
        )
        .limit(1)
    )


def fetch_scoring_batch_history(db: Session, *, limit: int = 20) -> list[ScoringBatch]:
    """상태와 무관하게 최근 scoring batch 이력을 최신순으로 반환합니다."""
    return db.scalars(
        select(ScoringBatch)
        .order_by(ScoringBatch.started_at.desc(), ScoringBatch.id.desc())
        .limit(limit)
    ).all()


def fetch_latest_successful_batch(db: Session) -> list[ModelRun]:
    """분류·회귀·군집별 가장 최근 성공 실행을 반환합니다."""
    runs = db.scalars(
        select(ModelRun)
        .where(ModelRun.status == ModelRunStatus.SUCCEEDED.value)
        .where(ModelRun.task.in_(["classification", "regression", "clustering"]))
        .order_by(ModelRun.started_at.desc(), ModelRun.id.desc())
    ).all()
    latest_by_task: dict[str, ModelRun] = {}
    for run in runs:
        latest_by_task.setdefault(run.task, run)
    return [
        latest_by_task[task]
        for task in ("classification", "regression", "clustering")
        if task in latest_by_task
    ]

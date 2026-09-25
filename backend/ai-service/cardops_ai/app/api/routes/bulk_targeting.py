"""분석 세그먼트 기반 일괄 타기팅의 preview·실행·취소·재실행 API입니다."""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import get_current_user, require_roles
from ...database import get_db
from ...enums import UserRole
from ...models import BulkTargetingRun, User
from ...schemas import (
    BulkTargetingPreviewItem,
    BulkTargetingPreviewRequest,
    BulkTargetingRerunRequest,
    BulkTargetingRunListResponse,
    BulkTargetingRunResponse,
)
from ...services.bulk_targeting_service import (
    BulkTargetingDomainError,
    BulkTargetingStateError,
    cancel_bulk_targeting,
    execute_bulk_targeting,
    fetch_bulk_targeting_preview_insights,
    fetch_bulk_targeting_runs,
    get_bulk_targeting_run,
    preview_bulk_targeting,
    rerun_bulk_targeting,
)


bulk_targeting_router = APIRouter(
    prefix="/api/v1/campaign-targeting",
    tags=["bulk-targeting"],
)
BULK_TARGETING_MUTATION_ROLES = (UserRole.ADMIN, UserRole.MARKETING)


def _domain_error(exc: BulkTargetingDomainError) -> HTTPException:
    if isinstance(exc, BulkTargetingStateError):
        return HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    return HTTPException(
        status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    )


def _to_preview_item(insight) -> BulkTargetingPreviewItem:
    return BulkTargetingPreviewItem(
        customer_id=insight.customer_id,
        customer_insight_id=insight.id,
        risk_level=insight.risk_level,
        cluster_name=insight.cluster_name,
        churn_probability=insight.churn_probability,
        expected_transaction_count=insight.expected_transaction_count,
        activity_gap=insight.activity_gap,
        recommended_action=insight.recommended_action,
        as_of_date=insight.as_of_date,
    )


def _to_response(
    run: BulkTargetingRun,
    *,
    db: Session,
    include_preview: bool = True,
) -> BulkTargetingRunResponse:
    rules = dict(run.rules_json)
    experiment_seed = rules.pop("experiment_seed", None)
    if experiment_seed:
        rules["experiment_assignment_policy"] = "sha256_seed_customer_v1"
        rules["experiment_seed_sha256"] = hashlib.sha256(
            str(experiment_seed).encode()
        ).hexdigest()
    insights = fetch_bulk_targeting_preview_insights(db, run) if include_preview else []
    items = (
        [_to_preview_item(insight) for insight in insights]
        if include_preview
        else []
    )
    return BulkTargetingRunResponse(
        id=run.id,
        segment=run.segment_code,
        status=run.status,
        campaign_id=run.campaign_id,
        campaign_name=str(rules["campaign_name"]),
        campaign_status=run.campaign.status if run.campaign is not None else None,
        requested_by_user_id=run.requested_by_user_id,
        rerun_of_id=run.rerun_of_id,
        source_as_of_date=run.source_as_of_date,
        scoring_batch_id=run.scoring_batch_id,
        rules=rules,
        preview_count=run.preview_count,
        eligible_count=run.eligible_count,
        created_count=run.created_count,
        skipped_active_campaign_count=run.skipped_active_campaign_count,
        skipped_recent_contact_count=run.skipped_recent_contact_count,
        skipped_opt_out_count=run.skipped_opt_out_count,
        cancelled_target_count=run.cancelled_target_count,
        items=items,
        created_at=run.created_at,
        executed_at=run.executed_at,
        cancelled_at=run.cancelled_at,
    )


@bulk_targeting_router.post(
    "/preview",
    response_model=BulkTargetingRunResponse,
    status_code=http_status.HTTP_201_CREATED,
    summary="세그먼트 일괄 타기팅 미리보기",
)
def preview_bulk_targeting_api(
    payload: BulkTargetingPreviewRequest,
    current_user: User = Depends(require_roles(*BULK_TARGETING_MUTATION_ROLES)),
    db: Session = Depends(get_db),
) -> BulkTargetingRunResponse:
    """고객을 생성하지 않고 세그먼트별 eligible·제외 결과를 계산합니다."""
    try:
        run, _scan = preview_bulk_targeting(
            db,
            payload=payload,
            actor=current_user,
        )
    except BulkTargetingDomainError as exc:
        db.rollback()
        raise _domain_error(exc) from None
    return _to_response(run, db=db)


@bulk_targeting_router.get(
    "/runs",
    response_model=BulkTargetingRunListResponse,
    summary="일괄 타기팅 실행 이력 조회",
)
def list_bulk_targeting_runs_api(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BulkTargetingRunListResponse:
    runs, total = fetch_bulk_targeting_runs(db, page=page, page_size=page_size)
    return BulkTargetingRunListResponse(
        items=[_to_response(run, db=db, include_preview=False) for run in runs],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=(total + page_size - 1) // page_size if total else 0,
    )


@bulk_targeting_router.get(
    "/runs/{run_id}",
    response_model=BulkTargetingRunResponse,
    summary="일괄 타기팅 미리보기·실행 결과 조회",
)
def get_bulk_targeting_run_api(
    run_id: int,
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BulkTargetingRunResponse:
    run = get_bulk_targeting_run(db, run_id)
    if run is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="The bulk targeting run was not found.",
        )
    return _to_response(run, db=db)


@bulk_targeting_router.post(
    "/runs/{run_id}/execute",
    response_model=BulkTargetingRunResponse,
    summary="일괄 타기팅 실행",
)
def execute_bulk_targeting_api(
    run_id: int,
    current_user: User = Depends(require_roles(*BULK_TARGETING_MUTATION_ROLES)),
    db: Session = Depends(get_db),
) -> BulkTargetingRunResponse:
    run = get_bulk_targeting_run(db, run_id)
    if run is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="The bulk targeting run was not found.",
        )
    try:
        run = execute_bulk_targeting(db, run=run, actor=current_user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="A campaign with the same name already exists.",
        ) from None
    except BulkTargetingDomainError as exc:
        db.rollback()
        raise _domain_error(exc) from None
    return _to_response(run, db=db)


@bulk_targeting_router.post(
    "/runs/{run_id}/cancel",
    response_model=BulkTargetingRunResponse,
    summary="일괄 타기팅 취소",
)
def cancel_bulk_targeting_api(
    run_id: int,
    current_user: User = Depends(require_roles(*BULK_TARGETING_MUTATION_ROLES)),
    db: Session = Depends(get_db),
) -> BulkTargetingRunResponse:
    run = get_bulk_targeting_run(db, run_id)
    if run is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="The bulk targeting run was not found.",
        )
    try:
        run = cancel_bulk_targeting(db, run=run, actor=current_user)
    except BulkTargetingDomainError as exc:
        db.rollback()
        raise _domain_error(exc) from None
    return _to_response(run, db=db)


@bulk_targeting_router.post(
    "/runs/{run_id}/rerun",
    response_model=BulkTargetingRunResponse,
    status_code=http_status.HTTP_201_CREATED,
    summary="취소된 일괄 타기팅 재실행 미리보기",
)
def rerun_bulk_targeting_api(
    run_id: int,
    payload: BulkTargetingRerunRequest | None = None,
    current_user: User = Depends(require_roles(*BULK_TARGETING_MUTATION_ROLES)),
    db: Session = Depends(get_db),
) -> BulkTargetingRunResponse:
    run = get_bulk_targeting_run(db, run_id)
    if run is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="The bulk targeting run was not found.",
        )
    payload = payload or BulkTargetingRerunRequest()
    try:
        rerun, _scan = rerun_bulk_targeting(
            db,
            run=run,
            actor=current_user,
            campaign_name=payload.campaign_name,
            max_targets=payload.max_targets,
        )
    except BulkTargetingDomainError as exc:
        db.rollback()
        raise _domain_error(exc) from None
    return _to_response(rerun, db=db)

"""캠페인 성과·A/B 실험 비교 조회 API입니다."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy.orm import Session

from .auth import get_current_user
from ...database import get_db
from ...enums import BulkTargetingSegment
from ...models import Campaign, User
from ...schemas import (
    CampaignPerformanceBreakdown,
    CampaignPerformanceMetrics,
    CampaignPerformanceResponse,
)
from ...services.performance_service import get_campaign_performance


performance_router = APIRouter(prefix="/api/v1", tags=["performance"])


def _to_response(
    result: dict[str, object],
    *,
    campaign_id: int | None,
    segment_code: BulkTargetingSegment | None,
    assigned_to_user_id: int | None,
) -> CampaignPerformanceResponse:
    return CampaignPerformanceResponse(
        campaign_id=campaign_id,
        segment_code=segment_code,
        assigned_to_user_id=assigned_to_user_id,
        summary=CampaignPerformanceMetrics(**result["summary"].__dict__),
        by_campaign=[
            CampaignPerformanceBreakdown(**item)
            for item in result["by_campaign"]
        ],
        by_segment=[
            CampaignPerformanceBreakdown(**item)
            for item in result["by_segment"]
        ],
        by_assignee=[
            CampaignPerformanceBreakdown(**item)
            for item in result["by_assignee"]
        ],
        by_cluster=[
            CampaignPerformanceBreakdown(**item)
            for item in result["by_cluster"]
        ],
        by_risk_level=[
            CampaignPerformanceBreakdown(**item)
            for item in result["by_risk_level"]
        ],
        generated_at=result["generated_at"],
    )


@performance_router.get(
    "/campaign-performance",
    response_model=CampaignPerformanceResponse,
    summary="캠페인 성과 요약·비교 조회",
)
def get_campaign_performance_api(
    campaign_id: int | None = Query(default=None, ge=1),
    segment: BulkTargetingSegment | None = Query(default=None),
    assigned_to_user_id: int | None = Query(default=None, ge=1),
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CampaignPerformanceResponse:
    """인증된 모든 역할이 캠페인 성과를 조회할 수 있습니다."""
    if campaign_id is not None and db.get(Campaign, campaign_id) is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="The campaign was not found.",
        )
    result = get_campaign_performance(
        db,
        campaign_id=campaign_id,
        segment_code=segment.value if segment is not None else None,
        assigned_to_user_id=assigned_to_user_id,
    )
    return _to_response(
        result,
        campaign_id=campaign_id,
        segment_code=segment,
        assigned_to_user_id=assigned_to_user_id,
    )


@performance_router.get(
    "/campaigns/{campaign_id}/performance",
    response_model=CampaignPerformanceResponse,
    summary="특정 캠페인 성과 조회",
)
def get_single_campaign_performance_api(
    campaign_id: int,
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CampaignPerformanceResponse:
    if db.get(Campaign, campaign_id) is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="The campaign was not found.",
        )
    result = get_campaign_performance(db, campaign_id=campaign_id)
    return _to_response(
        result,
        campaign_id=campaign_id,
        segment_code=None,
        assigned_to_user_id=None,
    )

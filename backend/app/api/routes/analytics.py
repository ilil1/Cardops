"""EDA 원천 데이터셋 기반 분석팀용 통계 API입니다."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .auth import get_current_user
from ...database import get_db
from ...enums import RiskLevel
from ...models import User
from ...schemas import (
    CategoricalChurnRateResponse,
    FeatureCorrelationResponse,
    NumericDistributionResponse,
)
from ...services import analytics_service
from ...services.insight_service import InsightFilters


analytics_router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


class ClusterProfileItem(BaseModel):
    cluster_name: str
    count: int
    avg_churn_probability: float
    avg_activity_gap: float
    avg_total_trans_amt: float


class ClusterProfileResponse(BaseModel):
    items: list[ClusterProfileItem]


class RiskClusterCell(BaseModel):
    risk_level: str
    cluster_name: str
    count: int


class RiskClusterCrosstabResponse(BaseModel):
    risk_levels: list[str]
    clusters: list[str]
    cells: list[RiskClusterCell]


class ReasonCodePair(BaseModel):
    code_a: str
    code_b: str
    count: int


class ReasonCodeCooccurrenceResponse(BaseModel):
    codes: list[str]
    single_counts: dict[str, int]
    pairs: list[ReasonCodePair]


def _build_filters(
    risk_level: str | None,
    cluster_name: str | None,
    customer_id: int | None,
) -> InsightFilters:
    """쿼리 파라미터를 고객 분석 목록과 동일한 InsightFilters로 변환합니다."""
    if risk_level is not None:
        try:
            parsed_risk_level = RiskLevel(risk_level)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported risk_level: {risk_level}",
            ) from error
    else:
        parsed_risk_level = None
    return InsightFilters(
        risk_level=parsed_risk_level,
        cluster_name=cluster_name,
        customer_id=customer_id,
    )


@analytics_router.get(
    "/categorical-churn-rate",
    response_model=CategoricalChurnRateResponse,
    summary="범주형 변수별 평균 예측 이탈 확률 조회",
)
def get_categorical_churn_rate(
    field: str = Query(
        ...,
        description="Gender, Card_Category, Income_Category, Education_Level, Marital_Status 중 하나",
    ),
    risk_level: str | None = Query(None, description="low, medium, high 중 하나"),
    cluster_name: str | None = Query(None),
    customer_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> CategoricalChurnRateResponse:
    """인증된 모든 역할이 범주형 변수별 평균 예측 이탈 확률을 조회할 수 있습니다.

    대시보드 상단 필터(위험도·군집·고객 ID)와 동일한 조건으로 필터링됩니다.
    """
    if field not in analytics_service.CATEGORICAL_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported categorical field: {field}",
        )
    filters = _build_filters(risk_level, cluster_name, customer_id)
    return CategoricalChurnRateResponse(
        field=field,
        items=analytics_service.categorical_churn_rate(db, field, filters),
    )


@analytics_router.get(
    "/numeric-distribution",
    response_model=NumericDistributionResponse,
    summary="위험도별 수치형 변수 분포 조회",
)
def get_numeric_distribution(
    field: str = Query(
        ...,
        description=(
            "Total_Trans_Ct, Total_Trans_Amt, Avg_Utilization_Ratio, "
            "Months_Inactive_12_mon, Contacts_Count_12_mon, "
            "Total_Relationship_Count 중 하나"
        ),
    ),
    risk_level: str | None = Query(None, description="low, medium, high 중 하나"),
    cluster_name: str | None = Query(None),
    customer_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> NumericDistributionResponse:
    """인증된 모든 역할이 위험도별 수치형 변수 분포(사분위 요약)를 조회할 수 있습니다.

    대시보드 상단 필터(위험도·군집·고객 ID)와 동일한 조건으로 필터링됩니다.
    """
    if field not in analytics_service.NUMERIC_DISTRIBUTION_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported numeric field: {field}",
        )
    filters = _build_filters(risk_level, cluster_name, customer_id)
    return NumericDistributionResponse(
        field=field,
        by_target=analytics_service.numeric_distribution(db, field, filters),
    )


@analytics_router.get(
    "/feature-correlation",
    response_model=FeatureCorrelationResponse,
    summary="변수-예측 이탈 확률 상관관계 조회",
)
def get_feature_correlation(
    risk_level: str | None = Query(None, description="low, medium, high 중 하나"),
    cluster_name: str | None = Query(None),
    customer_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> FeatureCorrelationResponse:
    """인증된 모든 역할이 수치형 변수와 예측 이탈 확률 간 상관계수를 조회할 수 있습니다.

    대시보드 상단 필터(위험도·군집·고객 ID)와 동일한 조건으로 필터링됩니다.
    """
    filters = _build_filters(risk_level, cluster_name, customer_id)
    return FeatureCorrelationResponse(
        items=analytics_service.feature_correlation(db, filters),
    )


@analytics_router.get(
    "/cluster-profile",
    response_model=ClusterProfileResponse,
    summary="군집별 평균 이탈확률·activity_gap·거래금액 프로필 조회",
)
def get_cluster_profile(
    risk_level: str | None = Query(None, description="low, medium, high 중 하나"),
    cluster_name: str | None = Query(None),
    customer_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> ClusterProfileResponse:
    """군집별 인원수와 평균 특성(이탈확률·activity_gap·거래금액)을 조회합니다."""
    filters = _build_filters(risk_level, cluster_name, customer_id)
    return ClusterProfileResponse(items=analytics_service.cluster_profile(db, filters))


@analytics_router.get(
    "/risk-cluster-crosstab",
    response_model=RiskClusterCrosstabResponse,
    summary="위험도 × 군집 교차 인원수 조회",
)
def get_risk_cluster_crosstab(
    risk_level: str | None = Query(None, description="low, medium, high 중 하나"),
    cluster_name: str | None = Query(None),
    customer_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> RiskClusterCrosstabResponse:
    """위험도(risk_level)와 군집(cluster_name)의 교차 인원수를 조회합니다."""
    filters = _build_filters(risk_level, cluster_name, customer_id)
    result = analytics_service.risk_cluster_crosstab(db, filters)
    return RiskClusterCrosstabResponse(**result)


@analytics_router.get(
    "/reason-code-cooccurrence",
    response_model=ReasonCodeCooccurrenceResponse,
    summary="위험 사유코드 동시발생 분석",
)
def get_reason_code_cooccurrence(
    risk_level: str | None = Query(None, description="low, medium, high 중 하나"),
    cluster_name: str | None = Query(None),
    customer_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> ReasonCodeCooccurrenceResponse:
    """가장 흔한 위험 사유코드 상위 6개끼리 동시에 나타나는 빈도를 조회합니다.

    세그먼트로 나누지 않고 필터링된 전체 고객을 대상으로 계산하므로
    동어반복 문제가 없습니다.
    """
    filters = _build_filters(risk_level, cluster_name, customer_id)
    result = analytics_service.reason_code_cooccurrence(db, filters)
    return ReasonCodeCooccurrenceResponse(**result)
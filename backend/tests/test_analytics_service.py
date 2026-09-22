"""EDA 원천 데이터셋 기반 분석 통계 계산을 검증합니다."""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend.app.services import analytics_service
from backend.app.services.insight_service import InsightFilters, _filtered_query

DATABASE_URL = os.environ.get("DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL이 설정된 실제 DB(예: docker compose의 mysql)가 있어야 실행됩니다.",
)


@pytest.fixture()
def db() -> Generator[Session, None, None]:
    engine = create_engine(DATABASE_URL)
    with Session(engine) as session:
        yield session


def test_categorical_churn_rate_sums_to_full_population(db: Session) -> None:
    """성별 그룹의 표본 수 합이 전체 최신 분석 결과 수와 일치하는지 확인합니다."""
    total = db.scalar(select(func.count()).select_from(_filtered_query(db, InsightFilters()).subquery())) or 0
    items = analytics_service.categorical_churn_rate(db, "Gender", InsightFilters())

    assert {item["group"] for item in items} == {"M", "F"}
    for item in items:
        assert 0.0 <= item["churn_rate"] <= 1.0
        assert item["count"] > 0
    assert sum(item["count"] for item in items) == total


def test_categorical_churn_rate_rejects_unknown_field(db: Session) -> None:
    """지원하지 않는 필드는 명확히 거부합니다."""
    with pytest.raises(ValueError):
        analytics_service.categorical_churn_rate(db, "Not_A_Real_Column", InsightFilters())


def test_numeric_distribution_quartiles_are_ordered(db: Session) -> None:
    """위험도(low/medium/high) 각각 min<=q1<=median<=q3<=max 순서를 지키는지 확인합니다."""
    result = analytics_service.numeric_distribution(db, "Total_Trans_Ct", InsightFilters())

    assert set(result.keys()) == {"low", "medium", "high"}
    for bucket in result.values():
        assert bucket["min"] <= bucket["q1"] <= bucket["median"]
        assert bucket["median"] <= bucket["q3"] <= bucket["max"]
        assert bucket["count"] > 0


def test_feature_correlation_matches_known_eda_ranking(db: Session) -> None:
    """노트북 EDA에서 확인된 상관관계 상위 변수·부호가 그대로 재현되는지 확인합니다."""
    items = analytics_service.feature_correlation(db, InsightFilters())

    by_feature = {item["feature"]: item["correlation"] for item in items}
    assert by_feature["Total_Trans_Ct"] < 0
    assert by_feature["Contacts_Count_12_mon"] > 0
    assert items[0]["feature"] == "Total_Trans_Ct"

    magnitudes = [abs(item["correlation"]) for item in items]
    assert magnitudes == sorted(magnitudes, reverse=True)

"""분석팀용 EDA 통계를 계산합니다.

과거에는 원천 학습 CSV(bankchurners_clean.csv)를 그대로 읽어 계산했지만, 그 CSV에는
CLIENTNUM(고객 ID)이 정제 단계에서 제거되어 있어 대시보드의 위험도/군집/고객 ID 필터와
연결할 방법이 없었습니다. 이제는 customers 테이블과 고객별 "최신" customer_insights
스냅샷(insights_service._filtered_query와 동일한 규칙)을 조인해 계산하므로, 대시보드
필터가 그대로 적용됩니다.

한 가지 의미 차이에 주의하세요: 원본 CSV의 "이탈률"은 과거 실제 이탈 여부(Target, 0/1
정답값) 기준이었지만, customers/customer_insights에는 정답값이 없고 모델이 예측한
churn_probability만 있습니다. 그래서 이 모듈의 결과는 "실제 과거 이탈률"이 아니라
"모델이 예측한 평균 이탈 확률"입니다. 필드 이름(churn_rate)은 프런트엔드와의 하위
호환을 위해 그대로 유지합니다.
"""

from __future__ import annotations

import json

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Customer
from .insight_service import InsightFilters, _filtered_query


CATEGORICAL_FIELDS = (
    "Gender",
    "Card_Category",
    "Income_Category",
    "Education_Level",
    "Marital_Status",
)
NUMERIC_DISTRIBUTION_FIELDS = (
    "Total_Trans_Ct",
    "Total_Trans_Amt",
    "Avg_Utilization_Ratio",
    "Months_Inactive_12_mon",
    "Contacts_Count_12_mon",
    "Total_Relationship_Count",
)

_CATEGORICAL_COLUMNS = {
    "Gender": Customer.gender,
    "Card_Category": Customer.card_category,
    "Income_Category": Customer.income_category,
    "Education_Level": Customer.education_level,
    "Marital_Status": Customer.marital_status,
}

_NUMERIC_COLUMNS = {
    "Total_Trans_Ct": Customer.total_trans_ct,
    "Total_Trans_Amt": Customer.total_trans_amt,
    "Avg_Utilization_Ratio": Customer.avg_utilization_ratio,
    "Months_Inactive_12_mon": Customer.months_inactive_12_mon,
    "Contacts_Count_12_mon": Customer.contacts_count_12_mon,
    "Total_Relationship_Count": Customer.total_relationship_count,
}


def categorical_churn_rate(
    db: Session,
    field: str,
    filters: InsightFilters,
) -> list[dict[str, object]]:
    """범주형 변수 그룹별 평균 예측 이탈 확률과 표본 수를 내림차순으로 반환합니다."""
    if field not in CATEGORICAL_FIELDS:
        raise ValueError(f"Unsupported categorical field: {field}")
    column = _CATEGORICAL_COLUMNS[field]
    base = _filtered_query(db, filters).subquery()
    avg_probability = func.avg(base.c.churn_probability)
    rows = db.execute(
        select(
            column.label("group"),
            avg_probability.label("churn_rate"),
            func.count().label("count"),
        )
        .select_from(base)
        .join(Customer, Customer.customer_id == base.c.customer_id)
        .group_by(column)
        .order_by(avg_probability.desc())
    ).all()
    return [
        {
            "group": str(row.group),
            "churn_rate": float(row.churn_rate or 0.0),
            "count": int(row.count),
        }
        for row in rows
    ]


def numeric_distribution(
    db: Session,
    field: str,
    filters: InsightFilters,
) -> dict[str, dict[str, float]]:
    """위험도(risk_level)별 수치형 변수의 사분위 요약을 반환합니다.

    원본 CSV 버전은 실제 이탈 여부(0/1)로 그룹을 나눴지만, 대신 쓸 수 있는 정답값이
    없어 대시보드의 다른 패널과 동일한 축인 위험도(low/medium/high)로 그룹을 나눕니다.
    """
    if field not in NUMERIC_DISTRIBUTION_FIELDS:
        raise ValueError(f"Unsupported numeric field: {field}")
    column = _NUMERIC_COLUMNS[field]
    base = _filtered_query(db, filters).subquery()
    rows = db.execute(
        select(base.c.risk_level, column)
        .select_from(base)
        .join(Customer, Customer.customer_id == base.c.customer_id)
    ).all()

    buckets: dict[str, list[float]] = {}
    for risk_level, value in rows:
        if value is None:
            continue
        buckets.setdefault(str(risk_level), []).append(float(value))

    result: dict[str, dict[str, float]] = {}
    for risk_level, values in buckets.items():
        array = np.asarray(values, dtype=float)
        result[risk_level] = {
            "min": float(np.min(array)),
            "q1": float(np.percentile(array, 25)),
            "median": float(np.percentile(array, 50)),
            "q3": float(np.percentile(array, 75)),
            "max": float(np.max(array)),
            "count": int(array.size),
        }
    return result


def feature_correlation(
    db: Session,
    filters: InsightFilters,
) -> list[dict[str, object]]:
    """수치형 변수와 예측 이탈 확률(churn_probability)의 상관계수를 절댓값 내림차순으로 반환합니다."""
    base = _filtered_query(db, filters).subquery()
    feature_items = list(_NUMERIC_COLUMNS.items())
    rows = db.execute(
        select(
            base.c.churn_probability,
            *[column for _, column in feature_items],
        )
        .select_from(base)
        .join(Customer, Customer.customer_id == base.c.customer_id)
    ).all()

    if not rows:
        return []

    data = np.asarray(rows, dtype=float)
    churn = data[:, 0]
    results: list[dict[str, object]] = []
    for index, (name, _) in enumerate(feature_items, start=1):
        feature_values = data[:, index]
        if np.std(feature_values) == 0 or np.std(churn) == 0:
            continue
        correlation = float(np.corrcoef(churn, feature_values)[0, 1])
        if np.isfinite(correlation):
            results.append({"feature": name, "correlation": correlation})
    results.sort(key=lambda item: abs(item["correlation"]), reverse=True)
    return results


def _decode_reason_codes(raw: object) -> list[str]:
    """reason_codes 컬럼 값(문자열로 직렬화된 JSON 리스트 등)을 코드 문자열 리스트로 변환합니다."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw]
    if isinstance(raw, dict):
        # 혹시 과거 데이터가 {code: 설명} 형태로 남아있을 경우를 대비한 안전장치입니다.
        return [str(key) for key in raw.keys()]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return []
        return _decode_reason_codes(parsed)
    return []


# transaction_decline은 배치 스코어링 로직(analysis_batch.py)에서 정확히
# "Total_Ct_Chng_Q4_Q1 <= 중앙값" 조건으로 붙습니다. 이 값은 거래 건수/금액
# 변화와 사실상 같은 신호라서, 다른 집계와 함께 두면 동어반복이 될 수 있어
# 사유코드 동시발생 분석에서도 제외합니다.
_TAUTOLOGICAL_REASON_CODES = {"transaction_decline"}


def cluster_profile(
    db: Session,
    filters: InsightFilters,
) -> list[dict[str, object]]:
    """군집별 인원수와 평균 이탈확률·activity_gap·거래금액을 반환합니다."""
    base = _filtered_query(db, filters).subquery()
    rows = db.execute(
        select(
            base.c.cluster_name,
            func.count().label("count"),
            func.avg(base.c.churn_probability).label("avg_churn_probability"),
            func.avg(base.c.activity_gap).label("avg_activity_gap"),
            func.avg(Customer.total_trans_amt).label("avg_total_trans_amt"),
        )
        .select_from(base)
        .join(Customer, Customer.customer_id == base.c.customer_id)
        .group_by(base.c.cluster_name)
        .order_by(func.count().desc())
    ).all()
    return [
        {
            "cluster_name": str(row.cluster_name),
            "count": int(row.count),
            "avg_churn_probability": float(row.avg_churn_probability or 0.0),
            "avg_activity_gap": float(row.avg_activity_gap or 0.0),
            "avg_total_trans_amt": float(row.avg_total_trans_amt or 0.0),
        }
        for row in rows
    ]


def risk_cluster_crosstab(
    db: Session,
    filters: InsightFilters,
) -> dict[str, object]:
    """위험도(risk_level) × 군집(cluster_name) 교차 인원수를 반환합니다."""
    base = _filtered_query(db, filters).subquery()
    rows = db.execute(
        select(
            base.c.risk_level,
            base.c.cluster_name,
            func.count().label("count"),
        )
        .select_from(base)
        .group_by(base.c.risk_level, base.c.cluster_name)
    ).all()

    risk_order = ["high", "medium", "low"]
    risk_levels = [level for level in risk_order if any(str(row.risk_level) == level for row in rows)]
    clusters = sorted({str(row.cluster_name) for row in rows})
    counts = {(str(row.risk_level), str(row.cluster_name)): int(row.count) for row in rows}

    cells = [
        {
            "risk_level": risk_level,
            "cluster_name": cluster_name,
            "count": counts.get((risk_level, cluster_name), 0),
        }
        for risk_level in risk_levels
        for cluster_name in clusters
    ]
    return {"risk_levels": risk_levels, "clusters": clusters, "cells": cells}


def reason_code_cooccurrence(
    db: Session,
    filters: InsightFilters,
    *,
    top_n: int = 6,
) -> dict[str, object]:
    """가장 흔한 위험 사유코드 상위 N개끼리 몇 명에게 동시에 붙는지 반환합니다.

    세그먼트로 나누지 않고 필터링된 전체 고객을 대상으로 하므로,
    세그먼트 비교와 달리 동어반복 문제가 없습니다.
    """
    base = _filtered_query(db, filters).subquery()
    rows = db.scalars(
        select(base.c.reason_codes).select_from(base)
    ).all()

    code_lists = [
        [code for code in _decode_reason_codes(raw) if code not in _TAUTOLOGICAL_REASON_CODES]
        for raw in rows
    ]

    single_counts: dict[str, int] = {}
    for codes in code_lists:
        for code in codes:
            single_counts[code] = single_counts.get(code, 0) + 1

    top_codes = sorted(single_counts, key=lambda code: single_counts[code], reverse=True)[:top_n]
    top_code_set = set(top_codes)

    pair_counts: dict[tuple[str, str], int] = {}
    for codes in code_lists:
        present = sorted(set(codes) & top_code_set)
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                key = (present[i], present[j])
                pair_counts[key] = pair_counts.get(key, 0) + 1

    pairs = [
        {"code_a": code_a, "code_b": code_b, "count": count}
        for (code_a, code_b), count in sorted(
            pair_counts.items(), key=lambda item: item[1], reverse=True
        )
    ]
    return {
        "codes": top_codes,
        "single_counts": single_counts,
        "pairs": pairs[:10],
    }
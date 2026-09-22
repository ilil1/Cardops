"""군집용 피처셋 정의 — 서로 다른 질문에 답하는 4종을 유지한다.

- behavioral_core(기본값): 5개 행동 변수. notebooks/05_clustering.ipynb → 기존
  src/clustering.py 운영값. k=3, 참고 Silhouette ≈ 0.218.
- behavioral_extended: 8개 행동 변수. notebooks/credit_card_retention_ml.ipynb §5.
  k=4, 참고 Silhouette = 0.1946. behavioral_core와 겹치는 피처가 4개뿐이라
  상위집합 관계가 아니다 — 둘 다 유지한다(docs/src_architecture.md 결정 A).
- credit_capacity: 4개 신용여력 변수. notebooks/credit_card_retention_ml.ipynb §5-2.
  k=2, 참고 Silhouette = 0.4687.
- activity_gap: 회귀(gap) 모델의 예측 결과에 의존한다. 원본 CSV만으로는 계산할 수
  없다(docs/src_architecture.md 결정 B) — regression_final.py가 저장하는
  Actual/Predicted/Residual 예측표를 받아서 만든다.

각 피처셋의 정확한 컬럼·k·출처는 docs/src_architecture.md 2절 카탈로그 참고.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from sklearn.preprocessing import StandardScaler

from common.data import load_raw_data

BEHAVIORAL_CORE_FEATURES = [
    "Total_Trans_Ct",
    "Avg_Utilization_Ratio",
    "Total_Revolving_Bal",
    "Contacts_Count_12_mon",
    "Total_Relationship_Count",
]

BEHAVIORAL_EXTENDED_FEATURES = [
    "Total_Trans_Amt",
    "Total_Trans_Ct",
    "Total_Revolving_Bal",
    "Avg_Utilization_Ratio",
    "Months_Inactive_12_mon",
    "Contacts_Count_12_mon",
    "Total_Ct_Chng_Q4_Q1",
    "Total_Amt_Chng_Q4_Q1",
]

CREDIT_CAPACITY_FEATURES = [
    "Credit_Limit",
    "Avg_Open_To_Buy",
    "Avg_Utilization_Ratio",
    "Total_Revolving_Bal",
]


def get_behavioral_core_features(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """행동 변수 5개(기본값)를 반환한다."""
    if df is None:
        df = load_raw_data()
    return df[BEHAVIORAL_CORE_FEATURES]


def get_behavioral_extended_features(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """행동 변수 8개(대안)를 반환한다."""
    if df is None:
        df = load_raw_data()
    return df[BEHAVIORAL_EXTENDED_FEATURES]


def get_credit_capacity_features(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """신용여력 변수 4개를 반환한다."""
    if df is None:
        df = load_raw_data()
    return df[CREDIT_CAPACITY_FEATURES]


def get_activity_gap_features(predictions: pd.DataFrame) -> pd.DataFrame:
    """회귀(gap) 모델의 Test 예측 결과에서 활동성 갭 군집용 피처를 만든다.

    predictions는 common.evaluate.make_regression_predictions()가 만드는
    Actual/Predicted/Residual 스키마를 그대로 받는다 — regression_final.py가
    저장하는 outputs/reports/regression_gap_predictions.csv와 같은 형태다.
    원본 CSV만으로는 이 피처셋을 만들 수 없다는 걸 시그니처로 강제한다.
    """
    return pd.DataFrame(
        {
            "예상_대비_거래_차이": predictions["Residual"].to_numpy(),
            "실제_거래건수": predictions["Actual"].to_numpy(),
        }
    )


def build_preprocessor() -> StandardScaler:
    """군집 피처는 전부 수치형이라 표준화만 하면 된다 (범주형 인코딩 불필요)."""
    return StandardScaler()

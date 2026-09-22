"""회귀 태스크의 "무엇을 넣고 뺄지"만 정의한다. 학습 로직은 여기 없다.

전처리(수치형 표준화 + 범주형 원-핫)는 이 파일에서 새로 만들지 않고
`common/data.py`의 `build_standard_preprocessor`를 `build_preprocessor`라는
이름으로 그대로 재노출해서 쓴다 — "어떤 피처를 남길지"는 태스크마다 다르지만
"남은 피처를 어떻게 숫자로 바꿀지"는 모든 태스크가 공유하는 기계적 로직이기 때문이다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dataclasses import dataclass, field
from typing import Sequence

import pandas as pd

from common.data import build_standard_preprocessor as build_preprocessor  # noqa: F401  (재노출)

TARGET_COL = "Total_Trans_Ct"  # 회귀 타겟: 최근 12개월 총 거래건수

# 회귀에서 정보 누수를 막기 위해 항상 제외하는 컬럼
# (Total_Ct_Chng_Q4_Q1은 거래건수 변화율이라 타겟과 사실상 같은 정보를 담는다.
#  Target은 이탈 여부 라벨 그 자체다 — 원본 노트북 make_features()도
#  drop = ["Total_Trans_Ct", "Target", "Total_Ct_Chng_Q4_Q1"]로 반드시 제외한다.
#  이걸 빠뜨리면 회귀 모델이 "정답(이탈 여부)"을 미리 보고 거래건수를 맞히게 되어,
#  활동성 갭에 이탈 신호가 거의 안 남는 심각한 데이터 누수가 된다.)
ALWAYS_DROP_COLS: list[str] = ["Total_Ct_Chng_Q4_Q1", "Target"]


@dataclass(frozen=True)
class RegressionTaskSpec:
    """회귀 태스크 1개를 정의하는 스펙. `to_X_y()` 하나만 호출하면 된다."""

    name: str
    description: str
    target_col: str = TARGET_COL
    drop_amount: bool = False           # True면 Total_Trans_Amt 제거 (갭 기반 조기경보용 — 항상 True로 씀)
    add_derived_features: bool = True   # 파생변수(비율/구간) 4종 추가 여부
    extra_drop_cols: Sequence[str] = field(default_factory=tuple)

    @property
    def drop_cols(self) -> list[str]:
        drop = list(ALWAYS_DROP_COLS) + list(self.extra_drop_cols)
        if self.drop_amount:
            drop.append("Total_Trans_Amt")
        return drop

    def add_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """파생변수 추가 (원본 df는 변경하지 않고 복사본을 반환).

        - 리볼빙_한도_비율  = Total_Revolving_Bal / Credit_Limit
        - 상품당_관계밀도    = Total_Relationship_Count / Months_on_book
        - 문의_대비_보유기간 = Contacts_Count_12_mon / Months_on_book
        - 연령대 (5구간 범주화 — pd.cut 결과는 category dtype이라
          `get_categorical_columns`가 자동으로 범주형으로 잡아낸다)
        """
        d = df.copy()
        if self.add_derived_features:
            d["리볼빙_한도_비율"] = d["Total_Revolving_Bal"] / d["Credit_Limit"]
            d["상품당_관계밀도"] = d["Total_Relationship_Count"] / d["Months_on_book"]
            d["문의_대비_보유기간"] = d["Contacts_Count_12_mon"] / d["Months_on_book"]
            d["연령대"] = pd.cut(
                d["Customer_Age"],
                bins=[0, 30, 40, 50, 60, 100],
                labels=["20대이하", "30대", "40대", "50대", "60대이상"],
            )
        return d

    def to_X_y(self, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
        """파생변수 추가 + 타겟 분리 + 컬럼 제거까지 한 번에 처리한다.

        원-핫 인코딩은 여기서 하지 않는다 — `build_preprocessor(X)`로 만든
        ColumnTransformer를 Pipeline에 넣어 Train에만 fit, Val/Test는 transform만
        하는 방식으로 처리한다 (get_dummies를 분할 전에 적용하면 Val/Test 정보가
        전처리 통계에 섞여 들어갈 위험이 있다).
        """
        d = self.add_features(df)
        y = d[self.target_col]
        drop = list(dict.fromkeys([self.target_col, *self.drop_cols]))
        X = d.drop(columns=[c for c in drop if c in d.columns])
        return X, y


# ── 사전 정의된 태스크 ────────────────────────────────────────────────────
# 거래금액을 포함하면 Test R²는 높아지지만 활동성 갭의 이탈 판별력(AUC)이 떨어진다. 그래서 A(금액 포함)
# 비교는 py 파이프라인에 두지 않고, 처음부터 금액 제외 구성 하나만 쓴다.

# RAW_TASK: 베이스라인용. 파생변수 없음, 금액 제외 (거래금액은 애초에 쓰지 않는다).
RAW_TASK = RegressionTaskSpec(
    name="raw_baseline",
    description="원본 피처만(파생변수 없음, 금액 제외) — 베이스라인 비교용.",
    drop_amount=True,
    add_derived_features=False,
)

# CT_GAP_TASK: 거래금액 제외 + 파생변수 추가. 활동성 갭(이탈 조기경보)에 쓰는 유일한 회귀 구성.
CT_GAP_TASK = RegressionTaskSpec(
    name="금액제외_갭기반",
    description="Total_Trans_Amt 제외 + 파생변수 추가. 이탈 조기경보(활동성 갭)용 회귀 모델.",
    drop_amount=True,
    add_derived_features=True,
)

REGRESSION_TASKS: dict[str, RegressionTaskSpec] = {task.name: task for task in (RAW_TASK, CT_GAP_TASK)}

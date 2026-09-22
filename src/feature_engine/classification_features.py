"""분류 태스크의 "무엇을 넣고 뺄지"만 정의한다. 학습 로직은 여기 없다.

`03_classification_수빈.ipynb`의 피처엔지니어링 실험(83~87번 섹션)을 스펙(dataclass)
기반으로 재구성했다.

전처리(수치형 표준화 + 범주형 원-핫)는 이 파일에서 새로 만들지 않고 `common/data.py`의
`build_standard_preprocessor`를 `build_preprocessor`라는 이름으로 그대로 재노출해서
쓴다 — `regression_features.py`와 동일한 이유다. 원래 노트북은 `get_dummies`를
train/val/test 분할 *전에* 전체 데이터에 적용했는데, `Pipeline(build_preprocessor(X) +
모델)`로 감싸 Train에만 fit하는 방식으로 바꾸면 분할 후 카테고리 불일치나 정보 누수
걱정 없이 회귀 모듈과 동일하게 안전해진다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dataclasses import dataclass, field
from typing import Sequence

import pandas as pd

from common.data import build_standard_preprocessor as build_preprocessor  # noqa: F401  (재노출)

TARGET_COL = "Target"  # 분류 타겟: 이탈 여부 (0=유지, 1=이탈)


@dataclass(frozen=True)
class ClassificationTaskSpec:
    """분류 태스크 1개를 정의하는 스펙. `to_X_y()` 하나만 호출하면 된다."""

    name: str
    description: str
    target_col: str = TARGET_COL
    add_derived_features: bool = False  # 파생변수(비율) 3종 추가 여부
    extra_drop_cols: Sequence[str] = field(default_factory=tuple)

    @property
    def drop_cols(self) -> list[str]:
        return list(self.extra_drop_cols)

    def add_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """파생변수 추가 (원본 df는 변경하지 않고 복사본을 반환).
        - 거래건당_평균금액  = Total_Trans_Amt / Total_Trans_Ct
        - 문의_대비_거래활동 = Contacts_Count_12_mon / (Total_Trans_Ct + 1)
        - 비활성_비율       = Months_Inactive_12_mon / Months_on_book
        """
        d = df.copy()
        if self.add_derived_features:
            d["거래건당_평균금액"] = d["Total_Trans_Amt"] / d["Total_Trans_Ct"]
            d["문의_대비_거래활동"] = d["Contacts_Count_12_mon"] / (d["Total_Trans_Ct"] + 1)
            d["비활성_비율"] = d["Months_Inactive_12_mon"] / d["Months_on_book"]
        return d

    def to_X_y(self, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
        """파생변수 추가 + 타겟 분리까지 한 번에 처리한다.

        원-핫 인코딩은 여기서 하지 않는다 — `build_preprocessor(X)`로 만든
        ColumnTransformer를 Pipeline에 넣어 Train에만 fit, Val/Test는 transform만
        하는 방식으로 처리한다 (get_dummies를 분할 전에 적용하면 서로 다른 카테고리가
        나뉘거나 Val/Test 정보가 전처리 통계에 섞여 들어갈 위험이 있다).
        """
        d = self.add_features(df)
        y = d[self.target_col]
        drop = list(dict.fromkeys([self.target_col, *self.drop_cols]))
        X = d.drop(columns=[c for c in drop if c in d.columns])
        return X, y


# ── 사전 정의된 태스크 ────────────────────────────────────────────────────
# RAW_TASK: 원본 피처만 (파생변수 없음). 노트북 결론대로 최종모델이 채택하는 유일한 버전
# ("최종 제출 모델은 기존 튜닝 LightGBM(원본 피처 기반, final_model)을 그대로 유지" — 87번 섹션).
RAW_TASK = ClassificationTaskSpec(
    name="raw_baseline",
    description="원본 피처만(파생변수 없음) — 베이스라인 비교 및 최종모델 채택 버전.",
    add_derived_features=False,
)

# FE_TASK: 파생변수 3종 추가. Validation 기준 소폭 개선을 확인했지만, 노트북 결론대로
# 최종모델은 채택하지 않고 비교용으로만 쓴다.
FE_TASK = ClassificationTaskSpec(
    name="파생변수_추가",
    description="거래건당_평균금액/문의_대비_거래활동/비활성_비율 3종 추가 — 피처엔지니어링 비교용(최종모델 미채택).",
    add_derived_features=True,
)

CHURN_TASK = RAW_TASK  # final/classification_final.py가 쓰는 태스크 (파생변수 미채택)

CLASSIFICATION_TASKS: dict[str, ClassificationTaskSpec] = {task.name: task for task in (RAW_TASK, FE_TASK)}
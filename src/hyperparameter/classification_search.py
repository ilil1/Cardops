"""분류 탐색·비교 3종: 베이스라인, 피처 엔지니어링, 하이퍼파라미터. (★상세 구현 대상)

`
이 모듈은 **탐색·비교만 하고 최종 모델을 저장하지 않는다** 

실행: python src/hyperparameter/classification_search.py
(classification_baseline_report.csv, classification_feature_engineering_report.csv,
 classification_hyperparameter_search.csv 3개를 outputs/reports/에 저장한다)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GridSearchCV, train_test_split
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from xgboost import XGBClassifier

from common.config import RANDOM_STATE, REPORT_DIR
from common.data import load_raw_data
from common.evaluate import evaluate_classification
from feature_engine.classification_features import (
    CHURN_TASK,
    ClassificationTaskSpec,
    FE_TASK,
    RAW_TASK,
    build_preprocessor,
)

# 이 모듈을 한 번 실행해 찾아둔 기본값 — final/classification_final.py가 이 값을 그대로
# 상수로 가져다 쓴다(재탐색하지 않음). 다시 탐색하려면
# `python src/hyperparameter/classification_search.py`를 실행해
# classification_hyperparameter_search.csv를 보고 이 값을 갱신하면 된다.
PARAM_GRID: dict[str, list] = {
    "model__n_estimators": [200, 300, 500],
    "model__max_depth": [5, 7, 10, -1],
    "model__learning_rate": [0.01, 0.05, 0.1],
    "model__num_leaves": [31, 50, 70],
}

BEST_PARAMS: dict = dict(learning_rate=0.1, max_depth=-1, n_estimators=500, num_leaves=31)


def get_best_params() -> dict:
    """자리표시자 : 이미 탐색된 최적값을 반환한다."""
    return dict(BEST_PARAMS)


# ---------------------------------------------------------------------------
# 탐색 대상 데이터 분할 (베이스라인/피처엔지니어링/하이퍼파라미터 3종이 공유)
# ---------------------------------------------------------------------------
def _split(task: ClassificationTaskSpec, df: pd.DataFrame):
    """태스크의 raw X/y를 60/20/20(Train/Val/Test)으로, stratify 유지하며 나눈다.
    """
    X, y = task.to_X_y(df)
    Xtr, Xtemp, ytr, ytemp = train_test_split(X, y, test_size=0.4, random_state=RANDOM_STATE, stratify=y)
    Xva, Xte, yva, yte = train_test_split(Xtemp, ytemp, test_size=0.5, random_state=RANDOM_STATE, stratify=ytemp)
    return Xtr, Xva, Xte, ytr, yva, yte


# ---------------------------------------------------------------------------
# 1. 베이스라인 — 원본 피처로 5개 모델 기본 성능 비교
# ---------------------------------------------------------------------------
def baseline_report(df: pd.DataFrame) -> pd.DataFrame:
    """5개 모델 기본 성능(미세튜닝 없음).
    LogisticRegression/MLP는 스케일링이 필요하고 RF/XGB/LightGBM은 필요 없지만,
    `build_preprocessor`가 모든 모델에 동일한 표준화+원-핫 파이프라인을 적용한다
    (트리 모델은 단조변환에 불변이라 성능에 영향이 없고, 대신 코드가 모델마다 갈리지 않는다).
    """
    Xtr, Xva, Xte, ytr, yva, yte = _split(RAW_TASK, df)

    neg, pos = (ytr == 0).sum(), (ytr == 1).sum()
    candidates = {
        "LogisticRegression": LogisticRegression(class_weight="balanced", max_iter=1000, random_state=RANDOM_STATE),
        "RandomForest": RandomForestClassifier(
            n_estimators=200, class_weight="balanced", random_state=RANDOM_STATE
        ),
        "XGBoost": XGBClassifier(
            n_estimators=200, eval_metric="logloss", scale_pos_weight=neg / pos, random_state=RANDOM_STATE
        ),
        "LightGBM": LGBMClassifier(
            n_estimators=200, class_weight="balanced", random_state=RANDOM_STATE, verbose=-1
        ),
        "MLP": MLPClassifier(hidden_layer_sizes=(64, 32), max_iter=500, random_state=RANDOM_STATE),
    }
    rows = []
    for name, estimator in candidates.items():
        pipe = Pipeline([("prep", build_preprocessor(Xtr)), ("model", estimator)]).fit(Xtr, ytr)
        rows.append(evaluate_classification(name, "Validation", pipe, Xva, yva))
        rows.append(evaluate_classification(name, "Test", pipe, Xte, yte))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 2. 피처 엔지니어링 — 원본 피처 vs 파생변수 3종 추가 (LightGBM, 튜닝된 파라미터)
# ---------------------------------------------------------------------------
def feature_engineering_report(df: pd.DataFrame) -> pd.DataFrame:
    """03번 노트북 83~87번 섹션과 동일: 파생변수 추가 전후 LightGBM(튜닝됨) 성능 비교.

    노트북 결론대로 개선폭은 크지 않고(Validation 기준 소폭 상승), 최종모델은
    원본 피처 버전(RAW_TASK)을 그대로 채택한다 — 이 리포트는 비교 기록용이다.
    """
    labels = {RAW_TASK.name: "원본_피처만", FE_TASK.name: "파생변수_추가"}
    rows = []
    for task in (RAW_TASK, FE_TASK):
        Xtr, Xva, Xte, ytr, yva, yte = _split(task, df)
        pipe = Pipeline(
            [
                ("prep", build_preprocessor(Xtr)),
                ("model", LGBMClassifier(**BEST_PARAMS, class_weight="balanced", random_state=RANDOM_STATE, verbose=-1)),
            ]
        ).fit(Xtr, ytr)
        label = labels[task.name]
        rows.append(evaluate_classification(label, "Validation", pipe, Xva, yva))
        rows.append(evaluate_classification(label, "Test", pipe, Xte, yte))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 3. 하이퍼파라미터 최적화 — GridSearchCV (LightGBM, F1 기준)
# ---------------------------------------------------------------------------
def hyperparameter_search_report(df: pd.DataFrame, task: ClassificationTaskSpec = RAW_TASK) -> pd.DataFrame:
    """ LightGBM 파라미터 그리드를 F1 기준으로 탐색한다.

    노트북은 Train+Val을 합치지 않고 `grid_search.fit(X_train, y_train)`으로 **Train(60%)에서
    바로** 5-fold CV를 돌린 뒤, 같은 Train(60%)으로 최적 파라미터를 재조립해 재학습한다
    (`regression_search.py`의 `grid_search`가 Train+Val 80%에서 탐색하는 것과는 다른 패턴 —
    이건 회귀 노트북과 분류 노트북이 실제로 다르게 짜여 있었기 때문이며, 여기서는 분류
    노트북 원본 그대로 따른다). Validation은 탐색에 전혀 관여하지 않으므로, 아래 board의
    Validation 점수는 완전히 처음 보는 데이터에 대한 깨끗한 평가다.
    """
    Xtr, Xva, Xte, ytr, yva, yte = _split(task, df)

    base_pipe = Pipeline(
        [
            ("prep", build_preprocessor(Xtr)),
            ("model", LGBMClassifier(class_weight="balanced", random_state=RANDOM_STATE, verbose=-1)),
        ]
    )
    search = GridSearchCV(base_pipe, PARAM_GRID, scoring="f1", cv=5, n_jobs=-1).fit(Xtr, ytr)
    best_params = {k.replace("model__", ""): v for k, v in search.best_params_.items()}

    # 노트북 47번 셀과 동일하게, 찾은 파라미터로 Train(60%) 위에 다시 조립한다
    # (GridSearchCV의 best_estimator_와 동일한 데이터로 재학습하는 것이라 결과는 같지만,
    # "탐색"과 "최종 후보 모델"의 책임을 코드로도 분리해 둔다).
    model = Pipeline(
        [
            ("prep", build_preprocessor(Xtr)),
            ("model", LGBMClassifier(**best_params, class_weight="balanced", random_state=RANDOM_STATE, verbose=-1)),
        ]
    ).fit(Xtr, ytr)

    board = pd.DataFrame(
        [
            evaluate_classification("GridSearchCV", "Validation", model, Xva, yva),
            evaluate_classification("GridSearchCV", "Test", model, Xte, yte),
        ]
    )
    board["Best_Params"] = [best_params, best_params]
    return board


def main() -> None:
    """베이스라인 → 피처 엔지니어링 → 하이퍼파라미터 탐색 3종을 실행하고 각각 리포트로 저장한다.

    `final/classification_final.py`는 이 main()을 호출하지 않는다 — 여기서 나온 결론은
    `BEST_PARAMS` 상수로 이 파일 위쪽에 값을 굳혀 넣고, final은 그 상수만 가져다 쓴다.
    """
    df = load_raw_data()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    baseline = baseline_report(df)
    baseline.to_csv(REPORT_DIR / "classification_baseline_report.csv", index=False)
    print("[베이스라인] 원본 피처, 미세튜닝 없음:")
    print(baseline.round(4).to_string(index=False))
    print(f"저장 완료: {REPORT_DIR / 'classification_baseline_report.csv'}\n")

    fe_report = feature_engineering_report(df)
    fe_report.to_csv(REPORT_DIR / "classification_feature_engineering_report.csv", index=False)
    print("[피처 엔지니어링] 원본 피처 vs 파생변수 추가:")
    print(fe_report.round(4).to_string(index=False))
    print(f"저장 완료: {REPORT_DIR / 'classification_feature_engineering_report.csv'}\n")

    search_board = hyperparameter_search_report(df)
    search_board.to_csv(REPORT_DIR / "classification_hyperparameter_search.csv", index=False)
    print("[하이퍼파라미터 최적화] GridSearchCV:")
    print(search_board.drop(columns=["Best_Params"]).round(4).to_string(index=False))
    print(f"저장 완료: {REPORT_DIR / 'classification_hyperparameter_search.csv'}")
    print(f"\n찾은 파라미터: {search_board['Best_Params'].iloc[0]}")
    print("이 값을 이 파일 위쪽 BEST_PARAMS에 반영하면 final/classification_final.py에 적용됩니다.")


if __name__ == "__main__":
    main()
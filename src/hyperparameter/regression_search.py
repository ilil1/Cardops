"""회귀 탐색·비교 3종: 베이스라인, 피처 엔지니어링, 하이퍼파라미터. (★상세 구현 대상)

`04_regression_final.ipynb`의 탐색 단계(2~4번 섹션)를 그대로 옮겼다:
  1. `baseline_report`            — 원본 피처(파생변수 없음)로 LinearRegression/RandomForest/XGBoost 기본 성능
  2. `feature_engineering_report` — 원본 피처 vs 파생변수 추가 (XGB, 미세튜닝 없음)
  3. `hyperparameter_search_report`(4가지 방법 비교):
       - `manual_search`      — 수동 그리드를 모두 돌며 Validation R²로 직접 비교
       - `randomized_search`  — RandomizedSearchCV (Train+Val 80%에서 CV 탐색)
       - `grid_search`        — GridSearchCV (Train+Val 80%에서 CV 탐색)
       - `optuna_search`      — Optuna TPE 샘플러

이 모듈은 **탐색·비교만 하고 최종 모델을 저장하지 않는다** — `clustering_search.py`가
`clustering_final.py`와 완전히 분리되어 독립 실행되는 것과 같은 패턴이다. 여기서 나온
결론(`XGB_BEST_PARAMS`)은 `final/regression_final.py`에 **값으로 굳혀 넣는다** — final이
이 모듈을 매번 다시 호출해 재탐색하지 않는다(아래 실행 방법 참고).

`feature_engine/regression_features.py`가 넘겨주는 X는 아직 원-핫 인코딩 전(raw)이라,
모든 탐색은 `Pipeline(build_preprocessor(X) + 모델)`로 감싸서 진행한다(전처리는 Train에만
fit, Validation/Test는 transform만 — 데이터 누수 방지). GridSearchCV/RandomizedSearchCV의
파라미터 그리드 키는 파이프라인 스텝 이름을 붙여 `model__n_estimators`처럼 써야 한다.

실행: python src/hyperparameter/regression_search.py
(regression_baseline_report.csv, regression_feature_engineering_report.csv,
 regression_hyperparameter_search.csv 3개를 outputs/reports/에 저장한다)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import itertools
from dataclasses import dataclass
from typing import Any

import optuna
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score
from sklearn.model_selection import GridSearchCV, RandomizedSearchCV, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from xgboost import XGBRegressor

from common.config import RANDOM_STATE, REPORT_DIR
from common.data import load_raw_data
from common.evaluate import evaluate_regression
from feature_engine.regression_features import CT_GAP_TASK, RAW_TASK, RegressionTaskSpec, build_preprocessor

optuna.logging.set_verbosity(optuna.logging.WARNING)

# 이 모듈을 한 번 실행해 찾아둔 기본값 — final/regression_final.py가 이 값을 그대로 상수로
# 가져다 쓴다(재탐색하지 않음). 다시 탐색하려면 `python src/hyperparameter/regression_search.py`를
# 실행해 regression_hyperparameter_search.csv를 보고 이 값을 갱신하면 된다.
XGB_BEST_PARAMS: dict = dict(
    n_estimators=500,
    max_depth=5,
    learning_rate=0.01,
    subsample=0.8,
    random_state=RANDOM_STATE,
)


@dataclass
class SearchResult:
    method: str
    best_params: dict[str, Any]
    model: Pipeline
    val_r2: float


def _make_pipeline(Xtr: pd.DataFrame, params: dict[str, Any], random_state: int = RANDOM_STATE) -> Pipeline:
    """전처리(Train에만 fit) + XGBRegressor 파이프라인을 만든다."""
    return Pipeline(
        [
            ("prep", build_preprocessor(Xtr)),
            ("model", XGBRegressor(random_state=random_state, **params)),
        ]
    )


# ---------------------------------------------------------------------------
# 1. 수동 Validation 탐색
# ---------------------------------------------------------------------------
MANUAL_GRID: dict[str, list] = {
    "n_estimators": [200, 500],
    "max_depth": [5, 7],
    "learning_rate": [0.01, 0.05],
    "subsample": [0.8, 1.0],
}


def manual_search(
    Xtr, ytr, Xva, yva, grid: dict[str, list] | None = None, random_state: int = RANDOM_STATE
) -> SearchResult:
    """모든 조합을 직접 돌며 Validation R²로 최적 파라미터를 고른다."""
    grid = grid or MANUAL_GRID
    keys, vals = zip(*grid.items())
    rows = []
    for combo in itertools.product(*vals):
        params = dict(zip(keys, combo))
        pipe = _make_pipeline(Xtr, params, random_state).fit(Xtr, ytr)
        rows.append({**params, "Val_R2": r2_score(yva, pipe.predict(Xva))})

    board = pd.DataFrame(rows).sort_values("Val_R2", ascending=False)
    best_row = board.iloc[0][list(grid)].to_dict()
    best_params = {k: (int(v) if k in ("n_estimators", "max_depth") else v) for k, v in best_row.items()}
    model = _make_pipeline(Xtr, best_params, random_state).fit(Xtr, ytr)
    val_r2 = r2_score(yva, model.predict(Xva))
    return SearchResult("수동탐색", best_params, model, val_r2)


# ---------------------------------------------------------------------------
# 2. RandomizedSearchCV
# ---------------------------------------------------------------------------
RANDOMIZED_DIST: dict[str, list] = {
    "model__n_estimators": [100, 200, 300, 500],
    "model__max_depth": [3, 5, 7, 10],
    "model__learning_rate": [0.01, 0.05, 0.1, 0.2],
    "model__subsample": [0.7, 0.8, 1.0],
    "model__colsample_bytree": [0.7, 0.8, 1.0],
}


def randomized_search(
    Xtv,
    ytv,
    Xtr,
    ytr,
    Xva,
    yva,
    dist: dict[str, list] | None = None,
    n_iter: int = 8,
    cv: int = 3,
    random_state: int = RANDOM_STATE,
) -> SearchResult:
    """RandomizedSearchCV로 Train+Val(80%)에서 탐색 후, Train(60%)만으로 재학습한다."""
    dist = dist or RANDOMIZED_DIST
    base_pipe = _make_pipeline(Xtv, {}, random_state)
    search = RandomizedSearchCV(
        base_pipe, dist, n_iter=n_iter, scoring="r2", cv=cv, random_state=random_state, n_jobs=-1
    ).fit(Xtv, ytv)
    best_params = {k.replace("model__", ""): v for k, v in search.best_params_.items()}
    model = _make_pipeline(Xtr, best_params, random_state).fit(Xtr, ytr)
    val_r2 = r2_score(yva, model.predict(Xva))
    return SearchResult("RandomizedSearchCV", best_params, model, val_r2)


# ---------------------------------------------------------------------------
# 3. GridSearchCV
# ---------------------------------------------------------------------------
GRID_PARAMS: dict[str, list] = {
    "model__n_estimators": [200, 500],
    "model__max_depth": [5, 7],
    "model__learning_rate": [0.01, 0.05],
    "model__subsample": [0.8],
}


def grid_search(
    Xtv,
    ytv,
    Xtr,
    ytr,
    Xva,
    yva,
    param_grid: dict[str, list] | None = None,
    cv: int = 3,
    random_state: int = RANDOM_STATE,
) -> SearchResult:
    """GridSearchCV로 Train+Val(80%)에서 탐색 후, Train(60%)만으로 재학습한다."""
    param_grid = param_grid or GRID_PARAMS
    base_pipe = _make_pipeline(Xtv, {}, random_state)
    search = GridSearchCV(base_pipe, param_grid, scoring="r2", cv=cv, n_jobs=-1).fit(Xtv, ytv)
    best_params = {k.replace("model__", ""): v for k, v in search.best_params_.items()}
    model = _make_pipeline(Xtr, best_params, random_state).fit(Xtr, ytr)
    val_r2 = r2_score(yva, model.predict(Xva))
    return SearchResult("GridSearchCV", best_params, model, val_r2)


# ---------------------------------------------------------------------------
# 4. Optuna (TPE 샘플러)
# ---------------------------------------------------------------------------
def optuna_search(
    Xtv,
    ytv,
    Xtr,
    ytr,
    Xva,
    yva,
    n_trials: int = 12,
    cv: int = 3,
    random_state: int = RANDOM_STATE,
) -> SearchResult:
    """Optuna TPE 샘플러로 Train+Val(80%)에서 탐색 후, Train(60%)만으로 재학습한다."""

    def objective(trial: optuna.Trial) -> float:
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 100, 600, step=100),
            "max_depth": trial.suggest_int("max_depth", 3, 10),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
        }
        pipe = _make_pipeline(Xtv, params, random_state)
        return cross_val_score(pipe, Xtv, ytv, cv=cv, scoring="r2").mean()

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=random_state))
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    model = _make_pipeline(Xtr, study.best_params, random_state).fit(Xtr, ytr)
    val_r2 = r2_score(yva, model.predict(Xva))
    return SearchResult("Optuna", study.best_params, model, val_r2)


# ---------------------------------------------------------------------------
# 오케스트레이터
# ---------------------------------------------------------------------------
def run_all_searches(
    Xtr, Xva, Xte, ytr, yva, yte, Xtv, ytv
) -> tuple[dict[str, SearchResult], pd.DataFrame]:
    """네 가지 탐색을 모두 실행하고, Validation R² 기준 비교표를 함께 반환한다.

    비교표는 Validation R² 내림차순으로 정렬되어 있어 `board.iloc[0]`이 최종 채택 후보다
    (Test는 이 시점에 참고로만 병기하고, 실제 모델 선택에는 쓰지 않는다).
    """
    results = {
        r.method: r
        for r in (
            manual_search(Xtr, ytr, Xva, yva),
            randomized_search(Xtv, ytv, Xtr, ytr, Xva, yva),
            grid_search(Xtv, ytv, Xtr, ytr, Xva, yva),
            optuna_search(Xtv, ytv, Xtr, ytr, Xva, yva),
        )
    }
    board = (
        pd.DataFrame(
            [
                {
                    "방법": r.method,
                    "Val_R2": r.val_r2,
                    "Test_R2": r2_score(yte, r.model.predict(Xte)),
                    "Best_Params": r.best_params,
                }
                for r in results.values()
            ]
        )
        .sort_values("Val_R2", ascending=False)
        .reset_index(drop=True)
    )
    return results, board


# ---------------------------------------------------------------------------
# 탐색 대상 데이터 분할 (베이스라인/피처엔지니어링/하이퍼파라미터 3종이 공유)
# ---------------------------------------------------------------------------
def _split(task: RegressionTaskSpec, df: pd.DataFrame):
    """태스크의 raw X/y를 60/20/20(Train/Val/Test)으로 나눈다."""
    X, y = task.to_X_y(df)
    Xtv, Xte, ytv, yte = train_test_split(X, y, test_size=0.2, random_state=RANDOM_STATE)
    Xtr, Xva, ytr, yva = train_test_split(Xtv, ytv, test_size=0.25, random_state=RANDOM_STATE)
    return Xtr, Xva, Xte, ytr, yva, yte, Xtv, ytv


# ---------------------------------------------------------------------------
# 1. 베이스라인 — 원본 피처(파생변수 없음, 금액 포함)로 3개 모델 기본 성능
# ---------------------------------------------------------------------------
def baseline_report(df: pd.DataFrame) -> pd.DataFrame:
    """LinearRegression/RandomForest/XGBoost 기본 성능(미세튜닝 없음)."""
    Xtr, Xva, Xte, ytr, yva, yte, _, _ = _split(RAW_TASK, df)

    candidates = {
        "LinearRegression": LinearRegression(),
        "RandomForest": RandomForestRegressor(n_estimators=200, random_state=RANDOM_STATE),
        "XGBoost": XGBRegressor(n_estimators=200, random_state=RANDOM_STATE),
    }
    rows = []
    for name, estimator in candidates.items():
        pipe = Pipeline([("prep", build_preprocessor(Xtr)), ("model", estimator)]).fit(Xtr, ytr)
        rows.append(evaluate_regression(name, "Validation", pipe, Xva, yva))
        rows.append(evaluate_regression(name, "Test", pipe, Xte, yte))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 2. 피처 엔지니어링 — 원본 피처 vs 파생변수 추가 (XGB, 미세튜닝 없음, 금액은 둘 다 제외)
# ---------------------------------------------------------------------------
def feature_engineering_report(df: pd.DataFrame) -> pd.DataFrame:
    """파생변수 추가 전후 XGBoost 성능 비교.

    금액(Total_Trans_Amt)은 처음부터 두 버전 모두 제외한다 — 04번 노트북 8번 섹션에서
    확인된 대로 금액을 포함하면 Test R²는 오르지만 활동성 갭의 이탈 판별력이 떨어지기
    때문에, py 파이프라인에서는 금액 포함 버전(A) 자체를 만들지 않는다.
    """
    labels = {RAW_TASK.name: "원본_피처만", CT_GAP_TASK.name: "파생변수_추가"}
    rows = []
    for task in (RAW_TASK, CT_GAP_TASK):
        Xtr, Xva, Xte, ytr, yva, yte, _, _ = _split(task, df)
        pipe = Pipeline(
            [("prep", build_preprocessor(Xtr)), ("model", XGBRegressor(n_estimators=200, random_state=RANDOM_STATE))]
        ).fit(Xtr, ytr)
        label = labels[task.name]
        rows.append(evaluate_regression(label, "Validation", pipe, Xva, yva))
        rows.append(evaluate_regression(label, "Test", pipe, Xte, yte))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 3. 하이퍼파라미터 최적화 — 수동/GridSearchCV/RandomizedSearchCV/Optuna 비교
# ---------------------------------------------------------------------------
def hyperparameter_search_report(df: pd.DataFrame, task: RegressionTaskSpec = CT_GAP_TASK) -> pd.DataFrame:
    """파생변수 추가 + 금액 제외 데이터에서 4가지 탐색법 비교.

    실제 최종 모델(final/regression_final.py)이 쓰는 피처 구성과 동일한 데이터로
    탐색해야 여기서 찾은 파라미터가 최종 모델에도 그대로 유효하다.
    """
    Xtr, Xva, Xte, ytr, yva, yte, Xtv, ytv = _split(task, df)
    _, board = run_all_searches(Xtr, Xva, Xte, ytr, yva, yte, Xtv, ytv)
    return board


def main() -> None:
    """베이스라인 → 피처 엔지니어링 → 하이퍼파라미터 탐색 3종을 실행하고 각각 리포트로 저장한다.

    `final/regression_final.py`는 이 main()을 호출하지 않는다 — 여기서 나온 결론은
    `XGB_BEST_PARAMS` 상수로 이 파일 위쪽에 값을 굳혀 넣고, final은 그 상수만 가져다 쓴다.
    """
    df = load_raw_data()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    baseline = baseline_report(df)
    baseline.to_csv(REPORT_DIR / "regression_baseline_report.csv", index=False)
    print("[베이스라인] 원본 피처, 미세튜닝 없음:")
    print(baseline.round(4).to_string(index=False))
    print(f"저장 완료: {REPORT_DIR / 'regression_baseline_report.csv'}\n")

    fe_report = feature_engineering_report(df)
    fe_report.to_csv(REPORT_DIR / "regression_feature_engineering_report.csv", index=False)
    print("[피처 엔지니어링] 원본 피처 vs 파생변수 추가:")
    print(fe_report.round(4).to_string(index=False))
    print(f"저장 완료: {REPORT_DIR / 'regression_feature_engineering_report.csv'}\n")

    search_board = hyperparameter_search_report(df)
    search_board.to_csv(REPORT_DIR / "regression_hyperparameter_search.csv", index=False)
    print("[하이퍼파라미터 최적화] 수동/Grid/Random/Optuna:")
    print(search_board[["방법", "Val_R2", "Test_R2"]].round(4).to_string(index=False))
    print(f"저장 완료: {REPORT_DIR / 'regression_hyperparameter_search.csv'}")

    best = search_board.iloc[0]
    print(f"\n최적 방법: {best['방법']}  Best_Params={best['Best_Params']}")
    print("이 값을 이 파일 위쪽 XGB_BEST_PARAMS에 반영하면 final/regression_final.py에 적용됩니다.")


if __name__ == "__main__":
    main()

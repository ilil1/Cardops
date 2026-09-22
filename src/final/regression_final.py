"""회귀 최종 파이프라인 — Voting 최종 모델 학습 + Test 1회 평가 + 활동성 갭 + OOF 저장.

거래금액(Total_Trans_Amt)을 포함하면 Test R²는 오르지만 활동성 갭의 이탈 판별력(AUC)이 떨어진다.
그래서 이 py 파이프라인은 "금액 포함(A) vs 금액 제외(B)" 비교 자체를 만들지 않고,
처음부터 금액 제외 구성(`feature_engine.regression_features.CT_GAP_TASK`) 하나만 쓴다.

베이스라인·피처 엔지니어링·하이퍼파라미터 비교는 이 파일이 하지 않는다 — 전부
`hyperparameter/regression_search.py`가 독립적으로 실행하고 저장한다
(`python src/hyperparameter/regression_search.py`). 이 파일은 그 탐색에서 나온 결론
(`XGB_BEST_PARAMS`, `regression_search.py`에 값으로 굳혀둔 상수)을 그대로 가져다
Voting 앙상블(XGB+RF+GBR+LightGBM)을 재학습하고, Test는 한 번만 평가하며, 전체 고객
OOF(Out-Of-Fold) 예측을 계산해 저장한다 — `clustering_final.py`가 `clustering_search.py`를
실행 시점에 다시 호출하지 않고 `K_BY_VARIANT` 상수를 쓰는 것과 같은 패턴이다.

역할 분담:
  - `feature_engine/regression_features.py` — 피처 엔지니어링(무엇을 넣고 뺄지) + 전처리 재노출
  - `hyperparameter/regression_search.py`   — 베이스라인·피처엔지니어링·하이퍼파라미터 비교(독립 실행)
  - 이 파일                                  — Voting 최종 모델 학습 + Test 1회 평가 + 저장만

전처리(`build_preprocessor`)는 항상 `Pipeline(prep, model)`로 묶어 Train에만 fit하고
Validation/Test/OOF는 transform만 한다 — 저장되는 모델도 전처리가 포함된 완성형이라
새 원본 데이터에 바로 `predict()`를 호출할 수 있다.

실행: python src/final/regression_final.py
(하이퍼파라미터를 다시 탐색해 XGB_BEST_PARAMS를 갱신하려면 그 전에
 python src/hyperparameter/regression_search.py 를 먼저 실행하고 값을 반영하세요.)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from typing import Any

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor, VotingRegressor
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_absolute_error, r2_score, roc_auc_score
from sklearn.model_selection import KFold, cross_val_predict, train_test_split
from sklearn.pipeline import Pipeline
from xgboost import XGBRegressor

from common import config
from common.data import load_raw_data
from common.evaluate import evaluate_regression, make_regression_predictions
from feature_engine.regression_features import CT_GAP_TASK, RegressionTaskSpec, build_preprocessor
from hyperparameter.regression_search import XGB_BEST_PARAMS

MODEL_NAME = "Voting"
CHURN_COL = "Target"
TASK = CT_GAP_TASK  # 이 파이프라인이 다루는 유일한 회귀 태스크 (금액 제외 + 파생변수)


def _split(task: RegressionTaskSpec, df: pd.DataFrame):
    """태스크의 raw X/y를 60/20/20(Train/Val/Test)으로 나눈다."""
    X, y = task.to_X_y(df)
    Xtv, Xte, ytv, yte = train_test_split(X, y, test_size=0.2, random_state=config.RANDOM_STATE)
    Xtr, Xva, ytr, yva = train_test_split(Xtv, ytv, test_size=0.25, random_state=config.RANDOM_STATE)
    return Xtr, Xva, Xte, ytr, yva, yte, Xtv, ytv


def _make_ensemble_members(xgb_params: dict[str, Any]):
    """학습 안 된(unfitted) XGB/RF/GradientBoost/LightGBM 4개를 만든다."""
    return [
        ("xgb", XGBRegressor(**xgb_params)),
        ("rf", RandomForestRegressor(n_estimators=150, random_state=config.RANDOM_STATE)),
        (
            "gbr",
            GradientBoostingRegressor(
                n_estimators=150, max_depth=4, learning_rate=0.03, random_state=config.RANDOM_STATE
            ),
        ),
        (
            "lgbm",
            LGBMRegressor(
                n_estimators=150, max_depth=5, learning_rate=0.05, random_state=config.RANDOM_STATE, verbose=-1
            ),
        ),
    ]


def build_voting_pipeline(Xtr: pd.DataFrame, ytr: pd.Series, xgb_params: dict[str, Any]) -> Pipeline:
    """전처리(Train에 fit) + Voting 앙상블(XGB+RF+GBR+LightGBM)을 하나의 Pipeline으로 학습한다.

    Stacking은 내부 CV가 바깥쪽 OOF와 중첩되면 예측이 무너질 수 있어(12절 참고) 애초에 후보에 넣지 않는다.
    """
    preprocessor = build_preprocessor(Xtr)
    Xtr_enc = preprocessor.fit_transform(Xtr)

    fitted_members = [(name, est.fit(Xtr_enc, ytr)) for name, est in _make_ensemble_members(xgb_params)]
    voting = VotingRegressor(fitted_members).fit(Xtr_enc, ytr)

    return Pipeline([("prep", preprocessor), ("model", voting)])


def make_voting_pipeline_unfitted(X_sample: pd.DataFrame, xgb_params: dict[str, Any]) -> Pipeline:
    """학습 안 된 전처리+Voting 파이프라인 (OOF `cross_val_predict`용 — fold마다 새로 학습됨)."""
    return Pipeline(
        [("prep", build_preprocessor(X_sample)), ("model", VotingRegressor(_make_ensemble_members(xgb_params)))]
    )


def _gap_metrics(
    pipeline: Pipeline, X_test: pd.DataFrame, y_test: pd.Series, churn_labels: pd.Series, low_quantile: float = 0.2
) -> tuple[dict, pd.DataFrame]:
    """활동성 갭(실제 − 예측) 기반 이탈 조기경보 지표 — 이 프로젝트 고유 비즈니스 지표."""
    pred = pipeline.predict(X_test)
    gap = y_test.values - pred
    churn = churn_labels.loc[X_test.index].values
    thr = np.quantile(gap, low_quantile)
    flag = gap <= thr

    pct = int(low_quantile * 100)
    metrics = {
        "Test_R2": r2_score(y_test, pred),
        "Test_MAE": mean_absolute_error(y_test, pred),
        "갭_이탈_상관": float(np.corrcoef(gap, churn)[0, 1]),
        "AUC": roc_auc_score(churn, -gap),
        f"하위{pct}%_포착률(%)": churn[flag].sum() / churn.sum() * 100,
        "위험군_정확도(%)": churn[flag].mean() * 100,
    }
    detail = pd.DataFrame(
        {"실제_거래건수": y_test.values, "예측_거래건수": pred, "활동성_갭": gap, "실제_이탈여부": churn},
        index=X_test.index,
    )
    return metrics, detail


def main() -> dict[str, Any]:
    """Voting 최종 모델 학습 → Test 1회 평가 → 활동성 갭 → OOF 저장."""
    config.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    config.REPORT_DIR.mkdir(parents=True, exist_ok=True)

    df = load_raw_data()
    churn_labels = df[CHURN_COL]
    xgb_params = dict(XGB_BEST_PARAMS)

    Xtr, Xva, Xte, ytr, yva, yte, _, _ = _split(TASK, df)
    X, y = TASK.to_X_y(df)

    pipeline = build_voting_pipeline(Xtr, ytr, xgb_params)
    board = pd.DataFrame(
        [
            evaluate_regression(MODEL_NAME, "Validation", pipeline, Xva, yva),
            evaluate_regression(MODEL_NAME, "Test", pipeline, Xte, yte),
        ]
    )
    print(f"[{TASK.name}] Voting 앙상블 Validation/Test:")
    print(board.round(4).to_string(index=False))

    # 진단용: Voting은 feature_importances_가 없어 permutation importance로 대체한다.
    # 노트북의 "예측 근거 Top8"과 직접 비교할 수 있도록 원본(raw) 컬럼 단위로 계산한다
    # (Pipeline이 내부에서 인코딩을 처리하므로 Xva를 원본 그대로 넘겨도 된다).
    # Docker/CI의 제한된 실행 환경에서도 재현 가능하게 동작하도록
    # 프로세스 기반 병렬화를 사용하지 않는다.
    perm = permutation_importance(
        pipeline,
        Xva,
        yva,
        n_repeats=5,
        random_state=config.RANDOM_STATE,
        n_jobs=1,
    )
    importance = pd.Series(perm.importances_mean, index=Xva.columns).sort_values(ascending=False)
    print("\n예측 근거 Top10 (Permutation Importance, Validation 기준):")
    print(importance.head(10).round(4).to_string())
    importance.to_frame("importance").to_csv(config.REPORT_DIR / "regression_feature_importance.csv")
    print(f"저장 완료: {config.REPORT_DIR / 'regression_feature_importance.csv'}")

    predictions = make_regression_predictions(MODEL_NAME, pipeline, Xte, yte)
    metrics, gap_detail = _gap_metrics(pipeline, Xte, yte, churn_labels)

    gap_metrics_df = pd.DataFrame([{"버전": TASK.name, "피처수": X.shape[1], **metrics}]).set_index("버전")
    print("\n활동성 갭 기반 이탈 조기경보 지표 (Test는 이 시점에 한 번만 평가):\n", gap_metrics_df.round(3))

    # 전체 고객 OOF 갭 — clustering_final.py의 get_activity_gap_features()가
    # Actual/Predicted/Residual 스키마를 기대하므로 make_regression_predictions()와
    # 동일한 컬럼 구성으로 직접 만든다 (cross_val_predict는 단일 fit된 모델이 아니라
    # make_regression_predictions()를 그대로 재사용할 수 없다).
    oof_estimator = make_voting_pipeline_unfitted(X, xgb_params)
    kf = KFold(n_splits=5, shuffle=True, random_state=config.RANDOM_STATE)  # 정렬된 데이터라 shuffle 필수
    oof_pred = cross_val_predict(oof_estimator, X, y, cv=kf, n_jobs=1)
    gap_oof_predictions = pd.DataFrame(
        {
            "Model": MODEL_NAME,
            "Actual": y.to_numpy(),
            "Predicted": oof_pred,
            "Residual": y.to_numpy() - oof_pred,
        }
    )
    gap_oof_predictions.to_csv(config.REPORT_DIR / "regression_gap_oof_predictions.csv", index=False)

    # 산출물 저장: 학습 모델(joblib), 평가·예측·갭 결과(csv)
    joblib.dump(pipeline, config.MODEL_DIR / "regression_model.joblib")

    board.to_csv(config.REPORT_DIR / "regression_evaluation.csv", index=False, encoding="utf-8-sig")
    predictions.to_csv(config.REPORT_DIR / "regression_gap_predictions.csv", index=False)
    gap_metrics_df.to_csv(config.REPORT_DIR / "regression_gap_metrics.csv", encoding="utf-8-sig")

    print(f"\n저장 완료: {config.MODEL_DIR / 'regression_model.joblib'}")
    print(f"저장 완료: {config.REPORT_DIR / 'regression_evaluation.csv'}")
    print(f"저장 완료: {config.REPORT_DIR / 'regression_gap_metrics.csv'}")
    print(f"저장 완료: {config.REPORT_DIR / 'regression_gap_predictions.csv'} (Test 전용, 참고용)")
    print(f"저장 완료: {config.REPORT_DIR / 'regression_gap_oof_predictions.csv'} (전체 고객 OOF, clustering_final.py가 읽음)")

    return {
        "model": pipeline,
        "board": board,
        "predictions": predictions,
        "gap_metrics": gap_metrics_df,
        "gap_detail": gap_detail,
        "gap_oof_predictions": gap_oof_predictions,
    }


if __name__ == "__main__":
    main()

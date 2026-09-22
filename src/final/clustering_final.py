"""최종 k(또는 n_components)로 군집 4종을 학습하고, 프로파일과 모델을 저장한다.

- behavioral_core: KMeans k=3 (hyperparameter/clustering_search.py 검증값, Silhouette≈0.218)
- behavioral_extended: KMeans k=4 (notebooks/credit_card_retention_ml.ipynb §5 참고값, Silhouette=0.1946)
- credit_capacity: KMeans k=2 (hyperparameter/clustering_search.py 검증값, Silhouette≈0.469)
- activity_gap: GMM(spherical) k=3 (notebooks/05_1/05_2clustering.ipynb 참고값 — Silhouette만
  보면 KMeans k=2가 더 높지만, "우선케어·일반관리·우량" 3단계 비즈니스 해석을 위해 GMM k=3을
  최종으로 쓴다) — regression_final.py가 저장한 outputs/reports/regression_gap_oof_predictions.csv가
  있어야 실행된다(docs/src_architecture.md 3절: regression_final → clustering_final 순서 강제).

  Test 예측(regression_gap_predictions.csv, 2,026명)이 아니라 5-fold out-of-fold
  예측(전체 10,127명)을 쓴다 — Test 예측만 쓰면 활동성 갭 군집이 고객의 20%에게만
  적용되고, Train/Val 고객은 세그먼트를 받지 못한다(notebooks/05_1clustering.ipynb
  리뷰에서 지적된 문제). OOF 파일은 전체 고객을 커버하므로 여기서도 다른 3개
  변형처럼 Churn_Rate 프로파일링이 가능하다.

실행: python src/final/clustering_final.py
(activity_gap까지 보려면 그 전에 python src/final/regression_final.py 를 먼저 실행)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import joblib
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.mixture import GaussianMixture

from common.config import MODEL_DIR, RANDOM_STATE, REPORT_DIR
from common.data import load_raw_data
from feature_engine.clustering_features import (
    build_preprocessor,
    get_activity_gap_features,
    get_behavioral_core_features,
    get_behavioral_extended_features,
    get_credit_capacity_features,
)

K_BY_VARIANT = {
    "behavioral_core": 3,
    "behavioral_extended": 4,
    "credit_capacity": 2,
    "activity_gap": 3,
}
# activity_gap만 GMM(spherical)을 쓴다 — 나머지 3종은 KMeans.
MODEL_TYPE_BY_VARIANT = {
    "behavioral_core": "kmeans",
    "behavioral_extended": "kmeans",
    "credit_capacity": "kmeans",
    "activity_gap": "gmm",
}
GMM_COVARIANCE_TYPE = "spherical"
GAP_PREDICTIONS_PATH = REPORT_DIR / "regression_gap_oof_predictions.csv"


def _fit_and_save(name: str, X: pd.DataFrame, k: int, churn: pd.Series | None, model_type: str = "kmeans") -> None:
    scaler = build_preprocessor()
    X_scaled = scaler.fit_transform(X)

    if model_type == "gmm":
        model = GaussianMixture(
            n_components=k, covariance_type=GMM_COVARIANCE_TYPE, random_state=RANDOM_STATE, n_init=10
        )
        model.fit(X_scaled)
        labels = model.predict(X_scaled)
    else:
        model = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=10)
        labels = model.fit_predict(X_scaled)

    sil = silhouette_score(
        X_scaled, labels, sample_size=min(3000, len(X_scaled)), random_state=RANDOM_STATE
    )

    df_profile = X.copy()
    df_profile["Cluster"] = labels
    cluster_profile = df_profile.groupby("Cluster").mean().round(3)
    cluster_profile.insert(0, "Customer_Count", df_profile.groupby("Cluster").size())

    if churn is not None:
        churn_series = pd.Series(churn.to_numpy(), index=df_profile.index)
        cluster_profile["Churn_Rate"] = churn_series.groupby(df_profile["Cluster"]).mean().round(4)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"features": list(X.columns), "scaler": scaler, "model": model},
        MODEL_DIR / f"clustering_{name}.joblib",
    )
    cluster_profile.to_csv(REPORT_DIR / f"clustering_{name}_profile.csv")

    label = f"{model_type.upper()} k={k}" if model_type == "kmeans" else f"GMM({GMM_COVARIANCE_TYPE}) k={k}"
    print(f"\n[{name}] {label} Silhouette={sil:.4f}")
    print(cluster_profile.to_string())


def main() -> None:
    df = load_raw_data()

    _fit_and_save(
        "behavioral_core",
        get_behavioral_core_features(df),
        K_BY_VARIANT["behavioral_core"],
        df["Target"],
        MODEL_TYPE_BY_VARIANT["behavioral_core"],
    )
    _fit_and_save(
        "behavioral_extended",
        get_behavioral_extended_features(df),
        K_BY_VARIANT["behavioral_extended"],
        df["Target"],
        MODEL_TYPE_BY_VARIANT["behavioral_extended"],
    )
    _fit_and_save(
        "credit_capacity",
        get_credit_capacity_features(df),
        K_BY_VARIANT["credit_capacity"],
        df["Target"],
        MODEL_TYPE_BY_VARIANT["credit_capacity"],
    )

    if GAP_PREDICTIONS_PATH.exists():
        predictions = pd.read_csv(GAP_PREDICTIONS_PATH)
        X_gap = get_activity_gap_features(predictions)
        # OOF 예측은 전체 고객을 원본 순서 그대로 커버하므로 df["Target"]과
        # 행 순서가 그대로 대응된다 — 다른 3개 변형처럼 Churn_Rate도 낼 수 있다.
        _fit_and_save(
            "activity_gap", X_gap, K_BY_VARIANT["activity_gap"], df["Target"], MODEL_TYPE_BY_VARIANT["activity_gap"]
        )
    else:
        print(
            f"\n[activity_gap] 건너뜀 (파일 없음: {GAP_PREDICTIONS_PATH}). "
            "먼저 python src/final/regression_final.py 를 실행하세요."
        )

    print(f"\n모델 저장 위치: {MODEL_DIR}")
    print(f"결과 저장 위치: {REPORT_DIR}")


if __name__ == "__main__":
    main()

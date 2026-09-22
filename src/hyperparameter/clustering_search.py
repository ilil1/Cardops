"""k(또는 n_components) 탐색 + Silhouette. KMeans와 GaussianMixture 둘 다 지원한다.

behavioral_core/extended, credit_capacity 3개 피처셋(원본 CSV만으로 계산 가능한
것들)에 대해 실행해 참고값(behavioral_core k=3 Silhouette≈0.218, credit_capacity
k=2 Silhouette≈0.469)과 방향이 같은지 확인한다. activity_gap은 회귀 결과가 있어야
계산되므로(docs/src_architecture.md 결정 B) `regression_gap_oof_predictions.csv`가
있을 때만 자동으로 포함한다 — 없으면 건너뛰고 나머지 피처셋만 탐색한다
(`final/clustering_final.py`가 activity_gap을 건너뛰는 것과 같은 패턴).
python src/final/regression_final.py 를 먼저 실행해두면 이 스크립트가 그 결과를 집어
activity_gap까지 탐색한다.

실루엣 계산은 속도를 위해 표본 3,000개로 근사한다(기존 src/clustering.py 방식) —
credit_card_retention_ml.ipynb의 참고값은 전체 데이터로 계산됐으므로 소수점 단위
차이는 정상이다.

실행: python src/hyperparameter/clustering_search.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

from common.config import RANDOM_STATE, REPORT_DIR
from feature_engine.clustering_features import (
    get_activity_gap_features,
    get_behavioral_core_features,
    get_credit_capacity_features,
)

SAMPLE_SIZE = 3000
GAP_PREDICTIONS_PATH = REPORT_DIR / "regression_gap_oof_predictions.csv"


def search(X: pd.DataFrame, k_range: range = range(2, 9)) -> pd.DataFrame:
    """KMeans와 GaussianMixture를 k_range 전체에 대해 돌려 Silhouette을 비교한다."""
    X_scaled = StandardScaler().fit_transform(X)
    rows = []

    for k in k_range:
        km = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=10).fit(X_scaled)
        km_sil = silhouette_score(
            X_scaled, km.labels_, sample_size=min(SAMPLE_SIZE, len(X_scaled)), random_state=RANDOM_STATE
        )
        rows.append({"method": "kmeans", "k": k, "silhouette": km_sil, "bic": None})

        gmm = GaussianMixture(n_components=k, random_state=RANDOM_STATE, n_init=5).fit(X_scaled)
        gmm_labels = gmm.predict(X_scaled)
        gmm_sil = silhouette_score(
            X_scaled, gmm_labels, sample_size=min(SAMPLE_SIZE, len(X_scaled)), random_state=RANDOM_STATE
        )
        rows.append({"method": "gmm", "k": k, "silhouette": gmm_sil, "bic": gmm.bic(X_scaled)})

    return pd.DataFrame(rows)


def main() -> None:
    feature_sets = {
        "behavioral_core": get_behavioral_core_features(),
        "credit_capacity": get_credit_capacity_features(),
    }
    # behavioral_extended는 behavioral_core와 같은 함수 시그니처를 쓰므로
    # feature_engine.clustering_features.get_behavioral_extended_features()를
    # 그대로 딕셔너리에 추가하면 동일하게 탐색할 수 있다.

    if GAP_PREDICTIONS_PATH.exists():
        predictions = pd.read_csv(GAP_PREDICTIONS_PATH)
        feature_sets["activity_gap"] = get_activity_gap_features(predictions)
    else:
        print(
            f"[activity_gap] 건너뜀 (파일 없음: {GAP_PREDICTIONS_PATH}). "
            "먼저 python src/final/regression_final.py 를 실행하면 이 탐색에 포함됩니다."
        )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    all_results = []

    for name, X in feature_sets.items():
        result = search(X)
        result.insert(0, "feature_set", name)
        best = result.loc[result["silhouette"].idxmax()]
        print(f"\n[{name}] 최적: {best['method']} k={int(best['k'])} Silhouette={best['silhouette']:.4f}")
        all_results.append(result)

    combined = pd.concat(all_results, ignore_index=True)
    combined.to_csv(REPORT_DIR / "clustering_search.csv", index=False)
    print(f"\n결과 저장 위치: {REPORT_DIR / 'clustering_search.csv'}")
    print("\n참고값: behavioral_core k=3 Silhouette 약 0.218, credit_capacity k=2 Silhouette 약 0.469")


if __name__ == "__main__":
    main()

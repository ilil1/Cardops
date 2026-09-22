"""고객 행동 특성을 기준으로 고객군을 찾는 K-means 군집 모델.

실행:
    python src/clustering.py
"""

import os
from pathlib import Path

# 일부 macOS 환경에서 물리 코어 수를 읽지 못할 때 생기는 경고를 방지한다.
os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(os.cpu_count() or 1))
os.environ.setdefault("OMP_NUM_THREADS", str(os.cpu_count() or 1))

import joblib
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler


# 1. 기본 설정
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "processed" / "bankchurners_clean.csv"
MODEL_DIR = PROJECT_ROOT / "outputs" / "models"
REPORT_DIR = PROJECT_ROOT / "outputs" / "reports"

CLUSTER_FEATURES = [
    "Total_Trans_Ct",
    "Avg_Utilization_Ratio",
    "Total_Revolving_Bal",
    "Contacts_Count_12_mon",
    "Total_Relationship_Count",
]
N_CLUSTERS = 3
RANDOM_STATE = 42


def load_data() -> pd.DataFrame:
    """정제된 고객 데이터를 불러온다."""
    return pd.read_csv(DATA_PATH)


def main() -> None:
    """K-means를 학습하고 군집 모델·평가·고객별 군집을 저장한다."""
    df = load_data()
    X = df[CLUSTER_FEATURES]

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = KMeans(
        n_clusters=N_CLUSTERS,
        random_state=RANDOM_STATE,
        n_init=10,
    )
    cluster_labels = model.fit_predict(X_scaled)
    df["Cluster"] = cluster_labels

    # 전체 데이터 계산은 느릴 수 있어 최대 3,000개 표본으로 평가한다.
    score = silhouette_score(
        X_scaled,
        cluster_labels,
        sample_size=min(3000, len(df)),
        random_state=RANDOM_STATE,
    )

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # 예측 시 동일한 변수 순서와 스케일러를 사용하도록 함께 저장한다.
    artifact = {
        "features": CLUSTER_FEATURES,
        "scaler": scaler,
        "model": model,
    }
    joblib.dump(artifact, MODEL_DIR / "clustering_kmeans.joblib")

    cluster_profile = df.groupby("Cluster")[CLUSTER_FEATURES].mean().round(3)
    cluster_profile.insert(0, "Customer_Count", df.groupby("Cluster").size())
    cluster_profile["Churn_Rate"] = (
        df.groupby("Cluster")["Target"].mean().round(4)
    )

    cluster_profile.to_csv(REPORT_DIR / "clustering_profile.csv")
    df[["Cluster", *CLUSTER_FEATURES, "Target"]].to_csv(
        REPORT_DIR / "clustering_assignments.csv",
        index=False,
    )
    pd.DataFrame(
        [
            {
                "N_Clusters": N_CLUSTERS,
                "Silhouette_Score": score,
                "Inertia": model.inertia_,
            }
        ]
    ).to_csv(REPORT_DIR / "clustering_metrics.csv", index=False)

    print("\n[군집 모델 평가]")
    print(f"군집 수: {N_CLUSTERS}")
    print(f"Silhouette Score: {score:.4f}")
    print("\n[군집별 프로파일]")
    print(cluster_profile.to_string())
    print(f"\n모델 저장 위치: {MODEL_DIR / 'clustering_kmeans.joblib'}")
    print(f"결과 저장 위치: {REPORT_DIR}")


if __name__ == "__main__":
    main()

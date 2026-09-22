"""고객 이탈 여부를 예측하는 분류 모델.

실행:
    python src/classification.py
"""

import hashlib
import json
import platform
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
import xgboost
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBClassifier


# 1. 기본 설정
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "processed" / "bankchurners_clean.csv"
MODEL_DIR = PROJECT_ROOT / "outputs" / "models"
REPORT_DIR = PROJECT_ROOT / "outputs" / "reports"

TARGET = "Target"
TEST_SIZE = 0.2
RANDOM_STATE = 42
MANIFEST_PATH = MODEL_DIR / "classification_manifest.json"


def load_data() -> tuple[pd.DataFrame, pd.Series]:
    """정제 데이터를 입력 변수 X와 타깃 y로 분리한다."""
    df = pd.read_csv(DATA_PATH)
    X = df.drop(columns=[TARGET])
    y = df[TARGET]
    return X, y


def build_preprocessor(X: pd.DataFrame) -> ColumnTransformer:
    """수치형은 표준화하고 범주형은 원-핫 인코딩한다."""
    numerical_columns = X.select_dtypes(include="number").columns
    categorical_columns = X.columns.difference(numerical_columns, sort=False)

    return ColumnTransformer(
        transformers=[
            ("num", StandardScaler(), numerical_columns),
            (
                "cat",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                categorical_columns,
            ),
        ]
    )


def evaluate_model(
    name: str,
    dataset: str,
    model: Pipeline,
    X: pd.DataFrame,
    y: pd.Series,
) -> dict[str, float | int | str]:
    """Train 또는 Test 데이터의 주요 분류 성능지표를 계산한다."""
    prediction = model.predict(X)
    probability = model.predict_proba(X)[:, 1]

    return {
        "Model": name,
        "Dataset": dataset,
        "Sample_Count": len(y),
        "Accuracy": accuracy_score(y, prediction),
        "Precision": precision_score(y, prediction, zero_division=0),
        "Recall": recall_score(y, prediction, zero_division=0),
        "F1": f1_score(y, prediction, zero_division=0),
        "ROC_AUC": roc_auc_score(y, probability),
    }


def make_prediction_result(
    name: str,
    model: Pipeline,
    X_test: pd.DataFrame,
    y_test: pd.Series,
) -> pd.DataFrame:
    """혼동행렬과 ROC 곡선에 사용할 테스트 예측 결과를 만든다."""
    prediction = model.predict(X_test)
    probability = model.predict_proba(X_test)[:, 1]

    return pd.DataFrame(
        {
            "Model": name,
            "Actual": y_test.to_numpy(),
            "Predicted": prediction,
            "Churn_Probability": probability,
        }
    )


def file_sha256(path: Path) -> str:
    """파일 내용을 기준으로 SHA-256 해시를 계산한다."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_joblib_atomic(value: object, path: Path) -> None:
    """완전히 저장된 모델만 최종 경로에 보이도록 교체한다."""
    temporary_path = path.with_name(f".{path.name}.tmp")
    joblib.dump(value, temporary_path)
    temporary_path.replace(path)


def save_csv_atomic(data: pd.DataFrame, path: Path) -> None:
    """CSV를 임시 파일에 기록한 뒤 최종 경로로 교체한다."""
    temporary_path = path.with_name(f".{path.name}.tmp")
    data.to_csv(temporary_path, index=False)
    temporary_path.replace(path)


def build_feature_manifest(X: pd.DataFrame) -> list[dict[str, object]]:
    """API 입력 검증에 사용할 변수 타입·범위·범주를 만든다."""
    features: list[dict[str, object]] = []

    for name in X.columns:
        series = X[name]
        if pd.api.types.is_integer_dtype(series):
            feature: dict[str, object] = {
                "name": name,
                "type": "integer",
                "required": True,
                "minimum": int(series.min()),
                "maximum": int(series.max()),
            }
        elif pd.api.types.is_numeric_dtype(series):
            feature = {
                "name": name,
                "type": "number",
                "required": True,
                "minimum": float(series.min()),
                "maximum": float(series.max()),
            }
        else:
            feature = {
                "name": name,
                "type": "string",
                "required": True,
                "allowed_values": sorted(
                    series.dropna().astype(str).unique().tolist()
                ),
            }
        features.append(feature)

    return features


def save_manifest(
    X: pd.DataFrame,
    result_df: pd.DataFrame,
    train_rows: int,
    test_rows: int,
) -> None:
    """학습 결과와 선택 모델의 무결성 정보를 원자적으로 저장한다."""
    test_results = result_df.loc[result_df["Dataset"] == "Test"].copy()
    best_result = test_results.loc[test_results["F1"].idxmax()]
    best_name = str(best_result["Model"])
    best_model_path = MODEL_DIR / f"classification_{best_name}.joblib"

    manifest = {
        "schema_version": 1,
        "task": "binary_classification",
        "target": {
            "name": TARGET,
            "negative_class": {
                "value": 0,
                "label": "Existing Customer",
            },
            "positive_class": {
                "value": 1,
                "label": "Attrited Customer",
            },
        },
        "default_model": {
            "name": best_name,
            "artifact": best_model_path.name,
            "sha256": file_sha256(best_model_path),
            "size_bytes": best_model_path.stat().st_size,
            "decision_threshold": 0.5,
        },
        "dataset": {
            "path": str(DATA_PATH.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "sha256": file_sha256(DATA_PATH),
            "rows": len(X),
            "train_rows": train_rows,
            "test_rows": test_rows,
            "test_size": TEST_SIZE,
            "random_state": RANDOM_STATE,
        },
        "test_metrics": {
            str(row["Model"]): {
                "accuracy": float(row["Accuracy"]),
                "precision": float(row["Precision"]),
                "recall": float(row["Recall"]),
                "f1": float(row["F1"]),
                "roc_auc": float(row["ROC_AUC"]),
            }
            for _, row in test_results.iterrows()
        },
        "features": build_feature_manifest(X),
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
            "xgboost": xgboost.__version__,
            "joblib": joblib.__version__,
        },
        "generated_at": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
    }

    temporary_path = MANIFEST_PATH.with_name(f".{MANIFEST_PATH.name}.tmp")
    temporary_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(MANIFEST_PATH)


def main() -> None:
    """세 분류 모델을 학습·평가하고 모델과 결과표를 저장한다."""
    X, y = load_data()
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=y,
    )

    # 이탈 고객이 적으므로 XGBoost에 불균형 비율을 전달한다.
    scale_pos_weight = (y_train == 0).sum() / (y_train == 1).sum()

    estimators = {
        "logistic_regression": LogisticRegression(
            max_iter=1000,
            class_weight="balanced",
            random_state=RANDOM_STATE,
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=100,
            class_weight="balanced",
            random_state=RANDOM_STATE,
            n_jobs=-1,
        ),
        "xgboost": XGBClassifier(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            scale_pos_weight=scale_pos_weight,
            eval_metric="logloss",
            random_state=RANDOM_STATE,
            n_jobs=-1,
        ),
    }

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    prediction_results = []
    for name, estimator in estimators.items():
        model = Pipeline(
            steps=[
                ("preprocessor", build_preprocessor(X_train)),
                ("model", estimator),
            ]
        )
        model.fit(X_train, y_train)

        results.append(
            evaluate_model(name, "Train", model, X_train, y_train)
        )
        results.append(
            evaluate_model(name, "Test", model, X_test, y_test)
        )
        prediction_results.append(
            make_prediction_result(name, model, X_test, y_test)
        )
        save_joblib_atomic(
            model,
            MODEL_DIR / f"classification_{name}.joblib",
        )

    result_df = pd.DataFrame(results).sort_values(["Model", "Dataset"])
    save_csv_atomic(
        result_df,
        REPORT_DIR / "classification_metrics.csv",
    )
    save_csv_atomic(
        pd.concat(prediction_results, ignore_index=True),
        REPORT_DIR / "classification_predictions.csv",
    )
    save_manifest(
        X,
        result_df,
        train_rows=len(X_train),
        test_rows=len(X_test),
    )

    print("\n[분류 모델 성능]")
    print(result_df.round(4).to_string(index=False))
    print(f"\n모델 저장 위치: {MODEL_DIR}")
    print(f"모델 매니페스트: {MANIFEST_PATH}")
    print(f"결과 저장 위치: {REPORT_DIR / 'classification_metrics.csv'}")


if __name__ == "__main__":
    main()

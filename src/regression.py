"""고객의 최근 12개월 거래건수를 예측하는 회귀 모델.

실행:
    python src/regression.py
"""

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBRegressor


# 1. 기본 설정
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "processed" / "bankchurners_clean.csv"
MODEL_DIR = PROJECT_ROOT / "outputs" / "models"
REPORT_DIR = PROJECT_ROOT / "outputs" / "reports"

TARGET = "Total_Trans_Ct"
EXCLUDED_COLUMNS = ["Target", "Total_Ct_Chng_Q4_Q1"]
TEST_SIZE = 0.2
RANDOM_STATE = 42


def load_data() -> tuple[pd.DataFrame, pd.Series]:
    """정제 데이터에서 회귀 입력 변수와 거래건수 타깃을 분리한다."""
    df = pd.read_csv(DATA_PATH)
    X = df.drop(columns=[TARGET, *EXCLUDED_COLUMNS])
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
    """Train 또는 Test 데이터의 회귀 성능지표를 계산한다."""
    prediction = model.predict(X)

    return {
        "Model": name,
        "Dataset": dataset,
        "Sample_Count": len(y),
        "MAE": mean_absolute_error(y, prediction),
        "RMSE": np.sqrt(mean_squared_error(y, prediction)),
        "R2": r2_score(y, prediction),
    }


def make_prediction_result(
    name: str,
    model: Pipeline,
    X_test: pd.DataFrame,
    y_test: pd.Series,
) -> pd.DataFrame:
    """산점도와 잔차 분석에 사용할 테스트 예측 결과를 만든다."""
    prediction = model.predict(X_test)

    return pd.DataFrame(
        {
            "Model": name,
            "Actual": y_test.to_numpy(),
            "Predicted": prediction,
            "Residual": y_test.to_numpy() - prediction,
        }
    )


def main() -> None:
    """세 회귀 모델을 학습·평가하고 모델과 결과표를 저장한다."""
    X, y = load_data()
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
    )

    estimators = {
        "linear_regression": LinearRegression(),
        "random_forest": RandomForestRegressor(
            n_estimators=100,
            random_state=RANDOM_STATE,
            n_jobs=-1,
        ),
        "xgboost": XGBRegressor(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            objective="reg:squarederror",
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
        joblib.dump(model, MODEL_DIR / f"regression_{name}.joblib")

    result_df = pd.DataFrame(results).sort_values(["Model", "Dataset"])
    result_df.to_csv(REPORT_DIR / "regression_metrics.csv", index=False)
    pd.concat(prediction_results, ignore_index=True).to_csv(
        REPORT_DIR / "regression_predictions.csv",
        index=False,
    )

    print("\n[회귀 모델 성능]")
    print(result_df.round(4).to_string(index=False))
    print(f"\n모델 저장 위치: {MODEL_DIR}")
    print(f"결과 저장 위치: {REPORT_DIR / 'regression_metrics.csv'}")


if __name__ == "__main__":
    main()

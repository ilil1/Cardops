"""분류/회귀 성능 평가와 예측 결과표 생성.

판단이 들어가지 않는 순수 계산 함수만 담는다 — 어떤 지표를 최종 보고에 쓸지,
어떤 모델을 최종으로 고를지 같은 결정은 final/ 각 스크립트의 책임이다.
"""

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)


def evaluate_classification(
    name: str,
    dataset: str,
    model,
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


def evaluate_regression(
    name: str,
    dataset: str,
    model,
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


def make_classification_predictions(
    name: str,
    model,
    X_test: pd.DataFrame,
    y_test: pd.Series,
) -> pd.DataFrame:
    """혼동행렬·ROC 곡선에 쓸 테스트 예측 결과를 만든다."""
    prediction = model.predict(X_test)
    probability = model.predict_proba(X_test)[:, 1]

    return pd.DataFrame(
        {
            "Model": name,
            "Actual": y_test.to_numpy(),
            "Predicted": prediction,
            "Probability": probability,
        }
    )


def make_regression_predictions(
    name: str,
    model,
    X_test: pd.DataFrame,
    y_test: pd.Series,
) -> pd.DataFrame:
    """산점도·잔차 분석에 쓸 테스트 예측 결과를 만든다."""
    prediction = model.predict(X_test)

    return pd.DataFrame(
        {
            "Model": name,
            "Actual": y_test.to_numpy(),
            "Predicted": prediction,
            "Residual": y_test.to_numpy() - prediction,
        }
    )

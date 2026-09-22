"""원본 데이터 로드와 범주형 컬럼 감지.

피처 선택·타깃 분리처럼 판단이 들어간 코드는 feature_engine/에 둔다 — 여기는
"CSV를 그대로 읽는다"와 "범주형 컬럼을 경고 없이 찾는다"는 순수 반복 작업만 담는다.
"""

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .config import DATA_PATH


def load_raw_data() -> pd.DataFrame:
    """정제된 원본 데이터를 그대로 불러온다 (컬럼 선택·타깃 분리 없음)."""
    return pd.read_csv(DATA_PATH)


def get_categorical_columns(df: pd.DataFrame) -> list[str]:
    """범주형 컬럼을 감지한다.

    select_dtypes(include=["object", "category"])만 쓰면, 문자열 컬럼의 실제
    dtype이 "str"인 pandas 버전에서 Pandas4Warning이 발생한다
    (notebooks/05_1clustering.ipynb에서 확인된 문제). "string"까지 포함해 세
    표현 전부를 잡아내면 경고 없이 동작한다(notebooks/04_regression_final.ipynb 방식).
    """
    return df.select_dtypes(include=["object", "string", "category"]).columns.tolist()


def build_standard_preprocessor(X: pd.DataFrame) -> ColumnTransformer:
    """수치형은 표준화하고 범주형은 원-핫 인코딩한다.

    어떤 피처를 쓸지는 판단이라 feature_engine/에 두지만, "주어진 X를 표준
    방식으로 전처리한다"는 기계적 로직이라 여기 하나만 두고 classification_features.py/
    regression_features.py가 build_preprocessor라는 이름으로 재노출해서 쓴다.
    """
    categorical_columns = get_categorical_columns(X)
    numerical_columns = X.columns.difference(categorical_columns, sort=False)

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

"""분류 모델 산출물의 manifest 구조와 검증 규칙을 정의합니다."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class TargetClass(BaseModel):
    """분류 대상의 단일 클래스 값과 사람이 읽을 수 있는 이름입니다."""

    value: int
    label: str = Field(min_length=1)


class TargetSpec(BaseModel):
    """이진 분류 대상과 음성·양성 클래스의 정의입니다."""

    name: str = Field(min_length=1)
    negative_class: TargetClass
    positive_class: TargetClass

    @model_validator(mode="after")
    def validate_distinct_classes(self) -> TargetSpec:
        """음성 클래스와 양성 클래스가 서로 다른 값인지 확인합니다."""
        if self.negative_class.value == self.positive_class.value:
            raise ValueError("Target class values must be different.")
        return self


class DefaultModelSpec(BaseModel):
    """API가 기본으로 적재할 모델 파일과 무결성 정보입니다."""

    name: str = Field(min_length=1)
    artifact: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)
    decision_threshold: float = Field(ge=0.0, le=1.0)


class DatasetSpec(BaseModel):
    """모델 학습에 사용된 데이터셋의 재현성 정보입니다."""

    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rows: int = Field(ge=1)
    train_rows: int = Field(ge=1)
    test_rows: int = Field(ge=1)
    test_size: float = Field(gt=0.0, lt=1.0)
    random_state: int

    @model_validator(mode="after")
    def validate_row_counts(self) -> DatasetSpec:
        """학습·테스트 행 수의 합이 전체 행 수와 일치하는지 확인합니다."""
        if self.train_rows + self.test_rows != self.rows:
            raise ValueError("Train and test rows must add up to total rows.")
        return self


class TestMetrics(BaseModel):
    """테스트 데이터셋에서 측정한 분류 모델 성능 지표입니다."""

    accuracy: float = Field(ge=0.0, le=1.0)
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    f1: float = Field(ge=0.0, le=1.0)
    roc_auc: float = Field(ge=0.0, le=1.0)


class FeatureSpec(BaseModel):
    """모델 입력 특성의 자료형과 허용 범위를 정의합니다."""

    name: str = Field(min_length=1)
    type: Literal["integer", "number", "string"]
    required: bool
    minimum: float | None = None
    maximum: float | None = None
    allowed_values: list[str] | None = None

    @model_validator(mode="after")
    def validate_constraints(self) -> FeatureSpec:
        """문자형과 숫자형 특성에 맞는 제약조건인지 확인합니다."""
        if self.type == "string":
            if not self.allowed_values:
                raise ValueError(
                    "String features must define at least one allowed value."
                )
            if self.minimum is not None or self.maximum is not None:
                raise ValueError(
                    "String features cannot define numeric bounds."
                )
            return self

        if self.minimum is None or self.maximum is None:
            raise ValueError("Numeric features must define both bounds.")
        if self.minimum > self.maximum:
            raise ValueError("Feature minimum cannot exceed maximum.")
        if self.allowed_values is not None:
            raise ValueError(
                "Numeric features cannot define allowed string values."
            )
        return self


class ClassificationManifest(BaseModel):
    """분류 모델 배포에 필요한 전체 메타데이터 계약입니다."""

    schema_version: Literal[1]
    task: Literal["binary_classification"]
    target: TargetSpec
    default_model: DefaultModelSpec
    dataset: DatasetSpec
    test_metrics: dict[str, TestMetrics] = Field(min_length=1)
    features: list[FeatureSpec] = Field(min_length=1)
    runtime: dict[str, str] = Field(min_length=1)
    generated_at: datetime

    @model_validator(mode="after")
    def validate_model_and_features(self) -> ClassificationManifest:
        """모델 이름, 기본 모델, 입력 특성의 일관성을 검증합니다."""
        # 모델 이름은 파일명이나 API 식별자로 안전하게 쓸 수 있는 형식만
        # 허용합니다.
        invalid_model_names = [
            name
            for name in self.test_metrics
            if re.fullmatch(r"[a-z0-9_]+", name) is None
        ]
        if invalid_model_names:
            raise ValueError(
                "Model names may contain only lowercase letters, numbers, "
                "and underscores."
            )

        if self.default_model.name not in self.test_metrics:
            raise ValueError(
                "Default model must have an entry in test_metrics."
            )

        # 중복 특성은 DataFrame 생성 시 컬럼 충돌을 만들 수 있으므로
        # manifest 적재 단계에서 차단합니다.
        feature_names = [feature.name for feature in self.features]
        if len(feature_names) != len(set(feature_names)):
            raise ValueError("Feature names must be unique.")
        return self

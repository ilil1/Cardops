"""선정된 머신러닝 모델의 안전한 적재와 예측 실행을 담당합니다."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from pydantic import ValidationError

from .model_manifest import ClassificationManifest, DefaultModelSpec


class ModelLoadError(RuntimeError):
    """필수 모델 산출물을 안전하게 적재하지 못했을 때 발생합니다."""


class ModelPredictionError(RuntimeError):
    """적재된 모델이 유효한 예측 결과를 만들지 못했을 때 발생합니다."""


class ModelRegistry:
    """FastAPI lifespan 동안 한 번 적재된 모델과 manifest를 관리합니다."""

    def __init__(self, model_dir: Path) -> None:
        """모델 디렉터리와 기본 manifest 경로를 초기화합니다."""
        self.model_dir = model_dir
        self.manifest_path = model_dir / "classification_manifest.json"
        self.manifest: ClassificationManifest | None = None
        self.model: Any | None = None

    @property
    def is_loaded(self) -> bool:
        """예측 가능한 모델 객체가 메모리에 적재되었는지 반환합니다."""
        return self.model is not None

    @property
    def default_model(self) -> DefaultModelSpec:
        """검증된 manifest에서 기본 모델 사양을 반환합니다."""
        if self.manifest is None:
            raise ModelLoadError("The classification manifest is not loaded.")
        return self.manifest.default_model

    def load(self) -> None:
        """모델 파일의 위치·크기·해시를 검증한 뒤 파이프라인을 적재합니다."""
        # 재적재가 실패했을 때 이전 모델을 준비된 상태로 오인하지 않도록
        # 먼저 기존 참조를 초기화합니다.
        self.model = None
        self.manifest = None

        # 학습 코드가 생성한 manifest가 존재해야 모델 버전과 입력 계약을
        # 신뢰할 수 있습니다.
        if not self.manifest_path.is_file():
            raise ModelLoadError(
                f"Model manifest not found: {self.manifest_path}"
            )

        try:
            # Pydantic 모델로 JSON 구조와 각 필드의 제약조건을 검증합니다.
            self.manifest = ClassificationManifest.model_validate_json(
                self.manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError) as exc:
            raise ModelLoadError(
                f"Invalid model manifest: {self.manifest_path}"
            ) from exc

        default_model = self.default_model
        artifact_reference = Path(default_model.artifact)
        # 절대경로나 하위 디렉터리, 상위 경로 이동을 허용하지 않고
        # MODEL_DIR 바로 아래의 단일 파일명만 받습니다.
        if (
            artifact_reference.is_absolute()
            or len(artifact_reference.parts) != 1
            or artifact_reference.name != default_model.artifact
        ):
            raise ModelLoadError(
                "Model artifact must be a file name inside MODEL_DIR."
            )

        model_root = self.model_dir.resolve()
        artifact_path = (model_root / artifact_reference).resolve()
        # 경로를 정규화한 뒤에도 최종 파일이 MODEL_DIR 내부인지 재확인합니다.
        if not artifact_path.is_relative_to(model_root):
            raise ModelLoadError(
                "Model artifact resolves outside the configured MODEL_DIR."
            )
        if not artifact_path.is_file():
            raise ModelLoadError(f"Model artifact not found: {artifact_path}")

        # 파일 크기와 SHA-256을 모두 비교하여 잘못되거나 변조된 산출물을
        # 역직렬화하기 전에 차단합니다.
        if artifact_path.stat().st_size != default_model.size_bytes:
            raise ModelLoadError(
                f"Model artifact size mismatch: {artifact_path}"
            )

        actual_hash = self._sha256(artifact_path)
        if actual_hash != default_model.sha256:
            raise ModelLoadError(
                f"Model artifact hash mismatch: {artifact_path}"
            )

        try:
            # 무결성 검증이 끝난 신뢰 가능한 joblib 산출물만 역직렬화합니다.
            model = joblib.load(artifact_path)
        except Exception as exc:
            raise ModelLoadError(
                f"Unable to load model artifact: {artifact_path}"
            ) from exc

        # 이 API가 사용하는 분류 모델 인터페이스를 적재 시점에 확인합니다.
        if not callable(getattr(model, "predict", None)):
            raise ModelLoadError("Loaded artifact does not support prediction.")
        if not callable(getattr(model, "predict_proba", None)):
            raise ModelLoadError(
                "Loaded classification artifact does not support probabilities."
            )

        # 모든 검증을 통과한 뒤에만 모델을 준비 완료 상태로 공개합니다.
        self.model = model

    def health(self) -> dict[str, Any]:
        """준비 상태 응답에 포함할 모델 식별 정보를 반환합니다."""
        if self.manifest is None:
            raise ModelLoadError("The classification manifest is not loaded.")
        default_model = self.default_model
        return {
            "model_loaded": self.is_loaded,
            "model_name": default_model.name,
            "model_artifact": default_model.artifact,
            "manifest_generated_at": self.manifest.generated_at.isoformat(),
        }

    def predict(self, features: dict[str, Any]) -> dict[str, Any]:
        """검증된 고객 한 명의 이탈 여부와 이탈 확률을 계산합니다."""
        if self.manifest is None or self.model is None:
            raise ModelPredictionError("The classification model is not ready.")

        # 요청 컬럼이 manifest의 특성과 정확히 일치해야 예측을 진행합니다.
        expected_features = [
            feature.name for feature in self.manifest.features
        ]
        if set(features) != set(expected_features):
            raise ModelPredictionError(
                "Prediction fields do not match the model manifest."
            )

        # 학습 당시의 컬럼 순서를 보존하여 단일 행 DataFrame을 구성합니다.
        input_frame = pd.DataFrame(
            [{name: features[name] for name in expected_features}],
            columns=expected_features,
        )
        positive_value = self.manifest.target.positive_class.value
        negative_value = self.manifest.target.negative_class.value

        # 모델의 classes_에서 양성 클래스의 위치를 찾아 해당 확률만 꺼냅니다.
        classes = getattr(self.model, "classes_", None)
        if classes is None:
            raise ModelPredictionError(
                "Loaded model does not expose classification classes."
            )

        try:
            positive_index = list(classes).index(positive_value)
            probabilities = np.asarray(self.model.predict_proba(input_frame))
            churn_probability = float(probabilities[0][positive_index])
        except (IndexError, TypeError, ValueError) as exc:
            raise ModelPredictionError(
                "Loaded model returned invalid probability output."
            ) from exc
        except Exception as exc:
            raise ModelPredictionError("Model prediction failed.") from exc

        if not 0.0 <= churn_probability <= 1.0:
            raise ModelPredictionError(
                "Loaded model returned a probability outside [0, 1]."
            )

        # manifest에 기록된 운영 임계값을 기준으로 최종 클래스를 판정합니다.
        threshold = self.default_model.decision_threshold
        is_attrited = churn_probability >= threshold
        prediction = positive_value if is_attrited else negative_value
        target_class = (
            self.manifest.target.positive_class
            if is_attrited
            else self.manifest.target.negative_class
        )

        return {
            "prediction": prediction,
            "status": target_class.label,
            "churn_probability": churn_probability,
            "decision_threshold": threshold,
            "model_name": self.default_model.name,
            "model_version": self.manifest.generated_at.isoformat(),
        }

    def predict_batch(self, features: pd.DataFrame) -> pd.DataFrame:
        """여러 고객의 이탈 확률을 manifest 컬럼 순서대로 계산합니다.

        온라인 API의 ``predict``와 동일한 검증·양성 클래스 선택 규칙을
        유지하면서, 배치에서는 행 단위 Python 호출을 피하고 모델의 벡터화
        예측을 사용합니다.
        """
        if self.manifest is None or self.model is None:
            raise ModelPredictionError("The classification model is not ready.")

        expected_features = [
            feature.name for feature in self.manifest.features
        ]
        if set(features.columns) != set(expected_features):
            raise ModelPredictionError(
                "Batch prediction fields do not match the model manifest."
            )

        input_frame = features.loc[:, expected_features]
        positive_value = self.manifest.target.positive_class.value
        classes = getattr(self.model, "classes_", None)
        if classes is None:
            raise ModelPredictionError(
                "Loaded model does not expose classification classes."
            )

        try:
            positive_index = list(classes).index(positive_value)
            probabilities = np.asarray(self.model.predict_proba(input_frame))
            churn_probabilities = pd.Series(
                probabilities[:, positive_index],
                index=input_frame.index,
                dtype="float64",
            )
        except (IndexError, TypeError, ValueError) as exc:
            raise ModelPredictionError(
                "Loaded model returned invalid batch probability output."
            ) from exc
        except Exception as exc:
            raise ModelPredictionError("Batch model prediction failed.") from exc

        if not ((churn_probabilities >= 0.0) & (churn_probabilities <= 1.0)).all():
            raise ModelPredictionError(
                "Loaded model returned a probability outside [0, 1]."
            )

        threshold = self.default_model.decision_threshold
        return pd.DataFrame(
            {
                "churn_probability": churn_probabilities,
                "prediction": (churn_probabilities >= threshold).astype(int),
            },
            index=input_frame.index,
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        """대용량 파일도 메모리에 모두 올리지 않고 SHA-256을 계산합니다."""
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

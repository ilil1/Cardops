"""최종 분류 모델을 Docker 배치의 기본 모델로 등록합니다."""

from __future__ import annotations

import hashlib
import json
import platform
from datetime import datetime
from math import ceil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lightgbm
import pandas as pd

from common.config import DATA_PATH, MODEL_DIR, PROJECT_ROOT, RANDOM_STATE, REPORT_DIR


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _create_base_manifest() -> dict:
    """Create the metadata needed when a fresh deployment has no manifest yet.

    The regular local model build creates a complete manifest first. Render's
    deployment build intentionally trains only the final model, so it needs a
    small, data-derived starting manifest on a clean filesystem.
    """
    data = pd.read_csv(DATA_PATH)
    features_frame = data.drop(columns=["Target"])
    feature_specs: list[dict[str, object]] = []

    for name in features_frame.columns:
        series = features_frame[name]
        if pd.api.types.is_integer_dtype(series):
            feature_specs.append(
                {
                    "name": name,
                    "type": "integer",
                    "required": True,
                    "minimum": int(series.min()),
                    "maximum": int(series.max()),
                }
            )
        elif pd.api.types.is_numeric_dtype(series):
            feature_specs.append(
                {
                    "name": name,
                    "type": "number",
                    "required": True,
                    "minimum": float(series.min()),
                    "maximum": float(series.max()),
                }
            )
        else:
            feature_specs.append(
                {
                    "name": name,
                    "type": "string",
                    "required": True,
                    "allowed_values": sorted(
                        series.dropna().astype(str).unique().tolist()
                    ),
                }
            )

    test_rows = ceil(len(data) * 0.2)
    return {
        "schema_version": 1,
        "task": "binary_classification",
        "target": {
            "name": "Target",
            "negative_class": {"value": 0, "label": "Existing Customer"},
            "positive_class": {"value": 1, "label": "Attrited Customer"},
        },
        "dataset": {
            "path": str(DATA_PATH.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "sha256": _sha256(DATA_PATH),
            "rows": len(data),
            "train_rows": len(data) - test_rows,
            "test_rows": test_rows,
            "test_size": 0.2,
            "random_state": RANDOM_STATE,
        },
        "test_metrics": {},
        "features": feature_specs,
        "runtime": {"python": platform.python_version()},
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def update_manifest() -> None:
    """classification_final.py가 만든 모델을 manifest의 기본 모델로 지정합니다."""
    manifest_path = MODEL_DIR / "classification_manifest.json"
    model_path = MODEL_DIR / "classification_lightgbm_final.joblib"
    metrics_path = REPORT_DIR / "classification_final_metrics.csv"

    for path in (model_path, metrics_path):
        if not path.is_file():
            raise FileNotFoundError(f"Required classification artifact not found: {path}")

    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = _create_base_manifest()
        print(f"Classification manifest baseline created: {manifest_path}")
    metrics = pd.read_csv(metrics_path).iloc[0]

    manifest["default_model"] = {
        "name": "lightgbm_final",
        "artifact": model_path.name,
        "sha256": _sha256(model_path),
        "size_bytes": model_path.stat().st_size,
        "decision_threshold": 0.5,
    }
    manifest.setdefault("test_metrics", {})["lightgbm_final"] = {
        "accuracy": float(metrics["Accuracy"]),
        "precision": float(metrics["Precision"]),
        "recall": float(metrics["Recall"]),
        "f1": float(metrics["F1"]),
        "roc_auc": float(metrics["ROC_AUC"]),
    }
    manifest.setdefault("runtime", {})["lightgbm"] = lightgbm.__version__
    manifest["generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")

    temporary_path = manifest_path.with_name(f".{manifest_path.name}.tmp")
    temporary_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(manifest_path)
    print(f"Classification manifest updated: {manifest_path}")


if __name__ == "__main__":
    update_manifest()

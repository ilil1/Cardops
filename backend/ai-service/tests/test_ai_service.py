"""분리된 AI HTTP 경계: 서비스 인증, 입력 검증, 모델 오류, 기존 경로 차단."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from cardops_ai.main import create_app
from cardops_ai.app.face.engine import FaceModelUnavailableError
from cardops_ai.app.model_registry import ModelPredictionError
from cardops_ai.app.schemas import PREDICTION_FIELD_MAP
from test_api import VALID_PREDICTION_PAYLOAD

TOKEN = "test-only-ai-service-token-32-characters"
HEADERS = {"X-Service-Token": TOKEN}


class FakeRegistry:
    def __init__(self, _directory):
        self.is_loaded = False

    def load(self):
        self.is_loaded = True

    def health(self):
        return {"model_loaded": self.is_loaded, "model_name": "fixture", "model_artifact": "fixture.joblib",
                "manifest_generated_at": "2026-01-01T00:00:00Z"}

    def predict(self, features):
        return {"prediction": 0, "status": "Existing Customer", "churn_probability": 0.1,
                "decision_threshold": 0.5, "model_name": "fixture", "model_version": "test"}


@pytest.fixture
def client():
    with TestClient(create_app(registry_factory=FakeRegistry, service_token=TOKEN)) as test_client:
        yield test_client


def model_features():
    return {model: VALID_PREDICTION_PAYLOAD[field] for field, model in PREDICTION_FIELD_MAP.items()}


@pytest.mark.parametrize("path,body", [
    ("/internal/v1/health", None), ("/internal/v1/predict", {"features": model_features()}),
    ("/internal/v1/face/availability", None), ("/internal/v1/face/detect", {"image": "bad"}),
    ("/internal/v1/face/embed", {"images": ["bad"]}),
])
def test_all_internal_routes_require_service_token(client, path, body):
    for headers in [{}, {"X-Service-Token": "wrong"}]:
        result = client.get(path, headers=headers) if body is None else client.post(path, headers=headers, json=body)
        assert result.status_code == 401


def test_prediction_and_health_contract(client):
    assert client.get("/ready").status_code == 200
    assert client.get("/internal/v1/health", headers=HEADERS).json()["model_loaded"] is True
    result = client.post("/internal/v1/predict", headers=HEADERS, json={"features": model_features()})
    assert result.status_code == 200
    assert result.json()["churn_probability"] == 0.1


@pytest.mark.parametrize("change", ["missing", "extra", "invalid_type", "out_of_range"])
def test_prediction_rejects_invalid_features(client, change):
    features = model_features()
    if change == "missing": del features["Customer_Age"]
    if change == "extra": features["future_churn"] = 1
    if change == "invalid_type": features["Customer_Age"] = "45"
    if change == "out_of_range": features["Customer_Age"] = 999
    assert client.post("/internal/v1/predict", headers=HEADERS, json={"features": features}).status_code == 422


def test_model_failure_does_not_expose_internal_details(client, monkeypatch):
    def fail(_features): raise ModelPredictionError("private artifact path")
    monkeypatch.setattr(client.app.state.registry, "predict", fail)
    result = client.post("/internal/v1/predict", headers=HEADERS, json={"features": model_features()})
    assert result.status_code == 503
    assert "private artifact" not in result.text
    assert client.get("/live").status_code == 200


def test_business_routes_are_not_registered(client):
    for path in ["/api/v1/auth/me", "/api/v1/campaigns", "/docs", "/openapi.json"]:
        assert client.get(path).status_code == 404


def test_face_contract_and_single_face_policy(monkeypatch):
    observed = []
    class Engine:
        def is_available(self): return True
        def detect(self, _image): return [object()]
        def embed_image(self, image, *, require_single):
            observed.append(require_single)
            return np.array([0.6, 0.8])
    monkeypatch.setattr("cardops_ai.main.decode_base64_image", lambda value: value)
    with TestClient(create_app(registry_factory=FakeRegistry, service_token=TOKEN,
                               face_engine_factory=Engine)) as client:
        assert client.get("/internal/v1/face/availability", headers=HEADERS).json() == {"available": True}
        assert client.post("/internal/v1/face/detect", headers=HEADERS, json={"image": "test"}).json() == {"face_count": 1}
        result = client.post("/internal/v1/face/embed", headers=HEADERS,
                             json={"images": ["test", "test"], "require_single": False})
        assert result.json() == {"embeddings": [[0.6, 0.8], [0.6, 0.8]]}
        assert observed == [False, False]
        assert client.post("/internal/v1/face/embed", headers=HEADERS, json={"images": []}).status_code == 422


def test_unavailable_face_model_is_503(monkeypatch):
    def missing(): raise FaceModelUnavailableError("missing face model")
    with TestClient(create_app(registry_factory=FakeRegistry, service_token=TOKEN, face_engine_factory=missing)) as client:
        assert client.get("/internal/v1/face/availability", headers=HEADERS).status_code == 503


def test_refuses_to_start_without_a_strong_service_token():
    with pytest.raises(RuntimeError, match="AI_SERVICE_TOKEN"):
        with TestClient(create_app(registry_factory=FakeRegistry, service_token="")):
            pass

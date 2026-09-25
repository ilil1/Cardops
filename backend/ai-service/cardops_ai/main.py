"""Core Service 전용 추론 API. 업무 API와 DB 초기화를 실행하지 않습니다."""

from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .app.config import get_model_dir
from .app.face.engine import (
    FaceAuthError,
    FaceModelUnavailableError,
    decode_base64_image,
    get_face_engine,
)
from .app.model_registry import ModelPredictionError, ModelRegistry
from .app.schemas import PREDICTION_FIELD_MAP, PredictionRequest, PredictionResponse

logger = logging.getLogger(__name__)
Image = Annotated[str, Field(min_length=1, max_length=12_000_000)]


class PredictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    features: dict[str, Any]


class DetectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image: Image


class EmbedInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    images: list[Image] = Field(min_length=1, max_length=50)
    require_single: bool = True


def create_app(*, model_dir: Path | None = None, registry_factory=ModelRegistry,
               face_engine_factory=get_face_engine, service_token: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        token = service_token if service_token is not None else os.getenv("AI_SERVICE_TOKEN", "")
        if len(token) < 32:
            raise RuntimeError("AI_SERVICE_TOKEN must contain at least 32 characters.")
        app.state.service_token = token
        registry = registry_factory(model_dir or get_model_dir())
        registry.load()
        app.state.registry = registry
        # Models run in sync endpoints (thread pool). Serialize use of shared model instances.
        app.state.inference_lock = Lock()
        yield
        app.state.registry = None

    app = FastAPI(title="CardOps AI Service", version="1.0.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    def authorize(request: Request, x_service_token: str | None = Header(default=None)) -> None:
        expected = request.app.state.service_token
        if x_service_token is None or not secrets.compare_digest(x_service_token.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="Invalid service authentication.")

    @app.get("/live")
    def live():
        return {"status": "ok", "service": "cardops-ai-service"}

    @app.get("/ready")
    def ready(request: Request):
        if not request.app.state.registry or not request.app.state.registry.is_loaded:
            raise HTTPException(status_code=503, detail="Model is not ready.")
        return {"status": "ok"}

    @app.exception_handler(FaceAuthError)
    async def face_error(_request: Request, error: FaceAuthError):
        status = 503 if isinstance(error, FaceModelUnavailableError) else 422
        return JSONResponse(status_code=status, content={"detail": str(error)})

    @app.exception_handler(ModelPredictionError)
    async def prediction_error(_request: Request, error: ModelPredictionError):
        logger.error("Model prediction failed", exc_info=error)
        return JSONResponse(status_code=503, content={"detail": "The model could not produce a prediction."})

    internal = APIRouter(prefix="/internal/v1", dependencies=[Depends(authorize)])

    @internal.get("/health")
    def health(request: Request):
        return request.app.state.registry.health()

    @internal.post("/predict", response_model=PredictionResponse)
    def predict(payload: PredictInput, request: Request):
        inverse = {model: field for field, model in PREDICTION_FIELD_MAP.items()}
        if set(payload.features) != set(inverse):
            raise HTTPException(status_code=422, detail="Expected the 19 classification model features.")
        try:
            validated = PredictionRequest.model_validate(
                {inverse[key]: value for key, value in payload.features.items()}, strict=True)
        except ValidationError as error:
            raise HTTPException(status_code=422, detail=error.errors(include_url=False, include_context=False)) from error
        with request.app.state.inference_lock:
            return request.app.state.registry.predict(validated.to_model_input())

    @internal.get("/face/availability")
    def face_availability(request: Request):
        with request.app.state.inference_lock:
            return {"available": face_engine_factory().is_available()}

    @internal.post("/face/detect")
    def face_detect(payload: DetectInput, request: Request):
        with request.app.state.inference_lock:
            return {"face_count": len(face_engine_factory().detect(decode_base64_image(payload.image)))}

    @internal.post("/face/embed")
    def face_embed(payload: EmbedInput, request: Request):
        with request.app.state.inference_lock:
            engine = face_engine_factory()
            return {"embeddings": [engine.embed_image(decode_base64_image(image),
                                  require_single=payload.require_single).tolist() for image in payload.images]}

    app.include_router(internal)
    return app


app = create_app()

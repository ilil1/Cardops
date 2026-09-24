"""Private JSON-lines worker for NestJS model and face inference.

This process has no HTTP listener. NestJS owns request validation, routing,
authentication, and database work; Python only runs the existing joblib/ONNX
artifacts, which cannot be loaded by Node.js.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from backend.app.config import get_model_dir
from backend.app.face.engine import (
    FaceAuthError,
    FaceModelUnavailableError,
    decode_base64_image,
    get_face_engine,
)
from backend.app.model_registry import ModelRegistry


def _send(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _handle(registry: ModelRegistry, operation: str, payload: dict[str, Any]) -> Any:
    if operation == "health":
        return registry.health()
    if operation == "predict":
        return registry.predict(payload["features"])
    if operation == "face_available":
        return get_face_engine().is_available()
    if operation == "face_detect":
        image = decode_base64_image(payload["image"])
        return {"face_count": len(get_face_engine().detect(image))}
    if operation == "face_embed":
        engine = get_face_engine()
        require_single = bool(payload.get("require_single", True))
        return [
            engine.embed_image(decode_base64_image(image), require_single=require_single).tolist()
            for image in payload["images"]
        ]
    raise ValueError("Unknown inference operation.")


def main() -> None:
    registry = ModelRegistry(Path(get_model_dir()))
    try:
        registry.load()
    except Exception as error:
        _send({"ready": False, "error": str(error)})
        raise
    _send({"ready": True, "health": registry.health()})

    for line in sys.stdin:
        request: dict[str, Any] = {}
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("Inference request must be an object.")
            result = _handle(registry, request["op"], request.get("payload") or {})
            _send({"id": request["id"], "ok": True, "result": result})
        except FaceAuthError as error:
            code = "unavailable" if isinstance(error, FaceModelUnavailableError) else "invalid_face"
            _send({"id": request.get("id"), "ok": False, "error": {"code": code, "message": str(error)}})
        except Exception as error:
            # A malformed request must not kill the shared model process.
            _send({"id": request.get("id"), "ok": False, "error": {"code": "inference_failed", "message": str(error)}})


if __name__ == "__main__":
    main()

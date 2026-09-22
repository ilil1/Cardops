"""얼굴 인증 딥러닝 파이프라인 — 검출·정렬·임베딩·1:N 매칭.

구성 (모두 ONNX Runtime CPU):

1. 검출   : SCRFD-500M(det_500m.onnx). 스트라이드 8/16/32 앵커를 디코딩해
            얼굴 박스와 5점 랜드마크(눈2·코·입꼬리2)를 얻습니다.
2. 정렬   : 5점 랜드마크를 ArcFace 표준 좌표에 유사변환으로 맞춰
            112×112 정면화 이미지를 만듭니다. 이 단계가 없으면 같은 사람도
            각도에 따라 임베딩이 크게 흔들립니다.
3. 임베딩 : ArcFace MobileFaceNet(w600k_mbf.onnx) → 512차원, L2 정규화.
4. 매칭   : 정규화 벡터의 내적(=코사인 유사도)으로 1:N 식별.
            임계값과 1·2위 마진 규칙을 함께 써서, 등록자끼리 비슷할 때
            아무나 통과되는 것을 막습니다.

보안 원칙: 임베딩은 반드시 서버가 원본 이미지에서 직접 추출합니다.
클라이언트가 계산한 임베딩을 받으면 벡터 재전송만으로 통과되기 때문입니다.
라이브니스(사진 공격 방어)는 이 데모 범위에 없습니다.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ..config import get_model_dir

# 512-d 임베딩 기준 코사인 유사도 판정값.
# buffalo 계열에서 동일인 쌍은 보통 0.5~0.75, 타인 쌍은 0.3 미만에 분포합니다.
SIMILARITY_THRESHOLD = 0.45
# 1:N 식별에서 1위와 2위의 최소 격차. 등록자가 2명 이상일 때만 적용합니다.
TOP2_MARGIN = 0.05
# 검출 신뢰도·NMS 기준 (InsightFace 기본값).
DETECTION_THRESHOLD = 0.5
NMS_THRESHOLD = 0.4
DETECTION_INPUT_SIZE = (640, 640)
EMBEDDING_DIM = 512

REQUIRED_MODELS = ("det_500m.onnx", "w600k_mbf.onnx")
MANIFEST_NAME = "face_manifest.json"

# ArcFace 학습 시 사용한 112×112 기준 5점 랜드마크 좌표입니다.
ARCFACE_TEMPLATE = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)


class FaceAuthError(Exception):
    """얼굴 인증 파이프라인의 사용자 표시용 오류 기반 클래스입니다."""


class FaceModelUnavailableError(FaceAuthError):
    """모델 파일이 없거나 매니페스트 검증에 실패했습니다."""


class InvalidImageError(FaceAuthError):
    """이미지를 디코딩할 수 없습니다."""


class NoFaceDetectedError(FaceAuthError):
    """이미지에서 얼굴을 찾지 못했습니다."""


class MultipleFacesError(FaceAuthError):
    """등록 이미지에 얼굴이 두 개 이상입니다."""


@dataclass(frozen=True)
class DetectedFace:
    bbox: np.ndarray  # (4,) x1 y1 x2 y2
    score: float
    landmarks: np.ndarray  # (5, 2)


@dataclass(frozen=True)
class MatchResult:
    user_id: int
    similarity: float
    margin: float | None  # 등록자가 1명이면 None


def decode_base64_image(data: str) -> np.ndarray:
    """data URL 또는 순수 base64 문자열을 BGR 이미지로 디코딩합니다."""
    payload = data.split(",", 1)[1] if "," in data else data
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as error:
        raise InvalidImageError("이미지 데이터를 해석할 수 없습니다.") from error
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise InvalidImageError("지원하지 않는 이미지 형식입니다.")
    return image


def _distance2bbox(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    return np.stack(
        [
            points[:, 0] - distance[:, 0],
            points[:, 1] - distance[:, 1],
            points[:, 0] + distance[:, 2],
            points[:, 1] + distance[:, 3],
        ],
        axis=-1,
    )


def _distance2kps(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    coords = []
    for i in range(0, distance.shape[1], 2):
        coords.append(points[:, 0] + distance[:, i])
        coords.append(points[:, 1] + distance[:, i + 1])
    return np.stack(coords, axis=-1)


def _nms(boxes: np.ndarray, scores: np.ndarray, threshold: float) -> list[int]:
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1 + 1)
        h = np.maximum(0.0, yy2 - yy1 + 1)
        overlap = (w * h) / (areas[i] + areas[order[1:]] - w * h)
        order = order[1:][overlap <= threshold]
    return keep


class FaceEngine:
    """ONNX 세션을 지연 로드하고 검출→정렬→임베딩을 수행합니다."""

    def __init__(self, model_dir: Path | None = None) -> None:
        self._model_dir = model_dir or (get_model_dir() / "face")
        self._lock = threading.Lock()
        self._detector = None
        self._embedder = None

    # ---------------------------------------------------------------- 로드
    def _verify_manifest(self) -> None:
        manifest_path = self._model_dir / MANIFEST_NAME
        if not manifest_path.exists():
            raise FaceModelUnavailableError(
                "얼굴 모델 매니페스트가 없습니다. "
                "`python -m backend.scripts.download_face_models`를 먼저 실행하세요."
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for name in REQUIRED_MODELS:
            path = self._model_dir / name
            if not path.exists():
                raise FaceModelUnavailableError(f"얼굴 모델 파일이 없습니다: {name}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            expected = manifest.get("models", {}).get(name, {}).get("sha256")
            if digest != expected:
                raise FaceModelUnavailableError(
                    f"얼굴 모델 해시가 매니페스트와 다릅니다: {name}"
                )

    def _ensure_loaded(self) -> None:
        if self._detector is not None and self._embedder is not None:
            return
        with self._lock:
            if self._detector is not None and self._embedder is not None:
                return
            import onnxruntime as ort

            self._verify_manifest()
            options = ort.SessionOptions()
            options.log_severity_level = 3
            self._detector = ort.InferenceSession(
                str(self._model_dir / "det_500m.onnx"),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
            self._embedder = ort.InferenceSession(
                str(self._model_dir / "w600k_mbf.onnx"),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )

    def is_available(self) -> bool:
        try:
            self._ensure_loaded()
            return True
        except FaceModelUnavailableError:
            return False

    # ---------------------------------------------------------------- 검출
    def detect(self, image_bgr: np.ndarray) -> list[DetectedFace]:
        self._ensure_loaded()
        input_w, input_h = DETECTION_INPUT_SIZE
        img_h, img_w = image_bgr.shape[:2]
        scale = min(input_w / img_w, input_h / img_h)
        resized = cv2.resize(image_bgr, (int(img_w * scale), int(img_h * scale)))
        canvas = np.zeros((input_h, input_w, 3), dtype=np.uint8)
        canvas[: resized.shape[0], : resized.shape[1]] = resized

        blob = cv2.dnn.blobFromImage(
            canvas, 1.0 / 128.0, DETECTION_INPUT_SIZE, (127.5, 127.5, 127.5), swapRB=True
        )
        outputs = self._detector.run(None, {self._detector.get_inputs()[0].name: blob})

        # 출력 9개 = [score, bbox, kps] × 스트라이드(8/16/32), 위치당 앵커 2개.
        strides = (8, 16, 32)
        num_anchors = 2
        all_boxes, all_scores, all_kps = [], [], []
        for idx, stride in enumerate(strides):
            scores = outputs[idx].reshape(-1)
            bbox_preds = outputs[idx + 3].reshape(-1, 4) * stride
            kps_preds = outputs[idx + 6].reshape(-1, 10) * stride

            grid_h, grid_w = input_h // stride, input_w // stride
            centers = np.stack(
                np.meshgrid(np.arange(grid_w), np.arange(grid_h)), axis=-1
            ).astype(np.float32)
            centers = (centers * stride).reshape(-1, 2)
            centers = np.repeat(centers, num_anchors, axis=0)

            mask = scores >= DETECTION_THRESHOLD
            if not mask.any():
                continue
            all_boxes.append(_distance2bbox(centers[mask], bbox_preds[mask]))
            all_scores.append(scores[mask])
            all_kps.append(_distance2kps(centers[mask], kps_preds[mask]))

        if not all_boxes:
            return []
        boxes = np.concatenate(all_boxes) / scale
        scores = np.concatenate(all_scores)
        kps = (np.concatenate(all_kps) / scale).reshape(-1, 5, 2)
        keep = _nms(boxes, scores, NMS_THRESHOLD)
        return [
            DetectedFace(bbox=boxes[i], score=float(scores[i]), landmarks=kps[i])
            for i in keep
        ]

    # ------------------------------------------------------------ 정렬·임베딩
    def _align(self, image_bgr: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
        matrix, _ = cv2.estimateAffinePartial2D(
            landmarks.astype(np.float32), ARCFACE_TEMPLATE, method=cv2.LMEDS
        )
        if matrix is None:
            raise NoFaceDetectedError("얼굴 정렬에 실패했습니다. 정면을 바라봐 주세요.")
        return cv2.warpAffine(image_bgr, matrix, (112, 112), borderValue=0)

    def _embed_aligned(self, aligned_bgr: np.ndarray) -> np.ndarray:
        blob = cv2.dnn.blobFromImage(
            aligned_bgr, 1.0 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True
        )
        embedding = self._embedder.run(
            None, {self._embedder.get_inputs()[0].name: blob}
        )[0].reshape(-1)
        norm = np.linalg.norm(embedding)
        if norm == 0:
            raise NoFaceDetectedError("임베딩 계산에 실패했습니다.")
        return (embedding / norm).astype(np.float32)

    def embed_image(self, image_bgr: np.ndarray, *, require_single: bool) -> np.ndarray:
        """이미지 한 장에서 임베딩 하나를 추출합니다.

        require_single=True(가입·등록)면 얼굴이 정확히 1개여야 합니다 — 옆
        사람이 함께 등록되는 사고를 막습니다. False(로그인)면 가장 큰 얼굴을
        씁니다.
        """
        faces = self.detect(image_bgr)
        if len(faces) == 0:
            raise NoFaceDetectedError(
                "얼굴을 찾지 못했습니다. 카메라를 정면으로 바라봐 주세요."
            )
        if require_single and len(faces) > 1:
            raise MultipleFacesError(
                "이미지에 얼굴이 여러 개 있습니다. 혼자 나온 화면으로 다시 시도해 주세요."
            )
        largest = max(
            faces,
            key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
        )
        return self._embed_aligned(self._align(image_bgr, largest.landmarks))


# ------------------------------------------------------------------ 매칭 로직
def average_embeddings(embeddings: list[np.ndarray]) -> np.ndarray:
    """등록용 다중 프레임 임베딩을 평균 후 재정규화합니다."""
    if not embeddings:
        raise ValueError("embeddings must not be empty")
    mean = np.mean(np.stack(embeddings), axis=0)
    norm = np.linalg.norm(mean)
    if norm == 0:
        raise ValueError("degenerate embedding average")
    return (mean / norm).astype(np.float32)


def identify(
    probe: np.ndarray,
    enrolled: dict[int, np.ndarray],
    *,
    threshold: float = SIMILARITY_THRESHOLD,
    margin: float = TOP2_MARGIN,
) -> MatchResult | None:
    """1:N 식별. 임계값 미달이거나 1·2위 격차가 좁으면 None(거부)입니다."""
    if not enrolled:
        return None
    scored = sorted(
        ((user_id, float(np.dot(probe, emb))) for user_id, emb in enrolled.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    best_id, best_sim = scored[0]
    if best_sim < threshold:
        return None
    if len(scored) >= 2:
        gap = best_sim - scored[1][1]
        if gap < margin:
            return None
        return MatchResult(user_id=best_id, similarity=best_sim, margin=gap)
    return MatchResult(user_id=best_id, similarity=best_sim, margin=None)


_engine: FaceEngine | None = None
_engine_lock = threading.Lock()


def get_face_engine() -> FaceEngine:
    """프로세스 전역 FaceEngine 싱글턴. 테스트에서는 monkeypatch로 대체합니다."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = FaceEngine()
    return _engine

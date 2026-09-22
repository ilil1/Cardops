"""얼굴 인증용 ONNX 모델(buffalo_sc)을 내려받아 모델 디렉터리에 배치합니다.

InsightFace가 공개한 buffalo_sc 팩에서 두 모델을 사용합니다.

- det_500m.onnx  : SCRFD-500M 얼굴 검출기 (5점 랜드마크 동시 출력)
- w600k_mbf.onnx : ArcFace MobileFaceNet 임베딩 (512차원)

backend 컨테이너는 outputs/models를 읽기 전용으로 마운트하므로, 쓰기 가능한
model-builder에서 실행합니다.

    docker compose run --rm model-builder python -m backend.scripts.download_face_models

호스트 venv에서 직접 실행해도 됩니다. 내려받은 뒤 각 파일의 SHA-256을
face_manifest.json에 기록하고, 엔진이 로드 시점에 해시를 재검증해
손상·부분 다운로드를 차단합니다(기존 classification_manifest 패턴과 동일).
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from backend.app.config import get_model_dir

BUFFALO_SC_URL = (
    "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_sc.zip"
)
REQUIRED_MODELS = ("det_500m.onnx", "w600k_mbf.onnx")
MANIFEST_NAME = "face_manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_face_models(target_dir: Path | None = None) -> Path:
    face_dir = (target_dir or get_model_dir() / "face").resolve()
    face_dir.mkdir(parents=True, exist_ok=True)

    missing = [name for name in REQUIRED_MODELS if not (face_dir / name).exists()]
    if missing:
        print(f"다운로드: {BUFFALO_SC_URL}")
        with urlopen(BUFFALO_SC_URL, timeout=120) as response:
            archive_bytes = response.read()
        print(f"수신 완료: {len(archive_bytes) / 1_048_576:.1f} MiB")
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            for member in archive.namelist():
                basename = Path(member).name
                if basename in REQUIRED_MODELS:
                    (face_dir / basename).write_bytes(archive.read(member))
                    print(f"저장: {face_dir / basename}")
    else:
        print("모델 파일이 이미 있어 다운로드를 건너뜁니다.")

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": BUFFALO_SC_URL,
        "models": {
            name: {
                "sha256": _sha256(face_dir / name),
                "size_bytes": (face_dir / name).stat().st_size,
            }
            for name in REQUIRED_MODELS
        },
    }
    manifest_path = face_dir / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"매니페스트 갱신: {manifest_path}")
    return face_dir


if __name__ == "__main__":
    download_face_models()

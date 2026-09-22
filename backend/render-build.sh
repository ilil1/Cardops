#!/bin/sh
set -eu

python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt

# outputs/ is intentionally ignored by Git because model artifacts are generated
# data. Render therefore creates the minimum online classification artifact during
# the build. Local Docker Compose continues to use the existing model-builder.
mkdir -p outputs/models outputs/reports

# Face login needs the InsightFace ONNX files and their checksum manifest at
# runtime. The downloader is idempotent, so existing files are reused.
python -m backend.scripts.download_face_models

if [ "${RENDER_BUILD_MODELS:-true}" = "true" ] && {
    [ ! -f outputs/models/classification_manifest.json ] ||
    [ ! -f outputs/models/classification_lightgbm_final.joblib ] ||
    [ ! -f outputs/models/regression_model.joblib ] ||
    [ ! -f outputs/models/clustering_activity_gap.joblib ];
}; then
    python src/final/classification_final.py
    python src/final/regression_final.py
    python src/final/clustering_final.py
fi

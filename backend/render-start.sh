#!/bin/sh
set -eu

# Ensure face authentication can start even when the Render build cache did
# not retain generated files. The downloader is idempotent and reuses existing
# ONNX files, so this does not download anything on a normal restart.
python -m backend.scripts.download_face_models

python -m backend.app.migration_runner

# Render는 Web Service가 먼저 포트를 열어야 정상 배포로 판단합니다.
# 고객 적재·분석·캠페인 시드는 오래 걸릴 수 있으므로 백그라운드에서 실행하고,
# API 서버는 즉시 시작해 Render의 포트 검사에 응답하도록 합니다.
sh backend/render-seed.sh &

exec uvicorn backend.app.main:app --host 0.0.0.0 --port "${PORT:-8000}"

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend/ai-service:/app
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY backend/ai-service/requirements.txt /app/backend/ai-service/requirements.txt
RUN python -m pip install -r backend/ai-service/requirements.txt
COPY backend/ai-service /app/backend/ai-service
COPY src /app/src
COPY data /app/data
COPY outputs/README.md /app/outputs/README.md
RUN mkdir -p /app/outputs/models /app/outputs/reports

# Compose builds artifacts in model-builder; Render can bake them into this image.
ARG RENDER_BUILD_MODELS=false
RUN if [ "$RENDER_BUILD_MODELS" = "true" ]; then \
      python -m cardops_ai.scripts.download_face_models \
      && python src/final/classification_final.py \
      && python src/final/regression_final.py \
      && python src/final/clustering_final.py; \
    fi

EXPOSE 8001
CMD ["sh", "-c", "exec uvicorn cardops_ai.main:app --host 0.0.0.0 --port ${PORT:-8001}"]

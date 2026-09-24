FROM node:24-bookworm-slim AS nest-build

WORKDIR /app/backend/nest
COPY backend/nest/package.json backend/nest/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY backend/nest/tsconfig*.json ./
COPY backend/nest/src ./src
RUN npm run build

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /app/backend/requirements.txt
RUN python -m pip install -r backend/requirements.txt \
    && mkdir -p /app/outputs/models /app/outputs/reports

COPY --from=nest-build /usr/local/bin/node /usr/local/bin/node
COPY --from=nest-build /app/backend/nest/node_modules /app/backend/nest/node_modules
COPY --from=nest-build /app/backend/nest/dist /app/backend/nest/dist
COPY backend /app/backend
COPY src /app/src
COPY data /app/data
COPY outputs/README.md /app/outputs/README.md

# Render creates ignored model artifacts while building its image. Compose uses
# its existing model-builder service and mounts the completed artifacts instead.
ARG RENDER_BUILD_MODELS=false
RUN if [ "$RENDER_BUILD_MODELS" = "true" ]; then \
      python -m backend.scripts.download_face_models \
      && python src/final/classification_final.py \
      && python src/final/regression_final.py \
      && python src/final/clustering_final.py; \
    fi

EXPOSE 8000
CMD ["sh", "/app/backend/nest/docker-entrypoint.sh"]

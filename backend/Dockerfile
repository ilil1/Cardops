FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . /app/backend

# This image is used by the one-shot model-builder service. The public HTTP
# server is built from backend/nest/Dockerfile.
CMD ["python", "-m", "backend.inference_worker"]

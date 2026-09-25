# AI Service — FastAPI

기존 joblib 분류 모델과 ONNX 얼굴 모델을 적재하고 Core의 요청을 처리합니다. 운영 진입점은 **`cardops_ai.main:app`**입니다.

## API

| 경로 | 역할 |
| --- | --- |
| `GET /live` | 프로세스 생존 |
| `GET /ready` | 분류 모델 준비 상태 |
| `GET /internal/v1/health` | 모델 정보 |
| `POST /internal/v1/predict` | 검증된 19개 고객 특성으로 분류 |
| `GET /internal/v1/face/availability` | 얼굴 모델 사용 가능 여부 |
| `POST /internal/v1/face/detect` | 얼굴 수 검출 |
| `POST /internal/v1/face/embed` | 얼굴 임베딩 생성 |

`/internal/v1/*`에는 `X-Service-Token` 헤더가 필요합니다. 서버와 Core의 `AI_SERVICE_TOKEN`을 같은 32자 이상 값으로 설정합니다. 예측 입력은 `{ "features": { "Customer_Age": 45, ... } }`이며 전체 필드·범위를 서버에서도 검증합니다.

모델은 lifespan에서 한 번 적재하고 파일 해시를 검증합니다. 공유 모델 연산은 잠금으로 직렬화합니다. 학습·전체 고객 분석을 HTTP 요청 안에서 실행하지 않습니다. 사용자 쿠키·회원·캠페인 API는 제공하지 않습니다.

## 호스트 실행

저장소 루트에서 실행합니다. `.env`와 `outputs/models/`를 먼저 준비합니다.

```bash
python -m pip install -r backend/ai-service/requirements.txt
export PYTHONPATH="$PWD/backend/ai-service:$PWD${PYTHONPATH:+:$PYTHONPATH}"
python -m cardops_ai.app.migration_runner
uvicorn cardops_ai.main:app --host 127.0.0.1 --port 8001
```

마이그레이션은 별도 작업입니다. AI 서버 시작은 DB에 접근하지 않습니다. 원본 고객과 분석 결과 적재도 별도로 실행합니다.

```bash
python -m cardops_ai.scripts.import_customers
python -m cardops_ai.scripts.run_analysis_batch
```

기존 `backend.app.*`·`backend.scripts.*` 명령은 `cardops_ai.app.*`·`cardops_ai.scripts.*`로 바뀌었습니다. DB 테이블과 Alembic revision은 유지됩니다. `app/legacy_main.py`는 이전 API 비교 테스트용이며 운영 진입점으로 실행하지 않습니다.

## 테스트

```bash
python -m pip install -r backend/ai-service/requirements-dev.txt
python -m pytest backend/ai-service/tests -q
```

AI HTTP 테스트와 대부분의 Python 테스트는 임시 모델·SQLite DB를 사용합니다. `test_analytics_service.py`는 `DATABASE_URL`의 적재된 DB를 읽는 선택적 통합 테스트입니다. 호스트 DB 접근을 제외하려면 `DATABASE_URL='' python -m pytest backend/ai-service/tests -q`로 실행합니다. 실제 학습 모델의 성능 검증과는 별개입니다.

이전 Python 업무 API 비교 테스트에는 로그인 제한 구현과 테스트의 불일치, 테스트 간 공유 계정·쿠키 의존성이 남아 있습니다. [검증 결과와 제한](../../docs/backend_service_refactor.md)에 기록했습니다. 현재 운영 진입점은 이 이전 API를 등록하지 않으며, 새 AI HTTP 계약 검증은 `python -m pytest backend/ai-service/tests/test_ai_service.py -q`로 독립 실행할 수 있습니다.

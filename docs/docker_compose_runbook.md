# Docker Compose 실행 가이드

저장소 루트에서 실행합니다. [백엔드 구조](../backend/README.md)를 함께 참고하세요.

## 서비스

| 서비스 | 역할 |
| --- | --- |
| `mysql` | 업무·분석 DB, 기존 `cardops_mysql_data` 볼륨 사용 |
| `model-builder` | 얼굴·분류·회귀·군집 모델 준비 후 종료 |
| `db-init` | Alembic 마이그레이션·선택적 테스트 계정 생성 후 종료 |
| `core-service` | NestJS 업무 API, 호스트 8000 |
| `ai-service` | FastAPI 추론, 내부 8001, 호스트 포트 공개 안 함 |
| `frontend` | React/Vite, 호스트 5173 |
| `jobs` | `tools` 프로필의 수동 적재·분석 CLI |

Core는 `db-init` 성공 후, AI는 `model-builder` 성공 후 시작합니다. Core 컨테이너에는 Python이 없습니다. AI 웹 프로세스는 DB에 접속하지 않습니다.

## 처음 실행

```bash
cp .env.example .env
```

`.env`의 `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD`, `JWT_SECRET`, **`AI_SERVICE_TOKEN`**을 설정합니다. JWT와 AI 토큰은 서로 다른 32자 이상 임의 문자열로 지정합니다. 로컬 시연 계정이 필요하면 `ALLOW_TEST_USER_SEEDING=true`와 `TEST_*_PASSWORD` 네 값을 설정합니다. 비밀번호는 12자 이상이어야 합니다.

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps -a
docker compose logs --tail 100 core-service ai-service db-init model-builder
curl http://localhost:8000/live
curl http://localhost:8000/ready
```

`db-init`과 `model-builder`의 `Exited (0)`은 정상 완료입니다. `/ready`는 AI까지 호출하므로 모델 준비 중에는 실패할 수 있습니다. 프런트엔드 프록시 대상은 `http://core-service:8000`입니다.

## 고객 적재·분석

```bash
docker compose run --rm jobs python -m cardops_ai.scripts.import_customers
docker compose run --rm jobs python -m cardops_ai.scripts.run_analysis_batch
```

재분석이 필요한 경우 배치 명령에 `--force`를 사용합니다. `jobs`는 AI와 같은 Python 이미지로 실행되며 DB·데이터·모델 볼륨을 받습니다. 합성 고객 생성·시연 캠페인 역시 같은 `jobs`에서 실행합니다. 기존의 `docker compose exec backend python ...` 명령은 사용하지 않습니다.

## 모델 재생성

```bash
FORCE_MODEL_REBUILD=true docker compose run --rm model-builder
docker compose restart ai-service
```

모델은 호스트 `outputs/models/`에 남습니다. 운영 중 산출물을 교체할 때는 동시 접근을 피하고 AI를 재시작합니다. 기존 서비스는 BankChurners 모델을 사용하며 Synchrony 실험 결과를 자동 배포하지 않습니다.

## 기존 구성에서 전환

새 `.env.example`의 AI 설정을 기존 `.env`에 추가한 뒤 다음을 실행합니다.

```bash
docker compose up -d --build --remove-orphans
```

이전 `backend` 컨테이너를 정리하고 새 서비스를 시작합니다. DB 볼륨 이름과 마이그레이션 이력은 유지합니다. 데이터 보존이 필요하면 `docker compose down -v`를 실행하지 마세요.

일반 중지는 `docker compose down`입니다. 서비스별 로그는 `docker compose logs -f core-service` 또는 `ai-service`로 확인합니다.

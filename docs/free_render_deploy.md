# Render 배포 — Core·AI 분리

[`render.yaml`](../render.yaml)은 `cardops-frontend` Static Site, `cardops-backend` NestJS Web Service, `cardops-ai` FastAPI Web Service를 정의합니다. 기존 공개 백엔드 이름을 유지합니다.

## 연결과 환경변수

- **Core**: `DATABASE_URL`, `JWT_SECRET`, `AUTH_COOKIE_SECURE=true`, `CORS_ORIGINS`를 설정합니다.
- **AI**: `AI_SERVICE_TOKEN`을 생성하고 모델을 이미지 빌드 단계에서 준비합니다. 업무 DB·JWT 환경변수는 필요하지 않습니다.
- **서비스 연결**: Core의 `AI_SERVICE_URL`은 AI의 `RENDER_EXTERNAL_URL`, 토큰은 AI의 `AI_SERVICE_TOKEN`에서 참조합니다.
- **Frontend**: `VITE_API_BASE_URL`은 Core의 HTTPS 주소로 설정합니다. AI 주소를 프런트엔드에 전달하지 않습니다.

무료 Render Web Service는 private network의 요청을 받을 수 없어 이 설정은 **HTTPS + 서비스 토큰**을 사용합니다. 유료 Private Service로 바꾸는 경우에는 Core의 AI URL도 내부 주소로 변경할 수 있습니다. [Render 공식 네트워크 문서](https://render.com/docs/private-network), [Blueprint 변수 참조](https://render.com/docs/blueprint-spec#referencing-service-properties)

## DB 준비

스키마 변경은 기존 Alembic으로만 관리합니다. Core와 AI 웹 서비스는 시작 시 마이그레이션을 실행하지 않습니다. 새로운 DB 또는 새 revision이 있는 배포에서는 별도 Python 작업으로 먼저 실행합니다.

```bash
# 저장소 루트, 대상 DATABASE_URL을 설정한 별도 셸/작업 환경에서
export PYTHONPATH="$PWD/backend/ai-service:$PWD${PYTHONPATH:+:$PYTHONPATH}"
python -m pip install -r backend/ai-service/requirements.txt
python -m cardops_ai.app.migration_runner
```

`DATABASE_URL`은 `mysql+pymysql://<user>:<password>@<host>:<port>/<database>` 형식과 DB에서 요구하는 TLS 옵션을 사용합니다. 새 데이터 적재·분석·시연 시드는 명시적인 별도 작업입니다. `POC_SEED_ON_START`로 웹 서버 시작마다 시드하던 방식은 현재 배포 진입점에서 실행되지 않습니다.

## 기존 배포에서 전환 순서

1. 현재 DB와 모델 산출물의 백업·revision을 확인합니다. 이번 구조 변경 자체에는 새 DB revision이 없습니다.
2. Blueprint를 동기화하여 `cardops-ai`를 만들고 모델 빌드와 `/ready` 성공을 확인합니다.
3. 기존 `cardops-backend`의 Dockerfile 경로를 `backend/core-service/Dockerfile`로 적용하고 AI URL·토큰 참조를 확인합니다. 기존 JWT·DB·CORS 값은 유지합니다.
4. Core의 `/live`, `/ready`, 로그인·고객 조회·예측을 확인합니다.

Core의 Render health check는 `/live`를 사용합니다. 모델까지 포함한 상태는 `/ready`에서 확인하며, AI 장애가 Core 재시작을 유발하지 않습니다. AI 무료 인스턴스가 비활성 상태였다면 초기 모델 요청이 60초 제한 시간을 넘겨 503이 될 수 있습니다. 필요하면 `AI_SERVICE_TIMEOUT_MS`를 조정합니다.

현재 저장소에 GitHub Actions workflow는 없습니다. 자동 배포 여부와 브랜치는 Render Git 연동 설정에서 관리합니다. YAML 수정만으로 실제 운영 환경이 전환되었다고 볼 수는 없습니다.

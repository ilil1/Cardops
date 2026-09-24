# CardOps 백엔드 (NestJS)

HTTP API와 인증·캠페인·분석 조회 업무 로직은 `backend/nest/`의 NestJS 앱이 담당합니다. Python은 기존 `joblib`/ONNX 모델 추론, 전체 고객 분석 배치, Alembic 마이그레이션과 데이터 시드에 사용합니다. 두 런타임은 같은 컨테이너 안에서 통신하며 Python 프로세스는 외부 포트를 열지 않습니다.

## 구조

```text
backend/
├── nest/
│   ├── src/
│   │   ├── auth/          # 계정, 쿠키 인증, 얼굴 가입·로그인
│   │   ├── campaigns/     # 캠페인, 대상, 일괄 타기팅, 성과
│   │   ├── read-apis/     # 고객 인사이트, 분석, 모델 배치 조회
│   │   ├── database/      # MySQL/TiDB 연결과 트랜잭션
│   │   └── inference/     # Python 추론 프로세스와 예측 API
│   ├── Dockerfile
│   └── package.json
├── inference_worker.py  # JSON Lines 기반 Python 추론 전용 프로세스
├── app/                 # Python 모델·ORM·배치 코드와 이전 HTTP 구현
├── migrations/          # 기존 Alembic 이력 (데이터 보존)
└── scripts/             # 적재·분석·시드 CLI
```

기존 `backend/app/main.py` 및 `backend/app/api/`는 이전 FastAPI 구현을 비교할 수 있도록 남겨두었으며, Compose와 Render에서 실행하지 않습니다. 신규 API 수정은 `backend/nest/src/`에서 합니다.

## 실행

프로젝트 루트에서 `.env.example`을 `.env`로 복사하고 `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD`, 32자 이상의 `JWT_SECRET`을 설정합니다.

```bash
docker compose up -d --build
docker compose ps -a
curl http://127.0.0.1:8000/live
curl http://127.0.0.1:8000/ready
```

`model-builder`가 모델을 만들고 종료하면 NestJS 백엔드가 시작됩니다. 백엔드 컨테이너는 Alembic 마이그레이션과 선택적 로컬 계정 시드를 실행한 뒤 Node.js 서버와 Python 추론 프로세스를 기동합니다. `/ready`는 모델 로드 상태를 반환합니다. 모델 무결성 검증에 실패하면 백엔드 시작도 실패합니다.

개발 중 TypeScript 검증과 테스트:

```bash
cd backend/nest
npm ci
npm run typecheck
npm test
npm run build
```

호스트에서 `npm run dev`를 실행할 때는 Python 3.13 환경에 `backend/requirements.txt`를 설치하고, 루트 `.env`의 `DATABASE_URL`이 호스트 MySQL 주소를 가리키도록 합니다. `PYTHON_EXECUTABLE`로 Python 실행 파일을 지정할 수 있습니다. Docker Compose에서는 이 설정을 자동으로 제공합니다.

## API와 호환성

- HTTP 포트: `8000`
- API 경로: 기존 `/api/v1/*` 유지
- 상태: `/live`, `/ready`
- 문서: `/docs`, `/redoc`, `/openapi.json`
- 인증: `cardops_access_token` HttpOnly JWT 쿠키, 기존 역할 및 만료 시간 유지
- 오류: 프런트엔드가 사용하는 `{ "detail": ... }` 응답 유지
- DB: 기존 테이블과 Alembic revision 유지, `DATABASE_URL`의 `mysql+pymysql://` 및 `mysql://` 허용

NestJS는 기존 46개 HTTP 경로를 등록합니다. Python 추론 프로세스는 모델을 한 번 적재해 예측과 얼굴 검출·임베딩 요청을 처리합니다. 원본 이미지와 임베딩은 HTTP로 별도 서비스에 전달되지 않습니다.

프런트엔드는 기존 상대 URL과 `credentials: include`를 그대로 사용합니다. 전체 고객 분석 배치는 계속 다음 명령으로 실행합니다.

```bash
docker compose exec backend python -m backend.scripts.import_customers
docker compose exec backend python -m backend.scripts.run_analysis_batch
```

## 배포

`compose.yaml`은 NestJS 백엔드 이미지와 기존 Python `model-builder` 이미지를 각각 빌드합니다. `render.yaml`은 NestJS Docker 이미지를 빌드하며, Git에 포함되지 않는 분류·회귀·군집·얼굴 모델을 이미지 빌드 중 생성합니다. Render의 기존 `DATABASE_URL`, `JWT_SECRET`, `CORS_ORIGINS`, `AUTH_COOKIE_SECURE` 환경변수를 계속 사용합니다.

## 검증 범위

NestJS TypeScript 빌드 및 업무 규칙 단위 테스트가 포함됩니다. 기존 `backend/tests/`는 이전 Python API 구현을 검증하는 참고 테스트입니다. DB를 사용하는 양쪽 구현의 전체 응답 동등성은 별도의 통합 테스트로 검증해야 합니다.

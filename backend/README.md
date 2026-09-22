# FastAPI 백엔드

신용카드 고객 이탈 분류 모델을 한 번 로드하고, 고객 데이터를 받아 이탈 여부와
확률을 반환하는 FastAPI 백엔드입니다.

## 주요 동작

- FastAPI `lifespan`에서 선택된 모델을 프로세스당 한 번 로드
- `@asynccontextmanager`와 `AsyncGenerator[None, None]`으로 모델 생명주기 관리
- `classification_manifest.json`의 전체 구조 검증
- 모델 파일 크기와 SHA-256 검증
- `MODEL_DIR` 밖의 모델 파일 접근 차단
- 고객 입력값 19개의 타입, 범위, 범주 검증
- XGBoost Pipeline을 이용한 고객 이탈 확률 계산
- Liveness와 Readiness 상태 확인 분리
- SQLAlchemy와 MySQL을 이용한 사용자 계정 저장
- Alembic 기반 DB 스키마 버전 관리와 기존 회원 데이터 보존 migration
- 고객 ID·19개 특성과 분석·캠페인 이력을 저장할 업무 테이블
- 분류·회귀·군집 모델을 실행해 `model_runs`와 `customer_insights`에 저장하는 배치
- Argon2 비밀번호 해시와 HttpOnly JWT 인증 쿠키
- 회원가입, 로그인, 현재 사용자 조회, 로그아웃 API
- 분석 세그먼트 기반 캠페인 일괄 타기팅 preview·실행·취소·재실행
- 한국어 설명이 포함된 Swagger UI와 OpenAPI 문서 제공

현재 백엔드는 고객 한 명의 특성 19개를 직접 받아 이탈 여부를 예측하는
Prediction API, 팀 계정 인증 API, customer_insights 조회·이력 API, 최신 모델
배치 상태 API, 캠페인 대상 업무 API와 세그먼트 일괄 타기팅 API를 제공합니다. 별도의 CLI 배치는 전체
고객을 분석해 결과를 MySQL에 저장하며, 대시보드는 이 결과를 읽어 고객 분석과
캠페인 처리 큐를 제공합니다. 모델 성능 Streamlit 화면은 별도 도구로 유지하며
React 대시보드에 통합하지 않습니다.

## 백엔드 파일 구조

```text
backend/
├── __init__.py
├── app/
│   ├── __init__.py
│   ├── api/
│   │   ├── dependencies.py
│   │   ├── router.py
│   │   └── routes/
│   │       ├── auth.py
│   │       ├── bulk_targeting.py
│   │       ├── campaigns.py
│   │       ├── performance.py
│   │       ├── customers.py
│   │       ├── insights.py
│   │       ├── model_runs.py
│   │       ├── predictions.py
│   │       └── system.py
│   ├── analysis_batch.py
│   ├── config.py
│   ├── customer_import.py
│   ├── database.py
│   ├── enums.py
│   ├── main.py
│   ├── migration_runner.py
│   ├── model_manifest.py
│   ├── model_registry.py
│   ├── models.py
│   ├── schemas.py
│   └── services/
│       ├── bulk_targeting_service.py
│       ├── campaign_service.py
│       ├── insight_service.py
│       └── model_run_service.py
├── migrations/
│   ├── env.py
│   └── versions/
├── scripts/
│   ├── import_customers.py
│   ├── run_analysis_batch.py
│   └── seed_test_users.py
├── alembic.ini
├── tests/
│   ├── test_api.py
│   ├── test_bulk_targeting.py
│   ├── test_performance.py
│   └── test_analysis_batch.py
├── README.md
├── requirements.txt
└── requirements-dev.txt
```

| 파일 | 책임 |
|---|---|
| `backend/app/main.py` | FastAPI 앱 생성과 lifespan, DB·모델 초기화 |
| `backend/app/api/router.py` | 기능별 API router 조합 |
| `backend/app/api/dependencies.py` | 모델 registry 등 공통 요청 의존성 |
| `backend/app/api/routes/auth.py` | 회원가입·로그인·로그아웃, 팀 계정 조회·관리, Argon2 해시, JWT 쿠키 검증 |
| `backend/app/api/routes/campaigns.py` | 캠페인 CRUD·대상 조회·등록·상태 변경·이벤트 이력과 역할 제한 |
| `backend/app/api/routes/bulk_targeting.py` | 세그먼트 일괄 타기팅 미리보기·실행·취소·재실행 API |
| `backend/app/api/routes/performance.py` | 캠페인·세그먼트·담당자별 성과와 A/B 증분효과 조회 API |
| `backend/app/api/routes/customers.py` | 관리자 전용 수신 거부 상태 변경 API |
| `backend/app/api/routes/system.py` | liveness·readiness 상태 API |
| `backend/app/api/routes/predictions.py` | 온라인 고객 이탈 예측 API |
| `backend/app/api/routes/insights.py` | customer_insights 최신 결과·분석 이력 API |
| `backend/app/api/routes/model_runs.py` | 최신 성공 모델 배치와 모델 버전 조회 API |
| `backend/app/config.py` | 앱 이름·버전, 프로젝트 경로, 모델·DB·인증 설정 관리 |
| `backend/app/database.py` | SQLAlchemy 엔진·세션과 migration 적용 여부 검증 |
| `backend/app/models.py` | 사용자·고객·분석·캠페인 SQLAlchemy 모델 |
| `backend/app/migration_runner.py` | 기존 users 기준선 처리와 Alembic upgrade 실행 |
| `backend/app/customer_import.py` | `CLIENTNUM`과 고객 특성 19개의 검증·upsert |
| `backend/app/analysis_batch.py` | 세 모델 실행, 위험도·액션 생성, 분석 결과 저장 |
| `backend/app/services/campaign_service.py` | 캠페인 생명주기, 대상 상태 전이, 담당자 역할, 중복 접촉, 서버 집계 규칙 |
| `backend/app/services/bulk_targeting_service.py` | 최신 인사이트 기반 세그먼트 규칙, 제외 정책, 배치 실행·취소·재실행 |
| `backend/app/services/performance_service.py` | 전환율·유지율·증분효과·비용·ROI 서버 집계 |
| `backend/app/services/insight_service.py` | 최신 스냅샷 선택, 이력, 필터·페이지네이션 조회 규칙 |
| `backend/app/services/model_run_service.py` | 모델 task별 최신 성공 배치 선택 규칙 |
| `backend/migrations/` | 버전별 DB 스키마 변경 이력 |
| `backend/scripts/import_customers.py` | 원본 고객 CSV 적재 명령 |
| `backend/scripts/run_analysis_batch.py` | 전체 고객 모델 분석 배치 명령 |
| `backend/scripts/seed_test_users.py` | 로컬 역할별 테스트 계정 생성·갱신 명령 |
| `backend/scripts/seed_demo_campaign.py` | 로컬 시연용 합성 시계열·A/B 캠페인 성과 생성 명령 |
| `backend/app/schemas.py` | 요청·응답 Pydantic Schema와 API 필드명 변환 |
| `backend/app/model_manifest.py` | 모델 manifest 구조와 데이터 일관성 검증 |
| `backend/app/model_registry.py` | 모델 파일 무결성 확인, 모델 적재, 예측 실행 |
| `backend/tests/test_analysis_batch.py` | 회귀 입력 계약과 위험도·액션 규칙 검증 |
| `backend/tests/test_api.py` | 임시 가짜 모델로 API와 모델 보안 검증 |
| `backend/tests/test_bulk_targeting.py` | 세그먼트 제외 규칙과 일괄 타기팅 생명주기 검증 |
| `backend/requirements.txt` | 서버 실행과 모델 추론에 필요한 운영 의존성 |
| `backend/requirements-dev.txt` | 운영 의존성과 pytest 등 개발·테스트 의존성 |

### 파일을 나눈 이유

`main.py`는 FastAPI 생명주기와 앱 조립만 담당합니다. HTTP 경로는
`api/routes/`에, 공통 의존성은 `api/dependencies.py`에, 고객 분석 조회 규칙은
`services/insight_service.py`에 분리했습니다. 모델 파일을 읽고 예측하는 로직은
`model_registry.py`, 데이터 형식 검증은 `schemas.py`와 `model_manifest.py`,
환경에 따라 달라지는 경로는 `config.py`가 담당합니다.

따라서 API 입력 형식이 바뀌면 `schemas.py`, 모델 manifest 규격이 바뀌면
`model_manifest.py`, 모델 적재나 추론 방식이 바뀌면 `model_registry.py`,
분석 목록의 필터·정렬 정책이 바뀌면 `services/insight_service.py`를 중심으로
수정할 수 있습니다.

## 서버 시작과 요청 처리 흐름

### 서버 시작

```text
create_app()
  → Docker entrypoint에서 Alembic migration 적용
  → FastAPI lifespan 진입
  → DB 스키마 revision·필수 테이블 확인
  → MODEL_DIR 결정
  → classification_manifest.json 검증
  → 모델 파일 경로·크기·SHA-256 검증
  → joblib 모델 적재
  → app.state.model_registry에 모델 보관
  → API 요청 수신 시작
```

`lifespan()`은 `yield`를 사용하는 비동기 제너레이터입니다.

```python
@asynccontextmanager
async def lifespan(
    application: FastAPI,
) -> AsyncGenerator[None, None]:
    ...
    yield
    ...
```

- `yield` 이전: 서버가 요청을 받기 전에 모델을 한 번 적재
- `yield` 구간: FastAPI가 요청 처리
- `yield` 이후: 서버 종료 시 공유 모델 참조 해제

`@asynccontextmanager` 자체는 사용 중이며 제거하면 안 됩니다. Pylance의 최신
타입 검사 규칙에 맞춰 반환 타입은 `AsyncIterator`가 아닌
`AsyncGenerator[None, None]`으로 선언합니다.

### 예측 요청

```text
POST /api/v1/predictions
  → PredictionRequest가 타입·범위·범주 검증
  → snake_case API 필드를 학습 데이터 컬럼명으로 변환
  → Depends가 준비된 ModelRegistry 주입
  → manifest 순서대로 1행 DataFrame 생성
  → predict_proba()로 이탈 확률 계산
  → manifest의 decision_threshold로 최종 상태 판정
  → PredictionResponse 반환
```

모델은 요청마다 다시 읽지 않습니다. 같은 서버 프로세스의 모든 예측 요청이
lifespan에서 적재한 모델 하나를 공유합니다.

## 모델 학습

프로젝트 루트에서 분류 학습 코드를 먼저 실행합니다.

```powershell
.\project_venv\Scripts\python.exe src\classification.py
```

학습이 정상적으로 끝나면 다음 파일이 생성됩니다.

```text
outputs/models/classification_logistic_regression.joblib
outputs/models/classification_random_forest.joblib
outputs/models/classification_xgboost.joblib
outputs/models/classification_manifest.json
outputs/reports/classification_metrics.csv
outputs/reports/classification_predictions.csv
```

`classification_manifest.json`에는 다음 정보가 기록됩니다.

- Test F1 점수가 가장 높은 기본 서비스 모델
- 모델 파일명, 크기, SHA-256
- 분류 임계값
- 입력 변수의 타입, 범위, 범주
- 모델별 Test 성능
- 학습 데이터 행 수와 SHA-256
- Python 및 ML 라이브러리 버전

모델을 다시 학습하면 모델 산출물과 매니페스트를 함께 갱신해야 합니다.

## 가상환경과 의존성

프로젝트 루트에서 가상환경을 만들고 운영 의존성을 설치합니다.

```powershell
py -m venv project_venv
.\project_venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

모델을 저장한 환경과 API에서 모델을 불러오는 환경의 ML 라이브러리 버전은
같아야 합니다. 검증한 버전은 `backend/requirements.txt`에 고정되어 있습니다.

의존성 파일은 용도별로 나뉩니다.

| 파일 | 사용 환경 | 내용 |
|---|---|---|
| `requirements.txt` | 운영, 개발 | FastAPI 서버 및 ML 모델 로드에 필요한 패키지 |
| `requirements-dev.txt` | 로컬 개발, CI | 운영 패키지 전체와 테스트 도구 |

운영 환경에는 다음 명령으로 운영 의존성만 설치합니다.

```powershell
.\project_venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

로컬 개발과 CI에는 테스트 의존성까지 설치합니다.

```powershell
.\project_venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
```

`requirements-dev.txt`는 Starlette `TestClient`가 사용하는 `httpx2`와
테스트 실행기 `pytest`를 운영 의존성 위에 추가합니다.

서버 실행이나 모델 추론에 필요하면 `requirements.txt`에 추가하고, 테스트나
개발 과정에서만 필요하면 `requirements-dev.txt`에 추가합니다.

## 개발 서버 실행

프로젝트 루트에서 실행합니다.

```powershell
.\project_venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

기본 주소는 `http://127.0.0.1:8000`입니다. `--reload`는 개발 환경에서만
사용합니다.

### React 개발 서버 연결

현재 백엔드에는 `CORSMiddleware`가 없습니다. React 개발 서버가 다른
Origin에서 실행될 때는 Vite 개발 프록시를 사용하는 것을 권장합니다.

```ts
// frontend/vite.config.ts
export default defineConfig({
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/live": "http://127.0.0.1:8000",
      "/ready": "http://127.0.0.1:8000",
    },
  },
});
```

React에서는 서버 주소를 직접 작성하지 않고 상대 경로로 호출합니다.

```ts
await fetch("/api/v1/predictions", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload),
});
```

운영 환경에서는 React 정적 파일과 `/api` Reverse Proxy를 같은 Origin으로
제공하는 구성을 권장합니다. 서로 다른 Origin을 반드시 사용해야 하는 경우에는
허용할 React 주소를 명시한 CORS 설정을 백엔드에 추가해야 합니다.

## API 목록

| Method | Path | 설명 |
|---|---|---|
| `GET` | `/live` | API 프로세스가 실행 중인지 확인 |
| `GET` | `/ready` | 모델이 정상적으로 로드되었는지 확인 |
| `POST` | `/api/v1/auth/signup` | 팀 계정 회원가입 |
| `POST` | `/api/v1/auth/login` | 로그인 및 HttpOnly 인증 쿠키 발급 |
| `GET` | `/api/v1/auth/me` | 현재 로그인 사용자 조회 |
| `GET` | `/api/v1/auth/users` | 활성 팀 계정 조회, 비활성 포함은 관리자 전용 |
| `PATCH` | `/api/v1/auth/users/{user_id}` | 관리자 전용 역할·활성 상태 변경 |
| `POST` | `/api/v1/auth/logout` | 인증 쿠키 삭제 |
| `POST` | `/api/v1/predictions` | 고객 정보로 이탈 상태와 확률 예측 |
| `GET` | `/api/v1/customer-insights` | 최신 고객 분석 결과 목록·필터·페이지네이션 |
| `GET` | `/api/v1/customer-insights/{customer_id}` | 고객별 최신 분석 결과와 특성 상세 |
| `GET` | `/api/v1/campaign-performance` | 전체·필터 캠페인 성과와 캠페인·세그먼트·담당자별 비교 |
| `GET` | `/api/v1/campaigns/{campaign_id}/performance` | 특정 캠페인 성과 조회 |
| `POST` | `/api/v1/campaign-targeting/preview` | 세그먼트 일괄 타기팅 미리보기 |
| `POST` | `/api/v1/campaign-targeting/runs/{run_id}/execute` | draft 캠페인·대상 생성 |
| `POST` | `/api/v1/campaign-targeting/runs/{run_id}/cancel` | 일괄 타기팅 취소 |
| `POST` | `/api/v1/campaign-targeting/runs/{run_id}/rerun` | 취소 정책 재실행 미리보기 |
| `GET` | `/api/v1/campaign-targeting/runs` | 일괄 타기팅 실행 이력 조회 |
| `PATCH` | `/api/v1/customers/{customer_id}/contact-preferences` | 관리자 전용 수신 거부 상태 변경 |
| `GET` | `/docs` | Swagger UI |
| `GET` | `/redoc` | ReDoc API 문서 |
| `GET` | `/openapi.json` | OpenAPI Schema |

`/`, `/health`, `/api/v1/models`는 제공하지 않으며 요청하면 `404 Not Found`를
반환합니다. 모델 선택은 서버가 검증된 manifest의 기본 모델을 적재하는 방식으로
처리하므로 프론트엔드용 모델 목록 API는 필요하지 않습니다.

인증 API는 `users` 테이블에 계정 아이디, 표시 이름, Argon2 비밀번호 해시를
역할과 함께 저장합니다. 신규 계정은 `analyst` 역할과 비활성 상태로 저장되며,
관리자가 승인해 활성화하기 전에는 로그인할 수 없습니다. 관리자는 팀 계정의
역할·활성 상태를 변경할 수 있으며, 최소 한 명의 활성 관리자는 유지됩니다. 로그인 성공 시
발급되는 JWT는 JavaScript에서 읽을 수 없는
HttpOnly 쿠키에 저장되며, `/api/v1/auth/me`가 현재 사용자를 확인할 때 사용합니다.
DB 테이블은 `create_all()`로 변경하지 않으며 Alembic migration으로 관리합니다.

### 로컬 역할별 테스트 계정

Docker Compose의 일회성 로컬 개발 DB에서만 `.env`에 다음 값을 잠시 설정합니다.
각 비밀번호는 12자 이상이어야 하며 저장소에 커밋하지 않습니다.

```env
APP_ENV=development
ALLOW_TEST_USER_SEEDING=true
TEST_ADMIN_PASSWORD=<local-only-password>
TEST_ANALYST_PASSWORD=<local-only-password>
TEST_OPERATIONS_PASSWORD=<local-only-password>
TEST_MARKETING_PASSWORD=<local-only-password>
```

| 역할 | 아이디 | 비밀번호 환경변수 |
|---|---|---|
| 관리자 | `test_admin` | `TEST_ADMIN_PASSWORD` |
| 분석팀 | `test_analyst` | `TEST_ANALYST_PASSWORD` |
| 운영팀 | `test_operations` | `TEST_OPERATIONS_PASSWORD` |
| 마케팅팀 | `test_marketing` | `TEST_MARKETING_PASSWORD` |

컨테이너는 생성 당시 환경변수를 사용하므로 재생성한 뒤 시드합니다.

```bash
docker compose up -d --force-recreate backend
docker compose exec backend python -m backend.scripts.seed_test_users
```

이 계정은 로컬 화면 검증용입니다. 운영 환경에서는 사용하지 말고, 테스트가
끝난 뒤 `ALLOW_TEST_USER_SEEDING=false`로 되돌려 Backend를 다시 생성합니다.
스크립트는 운영 환경·원격 DB·비밀번호 미설정 상태에서 실행을 거부하며, 같은
아이디가 이미 있으면 역할·비밀번호·표시 이름을 갱신합니다.
호스트에서 API를 직접 실행하기 전에는 다음 명령을 실행합니다.

```bash
python -m backend.app.migration_runner
python -m backend.scripts.import_customers
```

모델 artifact가 준비된 뒤 전체 고객 분석 결과를 저장합니다.

```bash
python -m backend.scripts.run_analysis_batch
```

Docker에서는 다음처럼 실행합니다.

```bash
docker compose exec backend python -m backend.scripts.run_analysis_batch
```

동일한 데이터와 artifact로 다시 실행하면 기존 스냅샷을 재사용하며, 새 이력을
강제로 만들 때만 `--force`를 추가합니다. 배치의 모델 입력 계약, 위험도 기준,
재실행 정책과 실제 저장 결과는
[`../docs/phase2_analysis_batch.md`](../docs/phase2_analysis_batch.md)에 있습니다.

분석 결과 API의 요청 파라미터와 응답 구조는
[`../docs/customer_insights_api.md`](../docs/customer_insights_api.md)에 있습니다.

Docker Compose는 첫 번째 명령을 Backend 시작 전에 자동으로 실행합니다. 자세한
스키마와 운영 방법은 `docs/database_schema.md`를 확인합니다.

정상적인 Readiness 응답 예시는 다음과 같습니다.

```json
{
  "status": "ok",
  "service": "Credit Card Customer ML API",
  "version": "0.1.0",
  "model_loaded": true,
  "model_name": "xgboost",
  "model_artifact": "classification_xgboost.joblib",
  "manifest_generated_at": "2026-07-30T14:19:58+09:00"
}
```

## 고객 이탈 예측

`POST /api/v1/predictions`에 고객 정보 19개를 JSON으로 전달합니다.

| API 필드 | 의미 | 타입 및 허용값 |
|---|---|---|
| `customer_age` | 고객 나이 | 정수, `26~73` |
| `gender` | 성별 | `F`, `M` |
| `dependent_count` | 부양가족 수 | 정수, `0~5` |
| `education_level` | 학력 | `College`, `Doctorate`, `Graduate`, `High School`, `Post-Graduate`, `Uneducated`, `Unknown` |
| `marital_status` | 결혼 상태 | `Divorced`, `Married`, `Single`, `Unknown` |
| `income_category` | 소득 구간 | `$120K +`, `$40K - $60K`, `$60K - $80K`, `$80K - $120K`, `Less than $40K`, `Unknown` |
| `card_category` | 카드 등급 | `Blue`, `Gold`, `Platinum`, `Silver` |
| `months_on_book` | 가입 개월 수 | 정수, `13~56` |
| `total_relationship_count` | 보유 금융상품 수 | 정수, `1~6` |
| `months_inactive_12_mon` | 최근 12개월 중 비활성 개월 수 | 정수, `0~6` |
| `contacts_count_12_mon` | 최근 12개월 고객센터 연락 수 | 정수, `0~6` |
| `credit_limit` | 신용 한도 | 실수, `1438.3~34516.0` |
| `total_revolving_bal` | 리볼빙 잔액 | 정수, `0~2517` |
| `avg_open_to_buy` | 평균 사용 가능 한도 | 실수, `3.0~34516.0` |
| `total_amt_chng_q4_q1` | 1분기 대비 4분기 거래금액 변화율 | 실수, `0.0~3.397` |
| `total_trans_amt` | 최근 12개월 총 거래금액 | 정수, `510~18484` |
| `total_trans_ct` | 최근 12개월 총 거래건수 | 정수, `10~139` |
| `total_ct_chng_q4_q1` | 1분기 대비 4분기 거래건수 변화율 | 실수, `0.0~3.714` |
| `avg_utilization_ratio` | 평균 신용 한도 이용률 | 실수, `0.0~0.999` |

범주형 필드는 모델이 학습한 영문 값을 그대로 전달해야 합니다. 프론트엔드에서
한국어 라벨을 표시하더라도 API 요청의 값은 위 표의 영문 값으로 변환합니다.

```json
{
  "customer_age": 45,
  "gender": "F",
  "dependent_count": 2,
  "education_level": "Graduate",
  "marital_status": "Married",
  "income_category": "$40K - $60K",
  "card_category": "Blue",
  "months_on_book": 36,
  "total_relationship_count": 4,
  "months_inactive_12_mon": 2,
  "contacts_count_12_mon": 3,
  "credit_limit": 12000.0,
  "total_revolving_bal": 1500,
  "avg_open_to_buy": 10500.0,
  "total_amt_chng_q4_q1": 0.8,
  "total_trans_amt": 4500,
  "total_trans_ct": 70,
  "total_ct_chng_q4_q1": 0.75,
  "avg_utilization_ratio": 0.25
}
```

응답에는 판정값, 고객 상태, 이탈 확률과 사용한 모델 정보가 포함됩니다.

```json
{
  "prediction": 0,
  "status": "Existing Customer",
  "churn_probability": 0.0025925275404006243,
  "decision_threshold": 0.5,
  "model_name": "xgboost",
  "model_version": "2026-07-30T15:32:46+09:00"
}
```

- `prediction: 0`: 기존 고객인 것으로 판정
- `prediction: 1`: 이탈 고객인 것으로 판정
- `churn_probability`: 모델이 계산한 이탈 확률
- `decision_threshold`: 이탈 여부를 나누는 임계값

필수 필드 누락, 알 수 없는 추가 필드, 허용 범위를 벗어난 수치 또는 지원하지
않는 범주가 전달되면 HTTP `422 Unprocessable Entity`를 반환합니다.

### 상태 코드

| 상태 코드 | 의미 |
|---|---|
| `200 OK` | 예측 성공 |
| `422 Unprocessable Entity` | 요청 필드 누락, 추가 필드, 타입·범위·범주 오류 |
| `503 Service Unavailable` | 모델 레지스트리가 준비되지 않음 |
| `500 Internal Server Error` | 적재된 모델이 정상적인 예측 결과를 만들지 못함 |

모델의 내부 예외나 서버 파일 경로는 API 응답에 노출하지 않습니다.

## 모델 경로 변경

기본 모델 경로는 프로젝트의 `outputs/models`입니다. 다른 위치의 모델을
사용하려면 서버 실행 전에 절대 경로를 `MODEL_DIR` 환경변수로 지정합니다.

```powershell
$env:MODEL_DIR = "C:\models\credit-card"
.\project_venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

지정한 디렉터리에는 매니페스트와 매니페스트가 선택한 모델 파일이 함께 있어야
합니다.

```text
classification_manifest.json
classification_xgboost.joblib
```

## 테스트

```powershell
.\project_venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
.\project_venv\Scripts\python.exe -m pytest backend\tests -q `
  -p no:cacheprovider `
  --basetemp=project_venv\pytest-temp
```

테스트는 프로젝트의 실제 `outputs/models`에 의존하지 않고 임시 모델과
매니페스트를 만들어 다음 항목을 확인합니다.

- Liveness와 Readiness 응답
- 고객 이탈 및 기존 고객 예측
- 누락·추가 필드와 잘못된 입력값 거부
- 제거된 API가 `404`를 반환하는지 확인
- Swagger UI와 Prediction OpenAPI Schema
- customer_insights 분석 이력·최신 모델 배치·캠페인 대상 업무 API
- 캠페인 중복 등록 차단과 역할별 캠페인 변경 권한 차단
- 불완전한 매니페스트 거부
- `MODEL_DIR` 밖으로 향하는 경로 거부
- 모델 SHA-256 불일치 거부
- 온라인·배치 분류 결과의 확률 일관성
- 회귀 입력 파생변수와 누수 컬럼 제거
- 위험도 구간과 추천 액션 규칙

## 모델 분석 배치

배치는 `classification_manifest.json`, `regression_model.joblib`,
`clustering_activity_gap.joblib`을 읽습니다. 회귀·군집 artifact가 없으면
먼저 다음 순서로 생성합니다.

```bash
python src/final/regression_final.py
python src/final/clustering_final.py
```

배치는 `customers`에서 고객을 읽고 `model_runs` 3건과 고객별
`customer_insights`를 저장합니다. `Target`은 운영 입력으로 사용하지 않습니다.
`campaigns`는 기본 정보·실행 기간·생명주기를 관리하고,
`campaign_targets`는 캠페인별 고객 업무를 관리합니다. 대상 생성·상태 전이·결과
변경은 `campaign_events`에 누적됩니다. 기존 `campaign_name` 요청은 호환되지만
신규 클라이언트는 `campaign_id`를 사용해야 합니다. 분석 세그먼트는
`bulk_targeting_runs`에 고정된 정책과 함께 미리보기·실행·취소·재실행되며,
실행 결과는 draft 캠페인과 `campaign_targets.bulk_targeting_run_id`로 연결됩니다.

## 현재 범위와 알려진 제약

- 현재 Prediction API는 고객 한 명의 요청을 동기 방식으로 예측하며 결과를
  저장하지 않습니다. 전체 결과 저장은 별도 배치 CLI가 담당합니다.
- 분석 결과·이력·최신 배치 상태와 캠페인 목록·이벤트 조회는 모든 활성 로그인
  사용자가 사용할 수 있습니다. 관리자는 전체 권한을 가지며, 캠페인 생성·수정과
  대상 등록은 `admin`, `marketing`, 대상 상태·결과 처리는 `admin`,
  `operations` 역할로 분리됩니다. 세그먼트 일괄 타기팅도 `admin`, `marketing`만
  실행할 수 있습니다. 대상 담당자는 활성 `operations` 사용자만 지정할 수
  있으며 `analyst`는 읽기 전용입니다.
- React 대시보드는 CSV 내보내기, 고위험 필터 바로가기, 고객별 분석 이력,
  모델 배치 버전 표시, 캠페인 등록·처리 큐를 제공합니다. 모델 성능 지표를
  보여 주는 기존 Streamlit 대시보드는 이번 대시보드 통합 범위에서 제외합니다.
- 입력 수치의 최솟값과 최댓값은 현재 학습 데이터 범위를 기준으로 합니다.
  실제 운영 데이터에서는 업무상 유효 범위와 학습 범위를 분리해야 합니다.
- 현재 lifespan에서 모델 적재가 실패하면 FastAPI 시작도 실패합니다. 따라서
  모델 파일이 없거나 손상된 경우 `/live`도 응답하지 않습니다. 운영 배포 전에
  프로세스 생존 상태와 모델 준비 실패를 완전히 분리할지 결정해야 합니다.
- 자동화 테스트는 빠르고 독립적으로 실행하기 위해 가짜 분류기를 사용합니다.
  실제 XGBoost 모델은 학습 후 `/ready`와 Prediction API로 별도 기동 검사를
  수행합니다.
- 브라우저의 다른 Origin 요청을 위한 CORS는 아직 설정하지 않았습니다.

## 자주 발생하는 오류

### `Model manifest not found`

분류 모델이 아직 생성되지 않았거나 `MODEL_DIR`가 잘못 지정되었습니다.

```powershell
.\project_venv\Scripts\python.exe src\classification.py
```

### `Model artifact size mismatch` 또는 `Model artifact hash mismatch`

모델 파일과 매니페스트가 서로 다른 학습 실행에서 생성되었을 수 있습니다.
분류 학습 코드를 다시 실행해 모델과 매니페스트를 함께 갱신합니다.

### `Invalid model manifest`

필수 항목, 데이터 타입 또는 허용 범위가 올바르지 않습니다. 매니페스트를
수동으로 수정하지 말고 학습 코드로 다시 생성합니다.

### pytest 임시 디렉터리 `PermissionError`

Windows 기본 임시 폴더의 기존 `pytest-of-*` 디렉터리에 접근할 수 없을 때
발생합니다. 위 테스트 명령처럼 `--basetemp=project_venv\pytest-temp`를 지정하면
프로젝트 가상환경 안의 무시된 경로를 사용하므로 이 문제를 피할 수 있습니다.

### Pylance의 `asynccontextmanager` deprecated 경고

`@asynccontextmanager`가 제거된 것이 아니라 async generator의 반환 타입을
`AsyncIterator`로 표기하는 방식에 대한 경고입니다. 현재 코드는 다음 표기를
사용합니다.

```python
async def lifespan(
    application: FastAPI,
) -> AsyncGenerator[None, None]:
```

IDE에 이전 경고가 남아 있으면 Python 분석 서버나 편집기를 다시 시작합니다.

## 보안 주의사항

`joblib` 모델은 신뢰할 수 있는 학습 과정에서 생성된 파일만 사용해야 합니다.
외부에서 받은 파일을 직접 로드하지 않습니다. 운영 환경에서는 모델 디렉터리를
Read-only로 마운트하고 모델과 매니페스트를 하나의 배포 단위로 관리하는 것을
권장합니다.

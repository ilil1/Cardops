# Docker Compose 환경 가이드

최신 자동 모델 생성·manifest 갱신·테스트 계정 생성 흐름은
[`docker_compose_runbook.md`](docker_compose_runbook.md)를 먼저 확인합니다.

이 문서는 CardOps 프로젝트의 Frontend, Backend, MySQL 개발 환경을 Docker
Compose로 실행하고, 다른 노트북에서도 동일한 환경을 재현하기 위한 안내서입니다.

구현된 데이터베이스 구조와 Alembic·고객 적재의 상세 명세는
[`phase1_database_implementation.md`](phase1_database_implementation.md)에서
확인할 수 있습니다.

모델 배치 실행과 `model_runs`·`customer_insights` 저장의 상세 명세는
[`phase2_analysis_batch.md`](phase2_analysis_batch.md)에서 확인할 수 있습니다.

운영 전 필수 정확성·보안 보완과 migration 주의사항은
[`immediate_correctness_hardening.md`](immediate_correctness_hardening.md)에서
확인할 수 있습니다.

로컬 시연용 합성 시계열·A/B 캠페인 데이터 생성 방법은
[`demo_data.md`](demo_data.md)에서 확인할 수 있습니다.

분석 결과 조회 API의 사용법은
[`customer_insights_api.md`](customer_insights_api.md)에서 확인할 수 있습니다.

## 1. 구성 개요

`compose.yaml`은 다음 세 개의 서비스를 하나의 Docker 네트워크로 실행합니다.

```text
Mac 호스트
├── 127.0.0.1:5173 ──> Frontend 컨테이너:5173
├── 127.0.0.1:8000 ──> Backend 컨테이너:8000
└── 127.0.0.1:3307 ──> MySQL 컨테이너:3306

Frontend 컨테이너 ──> Backend 컨테이너:8000
Backend 컨테이너  ──> mysql:3306
```

### 서비스 역할

| 서비스 | 역할 | 이미지/실행 환경 |
| --- | --- | --- |
| `mysql` | 회원 및 애플리케이션 데이터 저장 | MySQL 8.4 |
| `backend` | FastAPI API와 머신러닝 모델 제공 | Python 3.13 |
| `frontend` | React/Vite 웹 화면 제공 | Node.js 24, pnpm 11 |

모델은 별도 컨테이너로 실행하지 않습니다. 호스트의
`outputs/models` 디렉터리를 Backend 컨테이너에 읽기 전용으로 마운트하고,
FastAPI가 컨테이너 시작 시 모델을 로드합니다.

## 2. 사전 준비

다음 프로그램이 필요합니다.

- Git
- Docker Desktop
- Python 3.13 권장

Docker Desktop을 실행한 뒤 Docker가 정상적으로 동작하는지 확인합니다.

```bash
docker --version
docker compose version
```

## 3. 처음 실행하는 방법

프로젝트를 받은 뒤 루트 디렉터리에서 실행합니다.

```bash
git clone <저장소 주소>
cd SKN34-2nd-4Team

cp .env.example .env

python3 -m venv project_venv
source project_venv/bin/activate
python -m pip install -r requirements.txt
```

Windows PowerShell에서는 가상환경을 다음과 같이 활성화합니다.

```powershell
.\project_venv\Scripts\Activate.ps1
```

### 모델 파일 생성

모델 파일과 `classification_manifest.json`은 생성 산출물이므로 Git에 기본적으로
포함되지 않습니다. Docker를 실행하기 전에 분류 파이프라인을 한 번 실행합니다.

```bash
python src/classification.py
```

실행이 끝나면 다음 파일이 생성됩니다.

```text
outputs/models/classification_xgboost.joblib
outputs/models/classification_manifest.json
```

### Docker 서비스 시작

```bash
docker compose up -d --build
docker compose ps
```

Backend 컨테이너는 API 시작 전에 Alembic migration을 자동 적용합니다. 기존
`users` 테이블과 회원 데이터가 있으면 기준선에 연결한 뒤 신규 테이블만 추가합니다.

서비스가 시작된 뒤 고객 원본 데이터 10,127명을 한 번 적재합니다. 같은 명령을
다시 실행해도 `CLIENTNUM` 기준으로 갱신되므로 중복되지 않습니다.

```bash
docker compose exec backend python -m backend.scripts.import_customers
```

정상 실행 시 `mysql`은 `healthy`, `backend`와 `frontend`는 `Up` 상태로 표시됩니다.

역할별 화면을 확인하려면 일회성 로컬 DB에서만 테스트 계정 seed를 명시적으로
허용한 뒤 Backend 컨테이너에서 생성합니다. 비밀번호는 저장소에 없으며 로컬
`.env`에 직접 지정해야 합니다.

```env
APP_ENV=development
ALLOW_TEST_USER_SEEDING=true
TEST_ADMIN_PASSWORD=<12자 이상의 로컬 전용 비밀번호>
TEST_ANALYST_PASSWORD=<12자 이상의 로컬 전용 비밀번호>
TEST_OPERATIONS_PASSWORD=<12자 이상의 로컬 전용 비밀번호>
TEST_MARKETING_PASSWORD=<12자 이상의 로컬 전용 비밀번호>
```

컨테이너 환경을 갱신한 뒤 시드합니다.

```bash
docker compose up -d --force-recreate backend
docker compose exec backend python -m backend.scripts.seed_test_users
```

완료 후 `ALLOW_TEST_USER_SEEDING=false`로 되돌리고 Backend를 다시 생성합니다.
계정 ID와 비밀번호 환경변수 대응표는 `backend/README.md`에서 확인할 수 있습니다.

## 4. 접속 주소

| 대상 | 주소 | 용도 |
| --- | --- | --- |
| Frontend | <http://127.0.0.1:5173> | React 화면 |
| FastAPI Swagger | <http://127.0.0.1:8000/docs> | API 확인 |
| FastAPI 생존 확인 | <http://127.0.0.1:8000/live> | 프로세스 상태 확인 |
| FastAPI 준비 확인 | <http://127.0.0.1:8000/ready> | 모델 적재 상태 확인 |
| MySQL | `127.0.0.1:3307` | Mac에서 직접 접속 |

간단한 API 확인 명령은 다음과 같습니다.

```bash
curl http://127.0.0.1:8000/live
curl http://127.0.0.1:8000/ready
```

## 5. 포트와 데이터베이스 접속 주소

Compose의 포트 설정은 다음 형식입니다.

```yaml
ports:
  - "호스트 포트:컨테이너 포트"
```

현재 MySQL 설정은 다음과 같습니다.

```yaml
ports:
  - "${MYSQL_PORT:-3306}:3306"
```

`.env`에 `MYSQL_PORT=3307`이 있으면 실제 연결은 다음과 같습니다.

```text
Mac 호스트:3307 → MySQL 컨테이너:3306
```

접속 위치에 따라 DB 주소가 달라집니다.

| Backend 실행 위치 | DB 주소 |
| --- | --- |
| Mac에서 FastAPI를 직접 실행 | `127.0.0.1:3307` |
| Docker Backend 컨테이너에서 실행 | `mysql:3306` |

`mysql`은 Docker Compose 내부 네트워크에서 사용하는 MySQL 서비스 이름입니다.
Mac 터미널에서는 `mysql:3306`을 사용할 수 없고, Docker Backend에서는
`127.0.0.1:3307`을 사용하면 안 됩니다.

`.env`의 `DATABASE_URL`은 호스트에서 FastAPI를 직접 실행할 때 사용하는 주소입니다.
Compose로 Backend를 실행할 때는 `compose.yaml`이 내부 주소인
`mysql:3306`을 Backend에 주입합니다.

## 6. 환경변수와 비밀값

`.env.example`을 복사해 로컬 `.env`를 생성합니다.

```env
MYSQL_ROOT_PASSWORD=change-root-password
MYSQL_DATABASE=cardops
MYSQL_USER=cardops_app
MYSQL_PASSWORD=change-app-password
MYSQL_PORT=3307
APP_ENV=development
JWT_SECRET=<openssl rand -hex 32로 생성한 값>
AUTH_COOKIE_SECURE=false
LOGIN_MAX_ATTEMPTS=5
LOGIN_IP_MAX_ATTEMPTS=30
LOGIN_RATE_WINDOW_SECONDS=900
```

`.env`에는 비밀번호가 포함될 수 있으므로 커밋하지 않습니다. 저장소에는
`.env.example`만 포함해야 합니다.

## 7. 로그와 종료

전체 서비스 로그를 확인합니다.

```bash
docker compose logs -f
```

특정 서비스 로그만 확인할 수도 있습니다.

```bash
docker compose logs -f backend
docker compose logs -f mysql
```

서비스를 종료해도 MySQL 데이터는 named volume에 남습니다.

```bash
docker compose down
```

MySQL 데이터까지 초기화할 때만 다음 명령을 사용합니다.

```bash
docker compose down -v
```

`down -v`는 저장된 회원 및 애플리케이션 데이터를 삭제하므로 주의해야 합니다.

## 8. 포트 충돌 해결

MySQL 호스트 포트 `3307`이 이미 사용 중인지 확인합니다.

```bash
lsof -nP -iTCP:3307 -sTCP:LISTEN
```

사용 중이면 `.env`의 포트를 변경합니다.

```env
MYSQL_PORT=3308
```

이 경우 Mac에서 MySQL에 접속할 때는 `127.0.0.1:3308`을 사용합니다.
Docker Backend의 DB 주소 `mysql:3306`은 변경하지 않습니다.

Frontend `5173` 또는 Backend `8000`이 사용 중이면 `compose.yaml`의 호스트 포트
부분만 변경할 수 있습니다. 컨테이너 내부 포트와 Docker 네트워크 주소는 그대로
유지합니다.

## 9. 현재 환경의 범위

현재 Docker 구성은 다음 실행 기반을 제공합니다.

- MySQL 컨테이너 실행 및 데이터 보존
- FastAPI Backend 실행
- 분류 모델 로드 및 예측 API 제공
- React/Vite Frontend 실행
- Frontend에서 Backend로의 API 프록시

현재 Docker 구성에는 MySQL 기반 회원가입·로그인 기능이 연결되어 있습니다.
Backend 시작 시 Alembic migration으로 사용자·고객·분석·캠페인 테이블을
준비하고, Argon2로 비밀번호를 해시한 뒤 로그인 성공 시 HttpOnly JWT 쿠키를
발급합니다. 분석 결과·이력·최신 배치 상태 조회와 캠페인 대상 업무 API도
제공합니다. 캠페인 기획·대상 등록은 관리자·마케팅, 실제 대상 처리와 결과 입력은
관리자·운영 역할로 분리됩니다. 모델 분석
결과 배치는 `phase2_analysis_batch.md`, DB 구조와 고객 적재 방법은
[`database_schema.md`](database_schema.md)를 확인합니다.

React 고객 분석 대시보드는 벤토 그리드 요약, 고위험 바로가기, CSV 내보내기,
고객별 분석 이력, 배치 버전 표시, 캠페인 처리 큐를 제공합니다. 기존 모델
성능 Streamlit 대시보드는 별도 앱으로 유지하며 React 화면에는 통합하지 않습니다.

또한 현재 Frontend는 개발용 Vite 서버로 실행되므로, 운영 배포 시에는 Frontend를
빌드한 뒤 Nginx 등의 정적 서버로 제공하는 구성이 추가로 필요합니다.

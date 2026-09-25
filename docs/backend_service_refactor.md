# Core·AI 분리 및 NestJS 레이어 검증

## 변경 범위

- `backend/nest`를 `backend/core-service`로 이동했습니다.
- NestJS의 인증·얼굴 인증·캠페인·일괄 타기팅·성과·고객 분석·모델 이력을 Controller, Service, Repository로 분리했습니다.
- SQL과 조회 조건은 Repository, 쿠키 처리는 Controller, 업무 규칙과 트랜잭션 범위는 Service에 있습니다.
- Python 코드는 `backend/ai-service/cardops_ai`에 모았습니다. 운영 FastAPI 진입점은 `cardops_ai.main:app`입니다.
- JSON Lines 자식 프로세스를 제거하고 서비스 토큰·timeout이 있는 HTTP 통신을 적용했습니다.
- Core와 AI의 Docker 이미지를 분리했습니다. DB 마이그레이션은 별도 `db-init` 작업, 분석·시드는 `jobs` 작업으로 실행합니다.
- 기존 API 경로, 쿠키 이름, DB 테이블·Alembic 이력, BankChurners 서비스 모델과 Synchrony 오프라인 실험 구분을 유지했습니다.

## 실행한 검증

| 검증 | 결과 |
| --- | --- |
| NestJS TypeScript 검사·빌드 | 통과 |
| NestJS 테스트 | 23개 통과: API 46개 계약, 레이어 의존성, 기존 업무 규칙, 트랜잭션·AI 실패 처리 |
| Nest 실제 애플리케이션 의존성 주입 | 컴파일된 AppModule 초기화·종료 통과 |
| 신규 FastAPI AI 테스트 | 15개 통과: 내부 인증, 입력·응답, 모델 오류, 얼굴 API, 업무 라우터 미노출 |
| Docker Compose 설정 해석 | 통과 |
| Node 전용·Python 전용 Docker 이미지 | 두 이미지 빌드 통과 |
| 일회성 MySQL + Core + AI | 실제 HTTP 검사 54개 통과 |
| AI 중단 상태의 Core | `/ready` 503, `/live`·로그인·캠페인 조회 200 확인 |
| 현재 분류 모델 호환성 | 기존 `outputs/models`를 읽기 전용으로 연결해 `lightgbm_final` 적재·예측 성공 |

통합 검증에서는 실제 서비스 이미지와 MySQL 8.4, 연결 확인용 임시 DummyClassifier를 사용했습니다. 별도로 현재 LightGBM 산출물을 새 AI 이미지에서 적재하고 한 건을 예측했습니다. 모델 성능이나 실제 ONNX 얼굴 인식 정확도를 평가한 것은 아닙니다. 운영 DB나 배포 서비스에 테스트 데이터를 쓰지 않았습니다.

HTTP 검증은 가입 승인, JWT 쿠키, 권한 거부, 고객·분석 조회, 모델 실행 이력, 캠페인 생성·상태 전이·처리 이력, 실패 시 롤백, 타기팅 미리보기·실행의 멱등성·취소·재실행, Core에서 FastAPI를 통한 예측을 포함합니다.

## 이전 Python 비교 테스트의 제한

`DATABASE_URL='' python -m pytest backend/ai-service/tests -q` 전체 실행 결과는 **58개 통과, 4개 건너뜀, 2개 실패**입니다.

- `test_login_rate_limit_is_audited`: 이전 Python API의 로그인 제한 함수가 기존 코드에서 비활성화되어 있으나 테스트는 429를 기대합니다. 이번 변경에서 해당 업무 동작을 바꾸지 않았습니다.
- `test_customer_insight_list_filters_and_detail`: 앞 테스트와 공유하는 인증 클라이언트·계정에 의존합니다. 전체 실행에서는 남은 로그인 쿠키로 비인증 검사가 실패하고, 단독 실행에서는 다른 테스트가 생성할 계정이 없어 실패합니다.
- `test_analytics_service.py`의 4개 검사는 별도의 적재된 DB가 필요해 건너뛰었습니다.

이전 API 테스트를 현재 NestJS의 전체 통합 검증 결과로 해석하지 않습니다. 해당 Python 업무 라우터는 AI 운영 앱에 등록되지 않습니다. 실제 Render 환경의 배포·검증과 브라우저 화면 회귀 검증은 이번 로컬 구조 변경 검증에 포함하지 않았습니다.

실행법은 [백엔드 README](../backend/README.md), 배포 전환 순서는 [Render 가이드](free_render_deploy.md)를 참고합니다.

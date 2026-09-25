# CardOps 문서

현재 프로젝트 소개는 [메인 README](../README.md), 백엔드 구조는 [백엔드 README](../backend/README.md)를 참고합니다.

## 실행·구조

| 문서 | 내용 |
| --- | --- |
| [Docker Compose](docker_compose_runbook.md) | MySQL·Core·AI·배치 실행 |
| [Render 배포](free_render_deploy.md) | 서비스 분리와 환경변수·배포 순서 |
| [Core Service](../backend/core-service/README.md) | NestJS 레이어드 아키텍처 |
| [AI Service](../backend/ai-service/README.md) | FastAPI 추론 계약과 Python 작업 |
| [서비스 분리 검증](backend_service_refactor.md) | 빌드·테스트·통합 검증과 제한 |
| [DB 스키마](database_schema.md) | 테이블·Alembic·고객 데이터 적재 |

## 업무 기능

| 문서 | 내용 |
| --- | --- |
| [고객 인사이트 API](customer_insights_api.md) | 고객 목록·상세·이력 |
| [분석 배치](phase2_analysis_batch.md) | 모델 실행·스냅샷 저장 |
| [캠페인 업무 흐름](campaign_workflow.md) | 역할과 상태 전이 |
| [일괄 타기팅](bulk_targeting.md) | 후보 선정·고정·실행 |
| [캠페인 성과](campaign_performance.md) | 결과 입력·집계 규칙 |
| [시연 데이터](demo_data.md) | 합성 고객·캠페인 생성 |

## 데이터 전환·실험

| 문서 | 내용 |
| --- | --- |
| [데이터 전환 배경](data_transition/README.md) | 기존 BankChurners 데이터의 한계 |
| [Synchrony 개선 계획](synchrony_improvement_plan.md) | 시간순 해지 예측 실험 설계 |
| [학습·평가 분리 점검](synchrony_split_audit.md) | 누수·평가 시점 검토 |
| [추가 개선 결과](synchrony_advanced_evaluation.md) | 모델 비교·검증 범위 |

`phase1_database_implementation.md`, `legacy_project_readme.md` 등의 문서는 이전 구현 기록입니다. 현재 서버 실행 명령과 서비스 경계는 위의 Core·AI 문서를 기준으로 합니다.

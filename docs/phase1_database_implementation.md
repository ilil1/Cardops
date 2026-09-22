# 1단계 구현 문서: 고객 데이터와 분석 결과 저장 기반

## 1. 문서 목적

이 문서는 CardOps 프로젝트에 구현된 다음 기능의 구조와 사용법을 설명합니다.

- SQLAlchemy 기반 업무 데이터 모델
- Alembic migration을 이용한 MySQL 스키마 버전 관리
- 기존 users 회원 데이터를 보존하는 migration 도입
- 원본 고객 CSV의 CLIENTNUM과 19개 고객 특성 적재
- 모델 실행 이력·고객 분석·캠페인 결과를 저장하기 위한 테이블
- Docker Compose 시작 시 자동 migration
- Backend와 Frontend 인증 응답의 사용자 역할(role) 반영

이번 문서는 저장 기반을 처음 도입한 1단계 구현을 설명합니다. 이후 2단계에서
분류·회귀·군집 모델을 실행해 `model_runs`와 `customer_insights`를 채우는 배치도
구현했습니다. 배치의 상세 사용법과 실제 검증 결과는
[`phase2_analysis_batch.md`](phase2_analysis_batch.md)를 참고하세요.

## 2. 구현 범위와 현재 상태

~~~text
Docker Compose 시작
        │
        ▼
Backend entrypoint
        │
        ├─ migration_runner
        │      └─ Alembic upgrade head
        │
        └─ Uvicorn/FastAPI 시작

원본 BankChurners.csv
        │
        ▼
import_customers 명령
        │
        ├─ CLIENTNUM 기준 upsert
                   │
                   ▼
               customers

모델 배치
        │
        ├─ decision_policies
        ├─ scoring_batches
        ├─ model_runs
        ├─ customer_feature_snapshots
        ├─ customer_insights
        ├─ campaigns
        ├─ campaign_events
        ├─ campaign_targets
        ├─ bulk_targeting_runs
        ├─ bulk_targeting_candidates
        └─ auth_events
~~~

2026-08-02 로컬 Docker MySQL과 빈 SQLite에서 확인한 스키마 검증 상태입니다.
업무 테이블의 행 수는 개발 진행에 따라 달라지므로 스키마 계약으로 고정하지
않습니다.

| 항목 | 상태 |
|---|---|
| Alembic 최신 revision | 20260802_0010 |
| 빈 DB upgrade | head까지 성공 |
| downgrade·재-upgrade | 0008 → 0010 왕복 성공 |
| SQLAlchemy schema drift | `alembic check` 통과 |
| 기존 사용자·업무 데이터 | migration 후 보존 |
| campaign_id·customer_id 중복 | unique 적용 전 정리, 적용 후 0건 |
| customers.customer_id 중복 | 없음 |

기존 `campaign_name` 기반 대상은 migration 0005에서 실제 캠페인과 생성 이벤트로
backfill됩니다. 신규 대상은 명시적인 캠페인 계보와 상태 전이 이벤트를 함께
저장합니다. 모델 배치는 성공한 동일 입력을 재사용하고 실패한 동일 입력은 다음
시도 번호로 재실행합니다.

## 3. 관련 파일

| 파일 | 역할 |
|---|---|
| backend/alembic.ini | Alembic 스크립트 위치와 기본 설정 |
| backend/migrations/env.py | SQLAlchemy metadata와 DB 연결을 Alembic에 연결 |
| backend/migrations/versions/20260801_0001_users_baseline.py | 기존 users 구조의 기준선 revision |
| backend/migrations/versions/20260801_0002_customer_operations.py | 역할·고객·분석·캠페인 테이블 생성 |
| backend/migrations/versions/20260801_0003_p0_data_governance.py | 승인 기본값·입력 스냅샷·정책 hash 추가 |
| backend/migrations/versions/20260801_0004_scoring_lineage.py | scoring batch·decision policy·기준일 연결 |
| backend/migrations/versions/20260801_0005_campaign_domain.py | campaigns·campaign_events·대상 결과 집계 필드와 기존 데이터 backfill |
| backend/migrations/versions/20260801_0006_campaign_converted_not_null.py | 전환 여부 컬럼을 필수 boolean으로 고정 |
| backend/migrations/versions/20260801_0007_bulk_targeting.py | 수신 거부·최근 접촉 필드와 세그먼트 일괄 타기팅 배치 추가 |
| backend/migrations/versions/20260801_0008_performance_measurement.py | A/B 실험·유지·비용·매출 성과 필드 추가 |
| backend/migrations/versions/20260802_0009_immediate_correctness.py | 시점 재시도·후보 스냅샷·금액 정밀도·인증 감사 보완 |
| backend/migrations/versions/20260802_0010_campaign_money_defaults.py | MySQL 금액 컬럼 서버 기본값 복구 |
| backend/app/database.py | DB 엔진·세션 생성 및 migration 여부 검증 |
| backend/app/models.py | SQLAlchemy 모델 전체 정의 |
| backend/app/enums.py | 역할·상태·위험등급 상수 정의 |
| backend/app/migration_runner.py | 기존 DB 호환 처리와 upgrade head 실행 |
| backend/app/customer_import.py | CSV 검증, 변환, MySQL/SQLite upsert |
| backend/scripts/import_customers.py | 고객 적재 CLI 진입점 |
| backend/app/analysis_batch.py | 세 모델 실행과 customer_insights 저장 |
| backend/scripts/run_analysis_batch.py | 모델 분석 배치 CLI 진입점 |
| backend/docker-entrypoint.sh | 컨테이너 시작 시 migration 후 API 실행 |
| compose.yaml | MySQL·Backend·Frontend 연결과 data 읽기 전용 mount |
| backend/tests/test_persistence.py | migration·기존 회원·적재·관계 검증 |

## 4. 데이터베이스 구조

~~~mermaid
erDiagram
    USERS ||--o{ CAMPAIGN_TARGETS : assigns
    CUSTOMERS ||--o{ CUSTOMER_INSIGHTS : receives
    CUSTOMERS ||--o{ CAMPAIGN_TARGETS : targets
    MODEL_RUNS ||--o{ CUSTOMER_INSIGHTS : classifies
    MODEL_RUNS ||--o{ CUSTOMER_INSIGHTS : regresses
    MODEL_RUNS ||--o{ CUSTOMER_INSIGHTS : clusters
    CUSTOMER_INSIGHTS ||--o{ CAMPAIGN_TARGETS : recommends
~~~

### 4.1 users

기존 회원가입·로그인 계정 테이블입니다. 비밀번호 원문은 저장하지 않고
Argon2 해시만 저장합니다.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | INT | 기본키, 자동 증가 |
| username | VARCHAR(50) | 로그인 ID, unique |
| display_name | VARCHAR(100) | 표시 이름 |
| password_hash | VARCHAR(255) | Argon2 비밀번호 해시 |
| role | VARCHAR(20) | admin, analyst, operations, marketing |
| is_active | BOOLEAN | 계정 활성 여부 |
| created_at | DATETIME | 생성 시각 |
| updated_at | DATETIME | 수정 시각 |

회원가입 요청에서는 role을 받지 않습니다. 신규 계정은 `analyst` 역할과
비활성(`is_active=false`) 상태로 생성되며, 관리자가 승인하기 전에는 로그인할 수
없습니다. 사용자가 직접 회원가입하면서 운영·관리 권한을 얻는 상황을 방지하기
위한 정책입니다.
캠페인 생성·수정·대상 등록·일괄 타기팅은 `admin`, `marketing` 역할로 제한되며,
대상 상태·담당자·결과 변경은 `admin`, `operations`가 수행합니다. 대상 담당자는
활성 `operations` 사용자만 지정할 수 있습니다.
`analyst`는 분석 결과와 캠페인 큐를 조회만 할 수 있습니다.

### 4.2 customers

원본 BankChurners.csv에서 모델 입력으로 사용할 고객 식별자와 19개 특성을
저장합니다. 모델 정제 데이터에서 제거한 CLIENTNUM은 서비스에서 고객을 조회하고
다른 테이블과 연결하기 위해 customer_id로 보존합니다.

| DB 컬럼 | 원본 컬럼 | 설명 |
|---|---|---|
| customer_id | CLIENTNUM | 고객 업무 식별자, 기본키 |
| customer_age | Customer_Age | 고객 연령 |
| gender | Gender | 성별 |
| dependent_count | Dependent_count | 부양가족 수 |
| education_level | Education_Level | 교육 수준 |
| marital_status | Marital_Status | 결혼 상태 |
| income_category | Income_Category | 소득 구간 |
| card_category | Card_Category | 카드 등급 |
| months_on_book | Months_on_book | 카드 이용 기간 |
| total_relationship_count | Total_Relationship_Count | 보유 관계 상품 수 |
| months_inactive_12_mon | Months_Inactive_12_mon | 최근 12개월 비활성 개월 수 |
| contacts_count_12_mon | Contacts_Count_12_mon | 최근 12개월 문의 횟수 |
| credit_limit | Credit_Limit | 신용 한도 |
| total_revolving_bal | Total_Revolving_Bal | 리볼빙 잔액 |
| avg_open_to_buy | Avg_Open_To_Buy | 평균 사용 가능 한도 |
| total_amt_chng_q4_q1 | Total_Amt_Chng_Q4_Q1 | 거래금액 변화율 |
| total_trans_amt | Total_Trans_Amt | 총 거래금액 |
| total_trans_ct | Total_Trans_Ct | 총 거래건수 |
| total_ct_chng_q4_q1 | Total_Ct_Chng_Q4_Q1 | 거래건수 변화율 |
| avg_utilization_ratio | Avg_Utilization_Ratio | 평균 이용률 |
| marketing_opt_out | - | 마케팅 수신 거부 여부, 기본 false |
| last_contacted_at | - | 최근 접촉 시각, 캠페인 contacted/completed 처리 시 자동 갱신 |
| created_at, updated_at | - | 적재·수정 시각 |

다음 컬럼은 customers에 저장하지 않습니다.

- Attrition_Flag: 모델 학습 정답인 Target은 운영 고객 정보와 분리합니다.
- Naive_Bayes_Classifier_...: 원본에 포함된 기존 모델 결과이므로 제외합니다.

즉 customer_id는 조회용 식별자이고, 모델 입력 19개에는 포함되지 않습니다.

### 4.3 model_runs

모델 파일과 배치 실행의 계보를 보존합니다. 같은 모델 버전을 여러 번 실행해도
실행별 행을 남길 수 있습니다.

| 컬럼 | 설명 |
|---|---|
| id | 모델 실행 기본키 |
| task | classification, regression, clustering 등 작업명 |
| model_name | 예: xgboost, voting, activity-gap-gmm |
| model_version | 모델 manifest 버전 또는 실행 식별자 |
| artifact_path | 사용한 모델 파일 경로 |
| artifact_sha256 | 모델 파일 무결성 해시 |
| dataset_sha256 | 사용 데이터셋 해시, 선택값 |
| scoring_batch_id | 분석 배치 외래키, 기존 레거시 행은 NULL 가능 |
| decision_policy_sha256 | 적용한 의사결정 정책 hash |
| medium_threshold | 중위험 기준값 |
| high_threshold | 고위험 기준값 |
| activity_gap_quantile | 활동성 갭 우선순위 분위수 |
| status | running, succeeded, failed |
| processed_rows | 처리한 고객 수 |
| error_message | 실패 시 오류 내용 |
| started_at | 실행 시작 시각 |
| completed_at | 실행 종료 시각 |
| created_at | 실행 레코드 생성 시각 |

artifact_sha256는 현재 모델 manifest의 파일 무결성 검증 방식과 연결됩니다.
향후 모델 배치가 실패해도 failed 상태와 오류를 남길 수 있습니다.

### 4.4 decision_policies

분석 결과를 해석하는 정책을 immutable registry로 관리합니다. 동일한
`policy_sha256`은 하나만 저장하며, 위험도 기준이나 활동성 분위수가 바뀌면
새 정책 행이 생성됩니다.

| 컬럼 | 설명 |
|---|---|
| id | 정책 기본키 |
| version | 정책 버전, 예: `activity-gap-v2` |
| policy_sha256 | 정책 파라미터 전체의 SHA-256 |
| medium_threshold | 중위험 기준값 |
| high_threshold | 고위험 기준값 |
| activity_gap_quantile | 활동성 갭 우선순위 분위수 |
| policy_json | 사유·추천·군집·입력 계약을 포함한 전체 정책 JSON |
| created_at | 정책 등록 시각 |

### 4.5 scoring_batches

분류·회귀·군집 세 실행과 고객 인사이트를 하나로 묶는 배치 단위입니다.
분석 기준일과 입력 데이터, 정책을 직접 보존하므로 단순히 최신
`model_runs` 3개를 조합하는 방식보다 재현성과 재사용 판정이 명확합니다.

| 컬럼 | 설명 |
|---|---|
| id | 배치 기본키 |
| batch_key_sha256 | 개별 실행 시도의 고유 key |
| reuse_key_sha256 | 기준일·데이터·artifact·정책이 같은 논리 배치 key |
| attempt_number | 동일 논리 배치의 실행 시도 번호 |
| as_of_date | 업무 분석 기준일 |
| source_dataset_sha256 | 원천 데이터 hash |
| dataset_sha256 | 실제 DB 고객 입력 전체 hash |
| decision_policy_id | 적용 정책 외래키 |
| status | running, succeeded, failed |
| processed_rows | 처리 고객 수 |
| error_message | 실패 시 오류 내용 |
| started_at, completed_at | 배치 실행 시각 |

### 4.6 customer_feature_snapshots

고객 특성 19개와 `as_of_date`를 함께 보존합니다. 동일 고객·동일 특성이라도
분석 기준일이 다르면 별도 시점 스냅샷으로 저장할 수 있습니다.

### 4.7 customer_insights

고객별 분류·회귀·군집 결과를 하나의 분석 스냅샷으로 저장합니다. 고객 한 명의
결과를 매번 덮어쓰지 않고 scored_at을 기준으로 분석 이력을 누적할 수 있도록
설계했습니다.

| 컬럼 | 설명 |
|---|---|
| id | 분석 스냅샷 기본키 |
| customer_id | customers.customer_id 외래키 |
| customer_snapshot_id | 분석 당시 입력 스냅샷 외래키 |
| scoring_batch_id | 분석 배치 외래키 |
| as_of_date | 분석 기준일 |
| classification_run_id | 이탈 분류 모델 실행 외래키 |
| regression_run_id | 거래건수 회귀 모델 실행 외래키 |
| clustering_run_id | 활동성 군집 모델 실행 외래키 |
| churn_probability | 이탈 확률, 0~1 |
| risk_level | low, medium, high |
| expected_transaction_count | 모델이 예상한 거래건수 |
| activity_gap | 실제 거래건수 - 예상 거래건수 |
| cluster_name | 우선케어·일반관리·우량 등 비즈니스 이름 |
| cluster_confidence | 군집 소속 확률 또는 신뢰도 |
| recommended_action | 추천 대응 문구 |
| reason_codes | 영향 요인 코드 JSON |
| scored_at | 분석 계산 시각 |
| created_at | 저장 시각 |

세 개의 model_run_id를 각각 보존하는 이유는 분류 모델만 교체되거나 회귀
모델만 다시 계산된 경우에도 어떤 산출물을 조합했는지 확인하기 위해서입니다.

### 4.8 campaigns

캠페인 자체의 기본 정보와 실행 기간, 생명주기 상태를 저장합니다.

| 컬럼 | 설명 |
|---|---|
| id | 캠페인 기본키 |
| name | 캠페인 이름, unique |
| description | 캠페인 목적·운영 메모 |
| channel | 실행 채널 |
| segment_code | 성과 비교용 분석 세그먼트 |
| status | draft, scheduled, active, paused, completed, cancelled |
| start_at, end_at | 캠페인 실행 기간 |
| experiment_enabled, control_group_ratio | A/B 테스트와 대조군 비율 |
| experiment_seed | 재현 가능한 대상군·대조군 배정 seed |
| experiment_assignment_version | 기존·신규 A/B 해시 알고리즘 버전 |
| fixed_cost, cost_per_contact, revenue_per_conversion | ROI 계산 기준 금액 |
| retention_window_days | 유지 여부 관측 기준 기간 |
| created_by_user_id | 생성자 외래키 |
| created_at, updated_at | 생성·수정 시각 |

### 4.9 campaign_events

캠페인과 캠페인 대상의 상태·담당자·결과 변경을 이벤트 이력으로 남깁니다.

| 컬럼 | 설명 |
|---|---|
| campaign_id | 캠페인 외래키 |
| campaign_target_id | 대상 외래키, 캠페인 자체 이벤트는 NULL 가능 |
| event_type | created, status_changed, assigned, result_updated, conversion_updated |
| from_status, to_status | 변경 전·후 상태 |
| actor_user_id | 변경 수행 사용자 |
| metadata_json | 담당자·전환 등 구조화된 부가 정보 |
| created_at | 이벤트 발생 시각 |

### 4.10 campaign_targets

분석 결과에서 추천된 캠페인 대상과 실제 업무 처리 결과를 저장합니다.

| 컬럼 | 설명 |
|---|---|
| id | 캠페인 대상 기본키 |
| customer_id | 대상 고객 외래키 |
| customer_insight_id | 추천 근거가 된 분석 스냅샷 외래키 |
| campaign_id | campaigns 외래키 |
| bulk_targeting_run_id | 일괄 타기팅 생성 배치 외래키 |
| campaign_name | 예: 이탈 위험 리텐션 |
| assigned_to_user_id | 담당자, users.id 외래키 |
| status | pending, assigned, contacted, completed, cancelled |
| processed_at | 처리 완료 또는 마지막 처리 시각 |
| result | 상담·캠페인 결과 |
| result_notes | 상세 메모 |
| result_code | converted, not_converted, no_response 등 표준 결과 코드 |
| converted | 전환 여부, 캠페인 집계 기준 |
| experiment_group | treatment 대상군 또는 control 대조군 |
| contacted_at, completed_at, converted_at | 성과 상태별 시각 |
| retained, retention_checked_at | 유지 결과와 관측 시각 |
| outcome_revenue | 고객별 실제 매출, 캠페인 기본값보다 우선 |
| created_at, updated_at | 생성·수정 시각 |

같은 캠페인에 같은 고객을 중복 생성하지 않도록 `campaign_id + customer_id`에
unique 제약을 둡니다. 기존 호환을 위해 `customer_insight_id + campaign_name`
제약도 유지합니다.

### 4.11 bulk_targeting_runs

세그먼트 기반 일괄 타기팅의 의사결정과 실행 이력을 저장합니다.

| 컬럼 | 설명 |
|---|---|
| segment_code | high_risk_retention, medium_reactivation, low_risk_upsell |
| status | previewed, executed, cancelled |
| campaign_id | 실행 시 생성된 draft campaigns 외래키 |
| requested_by_user_id | 미리보기·실행 요청 사용자 |
| rerun_of_id | 재실행 원본 배치 외래키 |
| scoring_batch_id | 후보 전체가 공유하는 성공 분석 배치 외래키 |
| source_as_of_date | 분석 결과 기준일 |
| rules_json | 분위수·threshold·제외 기간·최대 대상 등 고정 정책 |
| preview_count, eligible_count, created_count | 미리보기·등록 집계 |
| skipped_*_count | 활성 캠페인·최근 접촉·수신 거부 제외 집계 |
| executed_at, cancelled_at | 상태 변경 시각 |

실행된 대상에는 `campaign_targets.bulk_targeting_run_id`가 저장되므로 어느
세그먼트 배치가 만든 대상인지 추적할 수 있습니다. 상세 규칙과 API 흐름은
[`bulk_targeting.md`](bulk_targeting.md)에 정리했습니다.

### 4.12 bulk_targeting_candidates

미리보기에서 평가한 고객별 분석 스냅샷, 순위, 제외 사유, 선택 여부와 실제 실행
결과를 저장합니다. 실행은 이 행을 기준으로 하므로 미리보기와 실행 사이에 최신
분석 결과가 바뀌어도 대상 목록이 조용히 달라지지 않습니다.

### 4.13 auth_events

가입 요청, 로그인 성공·실패·제한, 로그아웃, 관리자 계정 변경을 사용자·IP·수행자·
구조화 metadata와 함께 기록합니다. 로그인 실패 이벤트는 DB 기반 시도 제한의
근거로도 사용합니다.

## 5. Alembic migration 동작

### 5.1 새 DB

빈 MySQL 또는 SQLite DB에서 migration을 실행하면 다음 순서로 적용됩니다.

~~~text
20260801_0001_users_baseline
        │
        ▼
20260801_0002_customer_operations
        │
        ▼
20260801_0003_p0_data_governance
        │
        ▼
20260801_0004_scoring_lineage
        │
        ▼
20260801_0005_campaign_domain
        │
        ▼
20260801_0006_campaign_converted_not_null
        │
        ▼
20260801_0007_bulk_targeting
        │
        ▼
20260801_0008_performance_measurement
        │
        ▼
20260802_0009_immediate_correctness
        │
        ▼
20260802_0010_campaign_money_defaults
~~~

첫 번째 revision은 users 기준선 테이블을 만들고, 두 번째 revision은
users.role과 나머지 업무 테이블을 추가합니다. 세 번째 revision은 승인 기본값과
고객 입력 스냅샷을 추가하고, 네 번째 revision은 scoring batch,
decision policy, 분석 기준일을 연결합니다. 다섯 번째 revision은 캠페인 기본
정보, 대상 계보, 이벤트 이력, 결과 집계 필드를 추가하고 기존
`campaign_name` 데이터를 캠페인으로 backfill합니다.
여섯 번째 revision은 기존 NULL 전환 여부를 false로 보정하고 `converted`를
필수 boolean으로 고정합니다. 일곱 번째 revision은 수신 거부·최근 접촉 필드와
세그먼트 일괄 타기팅 실행 이력, 대상-배치 연결을 추가합니다. 여덟 번째 revision은
A/B 대상군·대조군, 구조화 결과 시각, 유지 관측값과 캠페인 비용·매출 정책을
추가합니다. 성과 계산식은 [`campaign_performance.md`](campaign_performance.md)에
정리했습니다. 아홉 번째 revision은 정책 JSON과 배치 재시도 계보, 타기팅 후보
스냅샷, 고객-캠페인 중복 제약, A/B 배정 버전, `NUMERIC(18, 2)` 금액과 인증 감사
이벤트를 추가합니다. 열 번째 revision은 MySQL 타입 변경 과정에서 사라질 수 있는
캠페인 금액 컬럼의 서버 기본값 `0`을 복구합니다.

### 5.2 기존 DB

기존 프로젝트는 Alembic 도입 전에 Base.metadata.create_all()로 users만
생성하고 있었습니다. 이 DB에 새 migration을 바로 적용하면 첫 revision이
이미 존재하는 users를 다시 만들려고 할 수 있습니다.

backend.app.migration_runner는 다음 방식으로 이를 처리합니다.

1. alembic_version의 현재 revision을 확인합니다.
2. revision이 없고 users가 있으면 기존 필수 컬럼을 확인합니다.
3. 기존 users 데이터가 정상인 경우 20260801_0001을 기준선으로 stamp합니다.
4. 최신 revision까지 upgrade해 role, 분석 테이블, 입력 스냅샷, scoring lineage를
   추가합니다.
5. 기존 회원 데이터는 삭제하거나 재생성하지 않습니다.

이미 신규 관리 테이블이 일부만 존재하는 비정상 상태라면 자동으로 진행하지 않고
오류를 발생시킵니다. 이런 경우에는 DB 백업과 현재 revision을 확인한 뒤 수동으로
복구해야 합니다.

### 5.3 FastAPI 시작 전 검증

initialize_database()는 더 이상 Base.metadata.create_all()을 호출하지 않습니다.
대신 다음을 확인합니다.

- alembic_version 테이블 존재 여부
- SQLAlchemy 모델에 등록된 필수 테이블 존재 여부

조건을 만족하지 않으면 API를 준비 상태로 띄우지 않고 migration 실행 명령을
안내하는 오류를 발생시킵니다. 이를 통해 모델만 바꾸고 DB migration을 빠뜨리는
상황을 조기에 확인할 수 있습니다.

## 6. 실행 방법

### 6.1 Docker Compose

프로젝트 루트에서 실행합니다.

~~~bash
cp .env.example .env
docker compose up -d --build
docker compose ps
~~~

Backend 컨테이너의 docker-entrypoint.sh가 다음 순서로 실행됩니다.

~~~text
python -m backend.app.migration_runner
        │
        ▼
alembic upgrade head
        │
        ▼
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
~~~

고객 CSV는 compose.yaml의 다음 읽기 전용 mount로 컨테이너에 전달됩니다.

~~~yaml
- ./data:/app/data:ro
~~~

서비스 시작 후 고객을 적재합니다.

~~~bash
docker compose exec backend python -m backend.scripts.import_customers
~~~

### 6.2 호스트에서 Backend 실행

호스트에서 실행하는 경우 .env의 DATABASE_URL은 127.0.0.1:3307을
사용해야 합니다.

~~~bash
source project_venv/bin/activate
python -m backend.app.migration_runner
python -m backend.scripts.import_customers
python -m uvicorn backend.app.main:app --reload
~~~

호스트에서 실행하는 FastAPI는 Docker 내부 주소인 mysql:3306에 접근할 수
없습니다. 반대로 Docker Backend는 127.0.0.1:3307이 아니라 Compose 서비스명인
mysql:3306을 사용합니다.

### 6.3 Alembic 상태 확인

~~~bash
alembic -c backend/alembic.ini current
alembic -c backend/alembic.ini history
alembic -c backend/alembic.ini check
~~~

가상환경의 실행 파일을 직접 사용할 수도 있습니다.

~~~bash
project_venv/bin/alembic -c backend/alembic.ini current
~~~

check 결과가 No new upgrade operations detected.이면 현재 SQLAlchemy 모델과
DB migration 상태가 일치한다는 의미입니다.

## 7. 고객 CSV 적재 규칙

### 입력 파일

기본 입력 경로는 다음과 같습니다.

~~~text
data/raw/BankChurners.csv
~~~

필수 컬럼은 CLIENTNUM과 모델 입력 19개입니다. Attrition_Flag와
Naive Bayes 결과 컬럼은 읽지만 저장하지 않습니다.

### 변환

- 원본 대문자 컬럼을 DB snake_case 컬럼으로 변환합니다.
- 정수형 특성은 int로 변환합니다.
- 금액·비율 특성은 float으로 변환합니다.
- 필수 컬럼 누락, 빈 값, 잘못된 숫자, 중복 CLIENTNUM을 거부합니다.
- customer_id를 기본키로 사용합니다.

### 중복 처리

customer_import.py는 DB dialect에 따라 upsert를 사용합니다.

- MySQL: ON DUPLICATE KEY UPDATE
- SQLite: ON CONFLICT DO UPDATE
- 기타 DB: SQLAlchemy merge

따라서 다음 명령을 여러 번 실행해도 고객 행이 계속 증가하지 않습니다.

~~~bash
docker compose exec backend python -m backend.scripts.import_customers
~~~

출력 예시는 다음과 같습니다.

~~~text
Customer import complete: processed=10127, inserted=10127, updated=0, total=10127
~~~

재실행하면 inserted=0, updated=10127이 되며 총 고객 수는 10,127명으로
유지됩니다.

## 8. 테스트와 검증

Persistence 테스트는 다음을 검증합니다.

- 빈 SQLite DB를 최신 migration까지 생성
- 기존 users 테이블과 회원 보존
- 신규 회원가입 계정이 analyst·비활성으로 생성되는지와 승인 전 로그인이 차단되는지
- customer_feature_snapshots 테이블 및 customer_insights 입력 lineage
- 원본 CSV 10,127행 파싱
- 고객 upsert 재실행 시 중복 방지
- 세 model_runs와 하나의 customer_insight 연결
- 캠페인 담당자와 분석 lineage 관계 저장

실행 명령:

~~~bash
project_venv/bin/python -m pytest backend/tests -q
~~~

현재 구현 검증 결과는 Backend 테스트 31개 통과입니다. Frontend 인증 타입과
OpenAPI 생성 타입도 role 필드를 포함하도록 갱신했으며 Frontend lint,
typecheck, test, build를 통과했습니다.

## 9. 운영 및 보안 주의사항

- .env에는 DB 비밀번호와 JWT secret이 있으므로 커밋하지 않습니다.
- 테스트 계정 seed는 기본 비활성입니다. 로컬 일회성 DB에서만
  `ALLOW_TEST_USER_SEEDING=true`를 명시적으로 설정합니다.
- 회원 비밀번호 원문은 어떤 테이블에도 저장하지 않습니다.
- CLIENTNUM은 모델 입력으로 사용하지 않습니다.
- Attrition_Flag/Target은 운영 캠페인 규칙의 입력으로 사용하지 않습니다.
- 모델 artifact 경로와 SHA-256은 model_runs에 기록해 실행 결과를 추적합니다.
- docker compose down -v는 MySQL named volume을 삭제하므로 회원·고객 데이터를
  지울 때만 사용합니다.
- 실제 운영 DB에는 migration 전 백업과 migration 후 alembic check를 권장합니다.

## 10. 저장 기반 위에 구현된 업무 기능

1. customers와 최신·과거 customer_insights 조회 API
2. 우선관리 고객 목록·상세 화면과 고위험 필터 바로가기
3. 추천 캠페인 대상 생성, 담당자 자동 배정, 처리 상태·결과 저장
4. users.role 기준 캠페인 기획·대상 등록·고객 처리 권한 분리
5. 최신 model_runs 배치 상태·모델 버전 표시와 CSV 내보내기
6. 고위험 리텐션·중위험 재활성화·저위험 우량군 업셀링 세그먼트 일괄 타기팅
7. 미리보기, 활성 캠페인·최근 접촉·수신 거부 제외, 취소·재실행 이력 관리

모델 성능 Streamlit 대시보드 통합은 현재 범위에 포함하지 않습니다.

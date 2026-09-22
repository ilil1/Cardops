# 2단계 구현 문서: 모델 배치 스코어링과 분석 결과 저장

## 1. 목적

1단계에서 준비한 `customers`, `model_runs`, `customer_insights` 저장 구조에
실제 모델 실행을 연결했습니다. 이제 Docker Backend에서 전체 고객을 한 번
스코어링하면 다음 결과가 MySQL에 저장됩니다.

- 분류: 고객별 이탈 확률과 위험 등급
- 회귀: 예상 거래건수와 실제 거래건수의 활동성 갭
- 군집: 활동성 갭 기반 고객 세그먼트와 군집 확률
- 운영: 설명용 사유 코드와 추천 액션
- 추적성: 사용한 모델 artifact·데이터·의사결정 정책 해시와 실행 상태
- 재현성: 분석 당시 고객 특성을 `customer_feature_snapshots`에 보존
- 배치 계보: `scoring_batches`, `decision_policies`, `as_of_date`로 하나의 분석 실행을 식별

모델의 학습 정답인 `Target` 또는 `Attrition_Flag`는 운영 배치 입력에 사용하지
않습니다. `customers`에 저장된 고객 특성과 모델 artifact만으로 결과를
계산합니다.

## 2. 전체 처리 흐름

~~~mermaid
flowchart LR
    C[customers 10,127명] --> F[모델 입력 변환]
    F --> CL[분류 XGBoost]
    F --> RE[회귀 Voting]
    CL --> I[customer_insights]
    RE --> GAP[실제 거래건수 - 예상 거래건수]
    GAP --> G[활동성 갭 GMM k=3]
    G --> I
    P[decision_policies] --> B[scoring_batches]
    B --> R[model_runs]
    B --> I
    CL --> R
    RE --> R
    G --> R
~~~

배치는 먼저 정책 registry에서 `decision_policies`를 확보하고, 기준일·고객 입력
hash·세 artifact·정책 hash를 묶은 `scoring_batches` 1건을 생성합니다. 이후
세 모델의 `model_runs` 3건과 고객별 `customer_insights`를 같은 batch ID로
연결합니다. 따라서 고객 결과 한 행이 어떤 기준일·정책·분류·회귀·군집
artifact에서 나온 것인지 추적할 수 있습니다.

## 3. 구현 파일

| 파일 | 역할 |
|---|---|
| `backend/app/analysis_batch.py` | 고객 조회, 세 모델 실행, 운영 규칙 적용, DB 저장 |
| `backend/scripts/run_analysis_batch.py` | 환경변수 기반 배치 CLI |
| `backend/app/model_registry.py` | 분류 모델의 manifest 검증과 벡터화 batch predict |
| `src/final/regression_final.py` | 금액 제외 Voting 회귀 artifact와 전체 OOF 결과 생성 |
| `src/final/clustering_final.py` | 활동성 갭 GMM k=3 artifact 생성 |
| `backend/tests/test_analysis_batch.py` | 회귀 입력 계약과 위험도·액션 규칙 테스트 |
| `backend/tests/test_api.py` | 온라인·배치 분류 결과 일관성 테스트 포함 |
| `backend/Dockerfile` | LightGBM 실행에 필요한 `libgomp1` 설치 |

## 4. 모델 입력 계약

### 4.1 분류

기존 `classification_manifest.json`이 선택한 기본 모델을 사용합니다. manifest의
19개 원본 컬럼 순서를 그대로 지키며, `ModelRegistry.predict_batch()`가
`predict_proba()`를 벡터화 호출합니다. 온라인 `POST /api/v1/predictions`와
양성 클래스·임계값 선택 규칙을 공유합니다.

### 4.2 회귀

`outputs/models/regression_model.joblib`은 `src/final/regression_final.py`가
생성한 완성형 Pipeline입니다. 배치에서는 다음 파생변수를 동일하게 생성합니다.

- `리볼빙_한도_비율` = `Total_Revolving_Bal / Credit_Limit`
- `상품당_관계밀도` = `Total_Relationship_Count / Months_on_book`
- `문의_대비_보유기간` = `Contacts_Count_12_mon / Months_on_book`
- `연령대` = 고객 연령 5구간 범주형 변수

누수 방지를 위해 `Total_Trans_Ct`, `Total_Ct_Chng_Q4_Q1`, `Target`을 제거하고,
활동성 갭 용도이므로 `Total_Trans_Amt`도 제거합니다. 결과는 다음과 같습니다.

~~~text
activity_gap = actual_total_trans_ct - expected_total_trans_ct
~~~

예상 거래건수는 음수가 될 수 없도록 0 미만을 0으로 보정합니다.

### 4.3 군집

`outputs/models/clustering_activity_gap.joblib`을 읽고 다음 두 컬럼을 표준화해
GMM(spherical) k=3에 전달합니다.

| 군집 입력 | 의미 |
|---|---|
| `예상_대비_거래_차이` | 활동성 갭 |
| `실제_거래건수` | 최근 12개월 실제 거래건수 |

군집 업무 라벨은 학습된 군집 평균의 활동성 갭 순서로 동적으로 지정합니다.

| 활동성 갭 평균 | 업무 라벨 |
|---|---|
| 가장 낮음 | `우선케어(거래 감소)` |
| 중간 | `일반관리(유지)` |
| 가장 높음 | `우량(예상이상)` |

GMM의 `predict_proba().max(axis=1)`은 `cluster_confidence`로 저장합니다.

## 5. 위험도와 추천 액션

CLI 기본 위험도 기준은 다음과 같습니다.

| 이탈 확률 | `risk_level` |
|---|---|
| `0.85 이상` | `high` |
| `0.50 이상 0.85 미만` | `medium` |
| `0.50 미만` | `low` |

기준은 CLI 인자로 변경할 수 있지만 `0 <= medium < high <= 1` 조건을 만족해야
합니다. 추천 액션은 확률과 활동성 갭을 조합해 생성합니다.

- 고위험 + 음의 갭: 이탈 위험 우선 상담 및 거래 활성화 혜택
- 고위험 + 양의 갭: 이탈 위험 고객 상담 및 관계 유지
- 활동성 갭 하위 20%: 저활동 고객 재활성화 캠페인
- 저위험 + 우량 군집: 우량 고객 업셀링 검토
- 그 외: 일반 유지 관리

사유 코드는 원본 특성의 운영 신호를 설명하기 위해 JSON 배열로 저장합니다.
예시는 `low_transaction_activity`, `transaction_decline`, `long_inactivity`,
`frequent_contacts`, `low_relationship_count`, `below_expected_activity`입니다.
활동성 갭 하위 분위수에는 `priority_activity_gap`, 그보다 크면서 음수인 값에는
`below_expected_activity`를 기록합니다. 신호가 없으면 `stable_activity`를
기록합니다. 하위 분위수 기본값은 0.2이며 CLI에서 조정할 수 있습니다.

## 6. 실행 방법

### 6.1 모델 artifact 생성

분류 artifact가 먼저 준비되어 있어야 합니다. 회귀와 군집은 다음 순서로
실행합니다.

~~~bash
project_venv/bin/python src/classification.py
project_venv/bin/python src/final/regression_final.py
project_venv/bin/python src/final/clustering_final.py
~~~

`backend/requirements.txt`에는 회귀 artifact를 읽기 위한 `lightgbm`이 포함되어
있으며, Docker 이미지에는 LightGBM의 Linux OpenMP 런타임인 `libgomp1`이
설치됩니다.

### 6.2 Docker에서 배치 실행

~~~bash
docker compose up -d --build
docker compose exec backend python -m backend.scripts.import_customers
docker compose exec backend python -m backend.scripts.run_analysis_batch
~~~

위 명령은 호스트의 `outputs/models`와 `data`를 Backend 컨테이너에 읽기 전용으로
마운트한 상태에서 실행됩니다. DB 접속은 컨테이너 내부 주소인 `mysql:3306`을
사용하므로 Mac 호스트 포트 `3307`과 혼동하지 않습니다.

위험도 기준을 직접 지정하려면 다음처럼 실행합니다.

~~~bash
docker compose exec backend python -m backend.scripts.run_analysis_batch \
  --medium-threshold 0.5 \
  --high-threshold 0.85 \
  --activity-gap-quantile 0.2 \
  --as-of-date 2026-08-01
~~~

`--as-of-date`를 생략하면 UTC 기준 오늘 날짜를 사용합니다. 미래 날짜는 허용하지
않습니다. 오늘 날짜는 현재 `customers`를 입력으로 사용하지만 과거 날짜는 그
날짜에 이미 저장된 `customer_feature_snapshots`만 사용합니다. 과거 스냅샷이
없으면 현재 고객값을 과거값으로 가장하지 않고 실행을 거부합니다.

## 7. 재실행과 이력 정책

기본 실행은 기준일·세 artifact SHA-256·선택된 고객 입력 전체의 정규화된
SHA-256·의사결정 정책 SHA-256을 묶은 `reuse_key_sha256`을 계산합니다. 동일한
논리 키의 성공 배치에서 세 `model_runs`와 고객별 결과가 완전할 때만 기존 배치를
재사용합니다. 실패한 배치는 덮어쓰지 않고 같은 재사용 키의 다음
`attempt_number`로 재시도합니다. `batch_key_sha256`은 각 시도마다 고유합니다.

새로운 분석 스냅샷을 강제로 만들려면 `--force`를 사용합니다.

~~~bash
docker compose exec backend python -m backend.scripts.run_analysis_batch --force
~~~

`--force` 실행은 새로운 `scoring_batches` 1건, `model_runs` 3건과
`customer_insights` 전체 고객 행을 새로 추가합니다. 기존 결과를 삭제하거나
덮어쓰지 않으며 같은 논리 키의 다음 실행 시도로 기록됩니다.

## 8. 저장 결과

성공한 배치는 다음을 저장합니다.

### `decision_policies` 1건

동일한 정책 hash를 중복 저장하지 않고, 위험도 기준·활동성 갭 분위수뿐 아니라
사유 코드, 추천 액션, 군집 라벨과 회귀 입력 계약 전체를 `policy_json`에 보존합니다.

### `scoring_batches` 1건

- `batch_key_sha256`
- `reuse_key_sha256`, `attempt_number`
- `as_of_date`
- `source_dataset_sha256`
- `dataset_sha256`
- `decision_policy_id`
- `status`, `processed_rows`, `started_at`, `completed_at`

### `model_runs` 3건

| task | 내용 |
|---|---|
| `classification` | manifest 기본 분류 모델, manifest 생성 시각, artifact hash |
| `regression` | `Voting` 회귀 Pipeline hash |
| `clustering` | 활동성 갭 GMM artifact hash |

각 실행은 `running`으로 기록한 뒤 성공하면 `succeeded`, 오류가 나면
`failed`와 오류 메시지를 남깁니다. 각 실행에는 고객 입력 데이터 해시와 함께
`decision_policy_sha256`, `medium_threshold`, `high_threshold`,
`activity_gap_quantile`도 저장합니다.

### `customer_insights` 고객별 1행

- `customer_id`
- `customer_snapshot_id` (분석 당시 19개 입력 특성 참조)
- `scoring_batch_id`
- `as_of_date`
- 세 `model_runs` 참조 ID
- `churn_probability`, `risk_level`
- `expected_transaction_count`, `activity_gap`
- `cluster_name`, `cluster_confidence`
- `recommended_action`, `reason_codes`
- `scored_at`

### `customer_feature_snapshots`

고객 특성이 수정돼도 분석 결과의 입력을 재현할 수 있도록 고객별 특성 조합과
`as_of_date`를 SHA-256으로 식별해 보존합니다. 동일 고객·동일 특성·동일 기준일은
중복 저장하지 않으며, 특성이 바뀌거나 기준일이 달라진 뒤 다음 배치를 실행하면
새 스냅샷이 생성됩니다.

`campaign_targets`는 배치가 자동으로 생성하지 않습니다. 분석 결과를 확인한 뒤
후속 캠페인 기능에서 필요한 고객만 캠페인 대상으로 전환하는 구조입니다.

## 9. 실제 검증 결과

2026-08-01 Docker MySQL에서 P0 migration과 새 정책 배치를 적용한 뒤 다음 결과를
확인했습니다.

| 항목 | 결과 |
|---|---:|
| 처리 고객 수 | 10,127 |
| 최신 scoring batch | 1 (ID 1, 기준일 2026-08-01) |
| 이번 배치 성공 `model_runs` | 3 (ID 7, 8, 9) |
| `decision_policies` | 1 |
| `customer_insights` | 10,127 |
| `customer_feature_snapshots` | 10,127 |
| 스냅샷 연결 인사이트 | 10,127 |
| `campaign_targets` | 0 |
| high | 1,519 |
| medium | 253 |
| low | 8,355 |
| 우선케어(거래 감소) | 3,578 |
| 일반관리(유지) | 5,464 |
| 우량(예상이상) | 1,085 |

정책 해시는 `a93df6843d0d2f558b96a32f65c8ee5120272dbf90ab30b167359c3076de3dfe`이며,
중위험 0.5·고위험 0.85·활동성 갭 하위 분위수 0.2가 기록됐습니다. 동일 명령을
다시 실행했을 때 scoring batch ID 1과 model run ID 7·8·9를 그대로 반환하고
`reused_existing_snapshot: true`가 되는 것도 확인했습니다. Backend `/ready`는
`model_loaded: true`로 응답했습니다.

## 10. 테스트

~~~bash
project_venv/bin/python -m pytest backend/tests -q
~~~

현재 Backend 테스트는 31개이며 다음을 포함합니다.

- 온라인·배치 분류 결과의 양성 확률 일관성
- 회귀 입력의 파생변수와 누수 컬럼 제거
- 위험도 구간과 추천 액션 규칙
- 실패 배치의 새 시도 생성과 과거 스냅샷 강제
- 최신 스냅샷 선택, 인증, 필터·페이지네이션·상세 조회 API
- migration, 고객 upsert, 인증, 모델 manifest 무결성 검증

## 11. 분석 대시보드 연계 현황

`customer_insights` 최신 결과·상세·이력 조회 API, 최신 모델 배치 상태 API,
캠페인 대상 생성·처리 API와 역할별 변경 권한이 구현되었습니다. API 사용법은
[`customer_insights_api.md`](customer_insights_api.md)에 정리되어 있습니다.
React 고객 분석 대시보드는 이 API를 사용해 고위험 고객 바로가기, CSV 내보내기,
분석 이력과 캠페인 처리 큐를 제공합니다. 모델 성능 Streamlit 대시보드 통합은
현재 범위에서 제외합니다.

# P2 캠페인 성과 측정

캠페인 처리 결과를 단순 문자열로만 남기지 않고, 대상군·대조군 배정과
전환·유지·비용을 같은 데이터 시점에서 집계하는 기능입니다. 성과 원천은
`campaign_targets`이며, 캠페인별 실험 정책과 비용 기준은 `campaigns`에
저장됩니다.

## 구현 범위

- 캠페인별 A/B 테스트 활성화와 대조군 비율 설정
- 고객 ID와 캠페인 seed를 이용한 재현 가능한 무작위 그룹 배정
- `treatment` 대상군과 `control` 대조군 저장
- 구조화된 결과 코드와 결과 변경 이벤트 기록
- 대상별 접촉·완료·전환 시각 저장
- 유지 여부와 유지 관측 시각 저장
- 고정 비용·접촉당 비용·전환당 매출 저장
- 전환율·유지율·증분효과·ROI 서버 집계
- 캠페인·세그먼트·담당자별 성과 비교
- 캠페인 상세 화면의 성과 대시보드와 대상 처리 UI

## A/B 그룹 배정

캠페인의 `experiment_enabled`가 true이고 `control_group_ratio`가 0보다 크면
신규 캠페인은 대상 등록 시 다음 값을 입력으로 SHA-256 해시를 계산합니다.

```text
experiment_seed : customer_id
```

해시를 0부터 1 사이의 bucket으로 변환하고, bucket이 `control_group_ratio`보다
작으면 대조군으로 배정합니다. 그 외에는 대상군으로 배정합니다. 일괄 타기팅을
취소하고 새 캠페인으로 재실행해도 같은 seed·고객은 같은 그룹을 유지합니다.
기존 캠페인은 과거 배정을 바꾸지 않도록 `seed : campaign_id : customer_id`
방식(`sha256_campaign_customer_v1`)을 유지하고, 신규 캠페인은
`sha256_seed_customer_v1`을 사용합니다.

대조군은 실제 접촉하지 않는 기준 집단입니다.

- 대조군 대상은 담당자 배정과 `assigned`·`contacted`·`completed` 상태 전이가
  차단됩니다.
- 대조군은 자연 발생 전환·유지 결과를 기록할 수 있습니다.
- 대상군은 기존 업무 흐름인 `pending → assigned → contacted → completed`를
  따릅니다.
- A/B 테스트를 사용하지 않는 캠페인은 모든 대상이 대상군입니다.
- 대상이 한 건이라도 생성되면 실험 여부, 대조군 비율, seed, 세그먼트와 재무
  정책은 서버에서 변경을 차단합니다.

## 구조화된 결과 코드

`campaign_targets.result_code`는 다음 코드 중 하나를 사용합니다.

| 코드 | 의미 | 일반적인 상태 |
|---|---|---|
| `contacted` | 접촉이 시작됨 | `contacted` 또는 `completed` |
| `converted` | 목표 행동·상품 전환 | `completed`(대상군), 대조군은 관측 결과로 기록 가능 |
| `declined` | 제안을 거절함 | `completed`(대상군) |
| `no_response` | 접촉했으나 응답 없음 | `completed`(대상군) |
| `opted_out` | 마케팅 수신 거부 | `completed`(대상군), 고객 수신 거부도 true로 보정 |

기존 데이터 호환을 위해 `not_converted`, `invalid_contact`도 계속 허용합니다.
`result` 자유 입력 필드는 상담 메모·상세 사유를 위해 유지하고, 집계·필터에는
`result_code`를 사용합니다.

## 지표 계산 기준

취소된 대상은 성과 분모에서 제외합니다. 모든 비율은 0과 1 사이의 실수로
API가 반환하고 화면은 백분율로 표시합니다.

### 전환율

```text
전환율 = 전환 대상 수 / 취소되지 않은 전체 대상 수
대상군 전환율 = 대상군 전환 수 / 대상군 수
대조군 전환율 = 대조군 전환 수 / 대조군 수
```

전환은 `converted = true` 또는 `result_code = converted`인 대상입니다.

### 접촉률

```text
접촉률 = 접촉 대상 수 / 취소되지 않은 전체 대상 수
```

대상군의 `contacted_at`, `contacted`·`completed` 상태, 구조화된 결과 코드를
호환 기준으로 사용합니다. 대조군은 접촉률 계산에서 항상 제외되도록 서버가
강제합니다.

### 유지율

유지 여부를 아직 관측하지 않은 대상은 유지율 분모에서 제외합니다. 대상군은
완료 시각, 대조군은 캠페인 시작 시각(없으면 대상 생성 시각)부터
`retention_window_days`가 지난 뒤에만 관측 가능한 대상으로 인정합니다.

```text
유지율 = retained = true인 대상 수 / retained가 기록된 대상 수
유지 관측률 = retained가 기록된 관측 수 / 관측 기간이 성숙한 대상 수
```

API는 `retention_eligible_count`, `retention_observed_count`,
`retention_observation_rate`를 함께 반환합니다. 관측 기간 전 입력은 거부하며,
실제 유지 결과가 없으면 `retention_rate = null`일 수 있습니다.

### 증분효과

대조군이 존재할 때만 계산합니다.

```text
증분 전환효과 = 대상군 전환율 - 대조군 전환율
증분 유지효과 = 대상군 유지율 - 대조군 유지율
```

대조군이 없거나 유지 관측값이 부족하면 해당 값은 `null`입니다. 이는 효과가
0이라는 뜻이 아니라, 비교할 기준 집단이나 관측 표본이 아직 없다는 뜻입니다.

### 비용·매출·ROI

캠페인 비용 정책은 다음 세 필드로 구성됩니다.

| 필드 | 계산 기준 |
|---|---|
| `fixed_cost` | 캠페인마다 한 번 더함. 담당자 비교에서는 전체 대상 수 비율로 배분 |
| `cost_per_contact` | 실제 접촉 대상 수마다 더함 |
| `revenue_per_conversion` | 개별 `outcome_revenue`가 없을 때 전환마다 적용 |
| `outcome_revenue` | 대상별 실제 매출. 입력되면 캠페인 기본 매출보다 우선 |

```text
총 비용 = 캠페인별 고정 비용 합계 + 접촉 대상별 접촉 비용 합계
관측 매출 = 대상군·대조군에서 관측한 전환 매출 합계
증분 전환 수 = 대상군 전환 수 - 대조군 전환율 × 대상군 수
증분 매출 = 증분 전환 수 × 대상군 평균 전환 가치
증분 ROI = (증분 매출 - 총 비용) / 총 비용
```

대조군이 없으면 대상군 관측 매출을 증분 매출로 사용합니다. 대조군의 자연 전환
매출은 `observed_revenue`에는 보이지만 캠페인 귀속 매출과 ROI에는 넣지 않습니다.
담당자 필터·비교는 대조군이 특정 담당자에게 배정되지 않더라도 해당 캠페인 전체
대조군 전환율을 기준선으로 사용합니다.
총 비용이 0이면 ROI는 `null`입니다. 음수 비용·매출 입력은 차단하며 금액 컬럼은
`NUMERIC(18, 2)`로 저장합니다.

## API

모든 성과 API는 로그인한 사용자에게 읽기 권한을 제공합니다. 분석팀도 성과를
조회할 수 있지만 캠페인·대상 변경 권한은 별도 역할 정책을 따릅니다.

### 전체·필터 성과

```http
GET /api/v1/campaign-performance
GET /api/v1/campaign-performance?campaign_id=12
GET /api/v1/campaign-performance?segment=high_risk_retention
GET /api/v1/campaign-performance?assigned_to_user_id=7
```

응답의 `summary`는 요청 필터가 적용된 전체 성과이며, 다음 비교 목록도 함께
반환됩니다.

- `by_campaign`: 캠페인별 성과
- `by_segment`: `segment_code`별 성과
- `by_assignee`: 담당자별 성과. 대조군·미배정 대상은 `unassigned`로 집계

### 특정 캠페인 성과

```http
GET /api/v1/campaigns/{campaign_id}/performance
```

캠페인 상세 화면이 사용하는 전용 조회 경로입니다.

### 캠페인 생성·수정 입력 예시

```json
{
  "name": "8월 고위험 리텐션 A/B",
  "status": "draft",
  "experiment_enabled": true,
  "control_group_ratio": 0.2,
  "fixed_cost": 50000,
  "cost_per_contact": 1200,
  "revenue_per_conversion": 30000,
  "retention_window_days": 30
}
```

세그먼트 일괄 타기팅 preview도 동일한 A/B·비용·유지 관측 필드를 받아
`bulk_targeting_runs.rules_json`에 고정하고, 실행 시 캠페인 정책으로 복사합니다.
취소 후 재실행하면 이 정책도 그대로 복사됩니다.

### 대상 결과 입력 예시

```http
PATCH /api/v1/campaign-targets/101
```

```json
{
  "status": "completed",
  "result_code": "converted",
  "converted": true,
  "outcome_revenue": 42000
}
```

유지 관측 기간이 지난 뒤에는 별도 PATCH로 `{"retained": true}` 또는
`{"retained": false}`를 기록합니다. 대상군은 완료 전 전환·유지 처리할 수
없습니다. 대조군은 접촉 상태로 변경할 수 없지만 자연 발생한 전환·유지 관측값은
관리자가 기록할 수 있습니다. 모든 변경은
`campaign_events`의 구조화된 metadata에 결과 코드, 전환 여부, 유지 여부,
매출, 실험 그룹과 함께 남습니다.

## 데이터베이스 변경

Alembic `20260801_0008`이 다음을 추가합니다.

| 테이블 | 필드 | 목적 |
|---|---|---|
| `campaigns` | `segment_code` | 성과 세그먼트 비교 키 |
| `campaigns` | `experiment_enabled`, `control_group_ratio`, `experiment_seed` | A/B 배정 정책 |
| `campaigns` | `fixed_cost`, `cost_per_contact`, `revenue_per_conversion` | ROI 비용·매출 정책 |
| `campaigns` | `retention_window_days` | 유지 관측 기준 기간 |
| `campaign_targets` | `experiment_group` | 대상군·대조군 구분 |
| `campaign_targets` | `contacted_at`, `completed_at`, `converted_at` | 성과 시점 보존 |
| `campaign_targets` | `retained`, `retention_checked_at` | 유지 결과와 관측 시점 |
| `campaign_targets` | `outcome_revenue` | 고객별 실제 매출 |

`20260802_0009`는 A/B 배정 알고리즘 버전과 `NUMERIC(18, 2)` 금액 타입을,
`20260802_0010`은 MySQL 금액 컬럼의 서버 기본값 `0`을 추가합니다. 기존 캠페인
대상은 `experiment_group = treatment`, 비용은 0, 유지 여부는
미관측(`NULL`)으로 backfill됩니다. 기존 결과 코드 제약은 구조화된 `contacted`,
`opted_out`를 포함하도록 확장됩니다.

## 화면 사용 흐름

캠페인 관리 화면에서 캠페인을 선택하면 대상 운영 화면 위에 성과 대시보드가
표시됩니다.

1. 상단 카드에서 전환율·유지율·증분 전환효과·ROI를 확인합니다.
2. 대상군·대조군 수와 접촉률·비용·매출을 확인합니다.
3. 캠페인·세그먼트·담당자별 비교표에서 상대 성과를 확인합니다.
4. 운영팀은 대상 목록에서 결과 코드, 전환, 유지 여부, 실제 매출을 기록합니다.
5. 기록이 저장되면 성과 대시보드가 다시 조회되어 최신 수치를 반영합니다.

## 검증

```bash
./project_venv/bin/python -m pytest backend/tests -q
PATH=/Users/geonwookim/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH \
  /Users/geonwookim/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm \
  --dir frontend run typecheck
```

성과 전용 테스트는 A/B 그룹, 구조화된 전환, 유지율, 증분효과와 ROI를 함께
검증합니다.

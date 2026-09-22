# P1 세그먼트 기반 일괄 타기팅

분석 배치가 저장한 `customer_insights`를 담당자가 한 명씩 등록하지 않고,
업무 세그먼트 규칙으로 캠페인 대상까지 변환하는 기능입니다. 타기팅 실행 전
미리보기에서 대상 수와 제외 사유를 확인하고, 실행하면 `draft` 캠페인과
`campaign_targets`가 하나의 배치(`bulk_targeting_runs`)로 연결됩니다.

## 구현 범위

| 세그먼트 | 대상 규칙 | 우선순위 |
|---|---|---|
| 고위험 리텐션 | `risk_level = high` | `churn_probability` 내림차순, 활동성 갭 오름차순 |
| 중위험 재활성화 | `risk_level = medium` AND `activity_gap`이 최신 결과의 하위 20% 분위수 이하 | 활동성 갭 오름차순, 이탈 확률 내림차순 |
| 저위험 우량군 업셀링 | `risk_level = low` AND `cluster_name = 우량(예상이상)` | 예상 거래건수 내림차순, 활동성 갭 내림차순 |

모든 세그먼트는 성공한 `scoring_batches` 한 건을 먼저 선택하고 그 배치에 속한
분석 결과만 사용합니다. `source_as_of_date`를 지정하면 해당 기준일 이하에서 가장
최신인 성공 배치를, `scoring_batch_id`를 지정하면 그 배치를 고정합니다. 서로 다른
모델·정책 배치의 고객 결과가 한 미리보기에 섞이지 않습니다. 중위험 재활성화의
분위수와 실제 계산된 threshold도 같은 배치에서 계산해
`bulk_targeting_runs.rules_json`에 저장합니다.

## 자동 제외와 중복 방지

다음 순서로 제외 사유를 분류해 집계합니다.

1. `customers.marketing_opt_out = true`: 수신 거부 고객
2. `contacted` 상태이거나 현재 세그먼트와 우선순위가 같거나 높은 활성 캠페인을
   보유한 고객: 활성 캠페인 보유
3. `customers.last_contacted_at`이 최근 접촉 제외 기간 안이거나, 기존 데이터의
   `contacted`·`completed` 대상 `processed_at`이 같은 기간 안인 고객: 최근 접촉
4. 나머지만 eligible 대상

미리보기에서 평가한 전체 후보, 제외 사유, 순위와 최종 선택 여부는
`bulk_targeting_candidates`에 고정합니다. 실행은 DB를 다시 스캔해 다른 대상을
선택하지 않고 이 스냅샷만 사용합니다. 다만 실행 직전에 고객 행을 잠그고 수신
거부·최근 접촉·활성 캠페인을 재검증해 그 사이 변경된 고객은 안전하게 건너뜁니다.
동시에 여러 배치가 실행되어도 한 고객이 두 개의 활성 캠페인에 등록되지 않습니다.

자동 캠페인 우선순위는 고위험 리텐션, 중위험 재활성화, 저위험 업셀링 순입니다.
상위 캠페인은 아직 접촉하지 않은 하위 자동 캠페인 대상을 취소하고 대체할 수
있습니다. 이미 접촉한 대상, 동급·상위 대상, 수동·미분류 캠페인은 자동으로
취소하지 않습니다. `max_targets`를 초과하는 후보는 정렬 후 뒤 순위부터 선택하지
않습니다.

`contacted` 또는 `completed`로 대상이 처리되면 `customers.last_contacted_at`이
자동 갱신됩니다. 수신 거부 상태는 `admin`만 변경할 수 있고, 신규 고객의 기본값은
`false`입니다.

## 배치 상태와 취소 정책

```text
previewed ── execute ──> executed
    │                      │
    └──── cancel ──────────┘
             │
             ▼
          cancelled ── rerun ──> 새 previewed 배치
```

- `previewed`: 정책과 제외 집계를 저장했지만 캠페인·대상은 아직 생성하지 않은 상태
- `executed`: `draft` 캠페인과 대상이 생성된 상태
- `cancelled`: 미리보기 폐기 또는 실행된 배치의 `pending`·`assigned` 대상 취소
- 이미 `contacted`·`completed`인 대상은 취소해도 되돌리지 않습니다.
- 재실행은 원래 배치를 수정하지 않고 `rerun_of_id`를 가진 새 미리보기를 만듭니다.

실행으로 생성한 캠페인은 바로 고객 접촉을 시작하지 않도록 `draft`로 생성됩니다.
담당자는 캠페인 상세 화면에서 검토 후 `scheduled` 또는 `active`로 변경합니다.

## API

모든 엔드포인트는 로그인 사용자가 필요합니다. 미리보기 생성·실행·취소·재실행은
`admin`, `marketing`만 가능합니다. `analyst`, `operations`는 조회만 가능합니다.

### 미리보기 생성

```http
POST /api/v1/campaign-targeting/preview
```

```json
{
  "segment": "medium_reactivation",
  "campaign_name": "8월 중위험 재활성화",
  "description": "활동성 하락 고객 재활성화",
  "channel": "전화",
  "assigned_to_user_id": 12,
  "recent_contact_days": 30,
  "activity_gap_quantile": 0.2,
  "max_targets": 500,
  "source_as_of_date": "2026-08-01",
  "scoring_batch_id": 12
}
```

`scoring_batch_id`는 선택값이며 생략하면 기준일 이하 최신 성공 배치를 사용합니다.
응답에는 `eligible_count`, `preview_count`, `skipped_active_campaign_count`,
`skipped_recent_contact_count`, `skipped_opt_out_count`, 그리고 최대 대상 수까지의
`items`가 포함됩니다. `rules`에는 실제 적용된 activity-gap threshold가 포함되어
미리보기와 실행의 정책이 달라지지 않습니다.

### 실행·취소·재실행

```text
POST /api/v1/campaign-targeting/runs/{run_id}/execute
POST /api/v1/campaign-targeting/runs/{run_id}/cancel
POST /api/v1/campaign-targeting/runs/{run_id}/rerun
GET  /api/v1/campaign-targeting/runs/{run_id}
GET  /api/v1/campaign-targeting/runs
```

재실행 시에는 선택적으로 캠페인 이름과 최대 대상 수만 덮어쓸 수 있습니다.

```json
{
  "campaign_name": "8월 재활성화 재실행",
  "max_targets": 300
}
```

### 수신 거부 상태 변경

```http
PATCH /api/v1/customers/{customer_id}/contact-preferences
```

```json
{
  "marketing_opt_out": true
}
```

이 API는 `admin` 전용이며, true인 고객은 모든 세그먼트의 자동 타기팅에서 제외됩니다.

## 데이터 구조

Alembic `20260801_0007`에서 실행 기반을 추가했고, 성과 측정은
`20260801_0008`, 재현성 보완은 `20260802_0009`에서 연결했습니다.

| 변경 | 내용 |
|---|---|
| `customers.marketing_opt_out` | 수신 거부 여부, 기본 `false` |
| `customers.last_contacted_at` | 최근 접촉 자동 기록 시각 |
| `bulk_targeting_runs` | 세그먼트·정책 JSON·실행 상태·제외 집계·재실행 계보 |
| `campaign_targets.bulk_targeting_run_id` | 대상이 어느 일괄 타기팅에서 생성됐는지 연결 |
| `bulk_targeting_runs.scoring_batch_id` | 후보 산출에 사용한 성공 분석 배치 |
| `bulk_targeting_candidates` | 미리보기 당시 후보·순위·제외·선택·실행 결과 스냅샷 |

`rules_json`에는 세그먼트, 캠페인 정보, 최근 접촉 기간, 분위수,
activity-gap threshold, 우량군 이름, 최대 대상 수, 기준일, A/B 대조군 비율,
비용·매출 정책과 유지 관측 기간이 저장됩니다. 따라서
후속 정책이 변경되어도 과거 실행 배치의 의사결정 근거를 확인할 수 있습니다.
실험 seed 원문은 API에 노출하지 않고 배정 정책 버전과 seed hash만 반환합니다.

일괄 타기팅 실행 시 캠페인의 A/B 정책이 대상 등록에 적용됩니다. 대조군은
담당자 배정 없이 `pending`으로 남고, 대상군만 활성 운영팀 담당자에게 배정됩니다.
성과 지표 계산 기준은 [`campaign_performance.md`](campaign_performance.md)에
정리되어 있습니다.

## 프론트엔드 사용 흐름

캠페인 관리 화면에서 관리자·마케팅 계정으로 로그인하면 상단의
`세그먼트 일괄 타기팅` 패널을 사용할 수 있습니다.

1. 세그먼트와 캠페인 기본 정보를 입력합니다.
2. `미리보기 생성`을 눌러 등록 가능 수와 세 가지 제외 집계를 확인합니다.
3. 고객 샘플을 확인한 뒤 `대상 등록 실행`을 누릅니다.
4. 생성된 draft 캠페인은 기존 캠페인 목록과 상세 대상 큐에서 검토합니다.
5. 실행을 취소하거나 같은 정책으로 다시 시도해야 하면 `일괄 타기팅 취소`와
   `취소 정책 재실행`을 사용합니다.

분석팀은 고객 분석과 캠페인 결과를 조회할 수 있지만 자동 타기팅을 실행할 수
없습니다. 운영팀은 생성된 대상의 담당자 배정과 접촉·처리 결과를 관리합니다.

## 검증

```bash
./project_venv/bin/python -m pytest backend/tests -q
PATH=/Users/geonwookim/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH \
  /Users/geonwookim/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm \
  --dir frontend run typecheck
```

백엔드에는 migration 검증과 함께 수신 거부·활성 캠페인 제외, 실행, 취소,
재실행 및 대상 연결을 검증하는 `test_bulk_targeting.py`가 포함되어 있습니다.

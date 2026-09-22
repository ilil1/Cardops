# customer_insights 조회 API

## 목적

로그인한 사용자가 고객별 최신 분석 스냅샷을 조회할 수 있도록 제공하는
Backend API입니다. 같은 고객의 과거 분석 결과가 여러 건 있어도 가장 최근
`scored_at` 결과 하나만 반환합니다.

모든 경로는 HttpOnly JWT 인증 쿠키가 필요합니다. 분석 결과·이력·배치 상태와
캠페인 목록·이벤트는 모든 활성 사용자가 조회할 수 있습니다. 업무 변경 권한은
역할별 책임에 따라 분리합니다.

| 역할 | 캠페인 생성·수정 | 대상 등록 | 대상 상태·결과 처리 | 조회 |
|---|---:|---:|---:|---:|
| `admin` | 가능 | 가능 | 가능 | 가능 |
| `marketing` | 가능 | 가능 | 불가 | 가능 |
| `operations` | 불가 | 불가 | 가능 | 가능 |
| `analyst` | 불가 | 불가 | 불가 | 가능 |

관리자는 예외 처리를 포함한 전체 권한을 갖습니다. 마케팅팀은 캠페인 기획과
타깃 등록을 담당하고, 운영팀은 실제 고객 접촉과 처리 결과를 담당합니다.

활성 팀 계정 목록은 다음 경로에서 조회합니다. 운영·마케팅 화면은 이 목록을
캠페인 담당자 선택에 사용하며, 관리자만 비활성 계정까지 포함할 수 있습니다.

~~~http
GET /api/v1/auth/users
~~~

표시 이름, 아이디, 역할과 활성 상태를 반환하며, 비밀번호 해시는 반환하지
않습니다. `include_inactive=true`는 관리자 외 역할에서 `403 Forbidden`을 반환합니다.

관리자는 다음 경로로 역할과 계정 활성 상태를 변경할 수 있습니다.

~~~http
PATCH /api/v1/auth/users/{user_id}
Content-Type: application/json

{
  "role": "marketing",
  "is_active": true
}
~~~

자기 계정 비활성화는 차단하며, 활성 관리자가 한 명뿐인 경우 마지막 관리자
권한 제거·비활성화도 차단합니다.

## 목록 조회

~~~http
GET /api/v1/customer-insights
~~~

### Query 파라미터

| 파라미터 | 기본값 | 설명 |
|---|---:|---|
| `risk_level` | 없음 | `low`, `medium`, `high` |
| `cluster_name` | 없음 | 예: `우선케어(거래 감소)` |
| `customer_id` | 없음 | 고객 ID 정확히 검색 |
| `campaign_candidates_only` | `false` | 수신 거부·최근 접촉·활성 캠페인 대상 고객을 제외하고 등록 가능한 후보만 조회 |
| `campaign_id` | 없음 | 후보를 등록할 캠페인 ID. 지정하면 해당 캠페인이 대체할 수 없는 동일/상위 우선순위 활성 대상만 제외 |
| `sort_by` | `churn_probability` | `churn_probability`, `activity_gap`, `expected_transaction_count`, `scored_at` |
| `sort_order` | `desc` | `asc`, `desc` |
| `page` | `1` | 1 이상의 페이지 번호 |
| `page_size` | `50` | 1~100 |

예시:

~~~bash
curl -b cookies.txt \
  'http://127.0.0.1:8000/api/v1/customer-insights?campaign_candidates_only=true&campaign_id=3&risk_level=high&page=1&page_size=20'
~~~

### 응답 구조

~~~json
{
  "items": [
    {
      "id": 1,
      "customer_id": 123456789,
      "classification_run_id": 1,
      "regression_run_id": 2,
      "clustering_run_id": 3,
      "churn_probability": 0.91,
      "risk_level": "high",
      "expected_transaction_count": 42.5,
      "activity_gap": -18.5,
      "cluster_name": "우선케어(거래 감소)",
      "cluster_confidence": 0.88,
      "recommended_action": "이탈 위험 우선 상담 및 거래 활성화 혜택",
      "reason_codes": ["transaction_decline", "below_expected_activity"],
      "scored_at": "2026-08-01T08:00:00"
    }
  ],
  "page": 1,
  "page_size": 20,
  "total": 1519,
  "total_pages": 76,
  "stats": {
    "total": 1519,
    "average_churn_probability": 0.91,
    "risk_counts": {
      "high": 1519
    },
    "cluster_counts": {
      "우선케어(거래 감소)": 1519
    },
    "cluster_options": {
      "우선케어(거래 감소)": 1519,
      "일반관리(유지)": 2840,
      "우량(예상이상)": 768
    }
  }
}
~~~

`stats`는 현재 필터가 적용된 전체 결과를 기준으로 계산되므로 대시보드의
요약 카드와 차트에 사용할 수 있습니다. `cluster_counts`는 선택된 군집까지
반영한 현재 결과의 분포이고, `cluster_options`는 `cluster_name` 필터를
제외한 나머지 조건에서 선택 가능한 군집 목록입니다. 따라서 군집 하나를
선택한 뒤에도 다른 군집으로 바로 변경할 수 있습니다.

## 고객 상세 조회

~~~http
GET /api/v1/customer-insights/{customer_id}
~~~

상세 응답은 목록 항목에 다음 `customer` 객체와 `customer_snapshot` 객체를
추가합니다.

- 고객 ID
- 19개 모델 입력 특성
- 고객 생성·수정 시각
- 최신 분석 결과와 세 모델 실행 ID
- `customer_snapshot`: 해당 분석이 실제로 사용한 19개 입력 특성
- `customer_snapshot.as_of_date`: 분석 기준일
- `customer_snapshot.feature_sha256`: 입력 특성 무결성 hash

신규 배치로 생성된 결과에는 `scoring_batch_id`와 `as_of_date`도 포함됩니다.
`customer_snapshot`이 없는 과거 레거시 결과는 해당 필드가 `null`일 수 있습니다.

분석 결과가 없는 고객은 `404 Not Found`를 반환합니다.

## 고객 분석 이력

~~~http
GET /api/v1/customer-insights/history/{customer_id}?limit=24
~~~

한 고객의 분석 스냅샷을 최신순으로 반환합니다. 같은 고객의 이탈 확률,
활동성 갭, 군집 결과가 시간에 따라 어떻게 바뀌었는지 상세 패널의 이력
영역에서 확인할 때 사용합니다. `limit`은 1~100 사이입니다.

## 최신 모델 배치 상태

~~~http
GET /api/v1/model-runs/latest
~~~

분류·회귀·군집별 가장 최근 성공 실행을 하나의 배치로 묶어 반환합니다.
신규 분석 배치는 다음 계보 메타데이터를 함께 제공합니다.

| 필드 | 설명 |
|---|---|
| `scoring_batch_id` | 세 모델 실행과 고객 인사이트를 묶는 배치 ID |
| `as_of_date` | 분석에 사용한 업무 기준일 |
| `decision_policy_id` | 위험 등급·활동성 갭 정책 ID |
| `decision_policy_sha256` | 정책 버전과 기준값을 식별하는 hash |

각 `runs[]` 항목에도 `scoring_batch_id`와 정책 hash·기준값이 포함됩니다.
대시보드는 데이터 갱신 시각, 기준일, 처리 행 수, 모델 버전을 표시할 수
있습니다. 성공한 실행 이력이 없으면 `404 Not Found`를 반환합니다.

## 캠페인 도메인 API

### 캠페인 생성·목록·상세

~~~http
POST /api/v1/campaigns
Content-Type: application/json

{
  "name": "고위험 고객 리텐션",
  "description": "고위험 고객 대상 상담 및 혜택 안내",
  "channel": "phone",
  "status": "draft",
  "start_at": "2026-08-05T00:00:00Z",
  "end_at": "2026-08-31T23:59:59Z"
}
~~~

캠페인 상태는 `draft`, `scheduled`, `active`, `paused`, `completed`,
`cancelled`입니다. 허용된 상태 전이는 다음과 같습니다.

| 현재 상태 | 허용되는 다음 상태 |
|---|---|
| `draft` | `scheduled`, `active`, `cancelled` |
| `scheduled` | `active`, `paused`, `cancelled` |
| `active` | `paused`, `completed`, `cancelled` |
| `paused` | `active`, `completed`, `cancelled` |
| `completed`, `cancelled` | 없음 |

~~~http
GET /api/v1/campaigns?status=active&page=1&page_size=20
GET /api/v1/campaigns/{campaign_id}
PATCH /api/v1/campaigns/{campaign_id}
~~~

캠페인 목록과 상세 응답에는 서버가 계산한 다음 집계가 포함됩니다.

```json
{
  "total_targets": 120,
  "unprocessed_targets": 42,
  "contacted_targets": 78,
  "converted_targets": 16,
  "status_counts": {
    "pending": 30,
    "assigned": 12,
    "contacted": 40,
    "completed": 38,
    "cancelled": 0
  }
}
```

### 캠페인 대상 등록

~~~http
POST /api/v1/campaign-targets
Content-Type: application/json

{
  "customer_insight_id": 42,
  "campaign_id": 3,
  "assigned_to_user_id": 7
}
~~~

기존 클라이언트 호환을 위해 `campaign_name`만 전달하는 요청도 지원합니다.
이 경우 같은 이름의 캠페인을 재사용하거나 안전한 초기 상태인 `draft` 캠페인을
자동 생성합니다.
새 클라이언트는 `campaign_id` 사용을 권장합니다.

담당자는 반드시 활성 상태의 `operations` 역할이어야 합니다.
`admin`과 `analyst`, 비활성 계정은 담당자로 지정할 수 없습니다.

`POST /api/v1/campaign-targets`는 `admin`, `marketing`만 호출할 수 있습니다.
`PATCH /api/v1/campaign-targets/{target_id}`는 `admin`, `operations`만 호출할
수 있습니다. 권한이 없는 역할의 직접 API 요청도 `403 Forbidden`으로 차단합니다.

동일 고객이 이미 접촉됐거나 동급·상위·수동 활성 캠페인에 등록되어 있으면
등록을 거부합니다. 상위 자동 세그먼트는 아직 접촉하지 않은 하위 자동 캠페인을
취소하고 대체할 수 있습니다. 고객 행 잠금과 DB unique 제약을 함께 사용해 동시
요청에서도 같은 캠페인·고객 중복을 차단합니다.

### 대상 상태 변경·결과 기록

~~~http
PATCH /api/v1/campaign-targets/{target_id}
Content-Type: application/json

{
  "status": "completed",
  "result": "혜택 안내 완료",
  "result_code": "converted",
  "converted": true,
  "result_notes": "앱 푸시 발송 후 상담 완료"
}
~~~

대상 상태 전이는 `pending → assigned → contacted → completed` 순서를 따릅니다.
각 단계에서 `cancelled`로 종료할 수 있으며, 완료·취소 후에는 변경할 수 없습니다.
`converted`는 `completed` 상태에서만 true로 설정할 수 있습니다.

### 캠페인별 대상 조회

~~~http
GET /api/v1/campaigns/{campaign_id}/targets?status=contacted&page=1&page_size=50
GET /api/v1/campaign-targets?campaign_id=3&assigned_to_user_id=7&converted=true
~~~

캠페인, 담당자, 고객, 대상 상태, 전환 여부 기준의 서버 필터와 페이지네이션을
지원합니다. 응답에는 필터 결과 기준의 전체 대상·미처리·접촉 완료·전환 집계가
포함됩니다.

부서 대시보드의 `캠페인 처리 현황`은 `page_size=8`로 조회하고, 응답의
`total`·`total_pages`로 페이지를 이동합니다. 화면에는 한 번에 8건만 표시되지만
전체 업무 수와 상태별 집계는 서버 기준으로 유지됩니다.

### 캠페인 이벤트 이력

~~~http
GET /api/v1/campaigns/{campaign_id}/events?page=1&page_size=50
GET /api/v1/campaigns/{campaign_id}/events?campaign_target_id=42
~~~

캠페인 생성, 대상 생성, 담당자 배정, 상태 전이, 결과·전환 변경 이력을 수행자와
함께 반환합니다. 이벤트는 삭제·수정하지 않고 누적해 업무 감사 이력으로 사용합니다.

## 인증과 오류

| 상태 코드 | 상황 |
|---|---|
| `200` | 조회 성공 |
| `401` | 인증 쿠키 없음·만료·비활성 사용자 |
| `404` | 해당 고객의 최신 분석 결과 없음 |
| `403` | 역할별 캠페인·대상 변경 권한 없음 |
| `409` | 같은 캠페인 대상이 이미 등록됨 |
| `422` | 잘못된 필터·페이지·정렬 파라미터 |
| `503` | DB가 설정되지 않음 |

## 대시보드 사용 예

대시보드는 다음 요청으로 초기 데이터를 가져올 수 있습니다.

~~~ts
const response = await fetch(
  "/api/v1/customer-insights?sort_by=churn_probability&sort_order=desc&page_size=50",
  { credentials: "include" },
);
const data = await response.json();
~~~

목록에서 고객을 선택하면 `/api/v1/customer-insights/{customer_id}`를 호출해
상세 패널을 구성합니다.

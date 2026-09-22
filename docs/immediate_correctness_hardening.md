# 보안·시점·캠페인 정확성 강화

## 목적

P0 데이터 시점, P1 캠페인·일괄 타기팅, P2 성과 측정 구현을 실제 운영에
적용하기 전에 데이터가 조용히 달라지거나 권한·성과가 잘못 해석될 수 있는
문제를 우선 수정했습니다. 관련 스키마 변경은 Alembic
`20260802_0009_immediate_correctness.py`와 금액 기본값을 보정하는
`20260802_0010_campaign_money_defaults.py`에 반영했습니다.

## 1. 분석 시점과 배치 복구

### 과거 기준일 입력

- 오늘 기준 배치는 현재 `customers`를 입력으로 사용합니다.
- 과거 `as_of_date` 배치는 해당 날짜에 저장된
  `customer_feature_snapshots`만 사용합니다.
- 과거 스냅샷이 없으면 현재 고객값을 과거값처럼 저장하지 않고 배치를
  거부합니다.
- 인사이트와 최신 배치 조회는 실행 시각보다 `as_of_date`를 먼저 비교합니다.
  늦게 적재한 과거 백필이 최신 업무 결과를 덮지 않습니다.

### 정책과 재사용 키

`decision_policies.policy_json`에 임계값뿐 아니라 사유 코드, 추천 액션,
군집 라벨과 회귀 입력 계약을 함께 저장합니다. 이 JSON 전체가 정책 SHA-256에
포함되므로 문구나 규칙이 달라지면 이전 배치를 잘못 재사용하지 않습니다.

`scoring_batches`는 다음 두 식별자를 분리합니다.

| 필드 | 의미 |
|---|---|
| `reuse_key_sha256` | 기준일·입력·정책·모델 artifact가 같은 논리 배치 |
| `attempt_number` | 같은 논리 배치의 실행 시도 번호 |
| `batch_key_sha256` | 개별 실행 시도의 고유 키 |

성공한 동일 논리 배치는 재사용하고, 실패한 배치는 이력을 보존한 채 다음
`attempt_number`로 다시 실행할 수 있습니다. `--force`도 새 시도로 기록됩니다.
모델 실행 ID는 DB flush 뒤 수집하므로 실패 처리 시 실제 실행 행을 정확히
`failed`로 갱신합니다.

## 2. 캠페인 권한과 생명주기

### 역할 분리

| 작업 | 허용 역할 |
|---|---|
| 캠페인 생성·수정·일괄 타기팅 | `admin`, `marketing` |
| 대상 배정·접촉·처리 | `admin`, `operations` |
| 실제 담당자 지정 | 활성 `operations` 계정만 |
| 조회 | 인증된 사용자 |

운영 담당자는 본인에게 배정됐거나 미배정인 대상만 처리할 수 있으며, 미배정
대상은 본인에게만 가져올 수 있습니다. 운영 담당자는 A/B 대조군 결과를 수동
수정할 수 없습니다. 관리자는 전체 권한을 유지합니다.

### 캠페인 상태

- 캠페인은 항상 `draft`로 생성한 뒤 별도 상태 전이로 활성화합니다.
- `scheduled`는 미래 `start_at`이 필요합니다.
- 미래 시작일이나 지난 종료일을 가진 캠페인은 `active`로 바꿀 수 없습니다.
- 대상 접촉·완료는 `active` 캠페인에서만 허용합니다.
- 미처리 대상군이 남은 캠페인은 `completed`로 닫을 수 없습니다.
- 캠페인을 `cancelled`로 바꾸면 열린 대상도 함께 취소합니다.
- `completed`·`cancelled` 캠페인의 기본 정책은 변경할 수 없습니다.
- 캠페인의 일부 날짜만 수정해도 다른 날짜가 의도치 않게 NULL이 되지 않습니다.

### 대상 상태와 결과

- 상태 전이 규칙과 담당자 필수 조건을 서버에서 검증합니다.
- 완료된 대상군은 최종 구조화 결과 코드가 반드시 필요합니다.
- `converted` 결과 코드와 전환 여부·전환 시각을 일관되게 맞춥니다.
- `opted_out` 결과는 고객 수신 거부 상태에도 반영됩니다.
- `retained`는 `true`, `false`, 미관측 `null`을 구분합니다.
- 유지 관측 기간이 지나기 전에는 `true`·`false` 모두 기록할 수 없습니다.
- 대상별 매출은 전환된 대상에만 기록할 수 있고, NULL로 다시 지울 수 있습니다.

## 3. 접촉 적격성과 1인 1활성 캠페인

수동 등록과 일괄 등록이 동일한 서버 규칙을 사용합니다.

1. 마케팅 수신 거부 고객 제외
2. 최근 30일 접촉 고객 제외
3. 동일 캠페인·고객 중복 제외
4. 다른 열린 캠페인과 우선순위 비교

세그먼트 우선순위는 고위험 리텐션, 중위험 재활성화, 저위험 업셀링 순입니다.
높은 우선순위는 아직 접촉하지 않은 낮은 우선순위 대상을 취소하고 대체할 수
있습니다. 이미 접촉했거나 우선순위가 같거나 높은 대상은 대체할 수 없습니다.
수동·미분류 캠페인은 자동 취소하지 않는 보수적 최상위 우선순위로 취급합니다.

동일 고객 동시 등록은 고객 행 잠금으로 직렬화하고, 같은 캠페인·고객 조합에는
DB unique 제약을 추가했습니다. `last_contacted_at`은 첫 접촉값에 고정하지 않고
실제 최근 처리 시각으로 갱신합니다.

## 4. 일괄 타기팅 재현성

미리보기 생성 시 하나의 성공 `scoring_batch_id`를 선택합니다. 후보는 이 배치의
인사이트만 사용하므로 서로 다른 모델 배치가 섞이지 않습니다.

`bulk_targeting_candidates`에는 다음 내용을 저장합니다.

- 고객과 근거 인사이트 ID
- 미리보기 당시 순위
- 적격·선택 여부
- 수신 거부·활성 캠페인·최근 접촉 제외 사유
- 실행 결과(`pending`, `created`, `skipped`, `cancelled`)
- 생성된 캠페인 대상 ID

실행 API는 후보를 다시 계산하지 않고 저장된 선택 후보를 사용합니다. 다만 실행
직전에 수신 거부·최근 접촉·활성 캠페인을 다시 확인해 새로 부적격해진 고객은
안전하게 건너뜁니다. 실행·취소는 배치 행 잠금으로 직렬화되며 같은 실행 요청은
중복 캠페인을 만들지 않습니다.

재실행은 원본 `scoring_batch_id`, 정책과 실험 seed를 이어받습니다. 새 캠페인은
`sha256_seed_customer_v1` 배정 방식을 사용해 캠페인 ID가 달라져도 같은 고객의
A/B 그룹이 유지됩니다. 기존 캠페인은 마이그레이션 시
`sha256_campaign_customer_v1`로 표시해 과거 배정과의 호환성을 보존합니다.
원본 seed는 API로 노출하지 않고 정책 버전과 seed SHA-256만 반환합니다.

## 5. 성과 측정 정확성

### 유지율

- 대상군: `completed_at + retention_window_days` 이후 관측 가능
- 대조군: `campaign.start_at` 또는 대상 생성일을 기준으로 관측 가능
- `retention_eligible_count`: 관측 기간이 성숙한 대상 수
- `retention_observed_count`: 성숙 대상 중 true·false가 입력된 수
- `retention_observation_rate`: 관측 수 / 관측 가능 수
- `retention_rate`: 유지 true 수 / 실제 관측 수

관측 기간 전에 잘못 입력된 값은 지표 계산에도 포함하지 않습니다.

### 매출과 ROI

`observed_revenue`는 대상군과 대조군에서 실제 관측한 전체 전환 매출입니다.
대조군의 자연 전환 매출은 캠페인 귀속 매출로 계산하지 않습니다.

```text
증분 전환 수 = 대상군 전환 수 - 대조군 전환율 × 대상군 수
증분 매출 = 증분 전환 수 × 대상군 평균 전환 가치
증분 ROI = (증분 매출 - 총 비용) / 총 비용
```

A/B 대조군이 없는 캠페인은 대상군 관측 매출을 귀속 매출로 사용합니다. 담당자별
비교에서는 캠페인 고정 비용을 대상 수 비율로 배분해 같은 고정 비용이 담당자마다
중복 합산되지 않게 했습니다. 대조군이 미배정 행으로 분리돼도 담당자별 ROI는
캠페인 전체 대조군 전환율을 공통 기준으로 사용합니다. 금액 컬럼은 `FLOAT`에서
`NUMERIC(18, 2)`로 변경해 통화 합산 오차를 줄였습니다.

## 6. 인증 보안과 감사

- 로그인 실패는 사용자·IP 조합 5회, IP 전체 30회/15분을 기본 한도로 제한합니다.
- 제한값은 `LOGIN_MAX_ATTEMPTS`, `LOGIN_IP_MAX_ATTEMPTS`,
  `LOGIN_RATE_WINDOW_SECONDS`로 설정합니다.
- 존재하지 않는 계정도 더미 Argon2 검증을 수행해 계정 존재 여부의 시간 차이를
  줄입니다.
- 성공 시 오래된 Argon2 파라미터의 해시를 자동 갱신합니다.
- 가입 요청, 로그인 성공·실패·제한, 로그아웃, 계정 권한 변경은 `auth_events`에
  사용자·IP·시각·구조화 metadata와 함께 기록합니다.
- 활성 관리자 목록을 행 잠금한 뒤 변경해 동시 요청으로 마지막 관리자가 사라지는
  문제를 방지합니다.

## 7. 로컬 테스트 계정

테스트 계정 비밀번호는 소스에 저장하지 않습니다. 다음 조건을 모두 만족해야
시드 스크립트가 실행됩니다.

1. `ALLOW_TEST_USER_SEEDING=true`
2. `APP_ENV=local`, `development`, `test` 중 하나
3. DB가 SQLite 또는 `127.0.0.1`, `localhost`, `mysql` 호스트
4. 역할별 `TEST_*_PASSWORD`가 각각 12자 이상

```env
APP_ENV=development
ALLOW_TEST_USER_SEEDING=true
TEST_ADMIN_PASSWORD=<local-only-password>
TEST_ANALYST_PASSWORD=<local-only-password>
TEST_OPERATIONS_PASSWORD=<local-only-password>
TEST_MARKETING_PASSWORD=<local-only-password>
```

Compose 컨테이너 환경은 생성 시 결정되므로 `.env`를 바꾼 뒤 Backend를 다시
생성합니다.

```bash
docker compose up -d --force-recreate backend
docker compose exec backend python -m backend.scripts.seed_test_users
```

시드가 끝나면 `ALLOW_TEST_USER_SEEDING=false`로 되돌리고 Backend를 다시
생성합니다.

## 8. 마이그레이션 주의사항

적용 전 DB를 백업하고 다음 중복 데이터를 먼저 확인해야 합니다.

```sql
SELECT campaign_id, customer_id, COUNT(*)
FROM campaign_targets
WHERE campaign_id IS NOT NULL
GROUP BY campaign_id, customer_id
HAVING COUNT(*) > 1;
```

중복이 있으면 `0009`는 임의 삭제하지 않고 실패합니다. 업무 담당자가 보존할 행을
결정한 뒤 다시 적용해야 합니다. 기존 일괄 미리보기에는 후보 스냅샷이 없으므로
마이그레이션 전에 만들어 두고 실행하지 않은 미리보기는 취소하고 새로 생성하는
것이 안전합니다.

`0010`은 MySQL에서 `FLOAT`를 `NUMERIC(18, 2)`로 바꿀 때 사라질 수 있는 캠페인
금액 컬럼의 서버 기본값 `0`을 복구합니다.

```bash
python -m backend.app.migration_runner
alembic -c backend/alembic.ini current
```

## 9. 검증

```bash
project_venv/bin/python -m pytest backend/tests -q
cd frontend
pnpm run lint
pnpm run typecheck
pnpm run test
pnpm run build
```

현재 검증 기준은 Backend 31개, Frontend 14개 테스트 통과입니다.

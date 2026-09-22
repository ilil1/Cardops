"""신규 세그먼트 4종으로 캠페인을 만들고 업무 흐름 4단계를 재현합니다.

`docs/campaign_workflow.md`에 정리한 상태 전이와 제약이 화면에서 실제로 어떻게
보이는지 확인할 수 있도록, 캠페인마다 **서로 다른 진행 단계**를 만듭니다.

  1) draft        — 타기팅만 해두고 아직 시작하지 않은 캠페인
  2) active       — 운영팀이 지금 처리 중 (대기/배정/접촉/완료가 섞여 있음)
  3) active       — 처리는 끝났지만 유지 관측 기간이 남아 결과 입력을 기다리는 상태
  4) completed    — 전환·유지·매출까지 모두 입력되어 성과 집계가 가능한 상태

실제 고객 원본은 건드리지 않고 캠페인·대상만 생성하며, 로컬 DB에서만 실행됩니다.
재실행하면 기존 시나리오 캠페인을 지우고 다시 만듭니다.

실행: python -m backend.scripts.seed_segment_scenarios
"""

from __future__ import annotations

import argparse
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.config import get_database_url
from backend.app.database import initialize_database
from backend.app.enums import (
    BulkTargetingSegment,
    CampaignEventType,
    CampaignLifecycleStatus,
    CampaignResultCode,
    CampaignStatus,
    ExperimentGroup,
)
from backend.app.models import (
    Campaign,
    CampaignEvent,
    CampaignTarget,
    Customer,
    CustomerInsight,
    User,
)
from backend.app.services.bulk_targeting_service import (
    DEFAULT_CAMPAIGN_DESCRIPTIONS,
    FULL_PAYER_ACTIVE_TRANSACTIONS,
    SMALL_BALANCE_LIMIT,
    STABLE_BALANCE_MAX,
    STABLE_BALANCE_MIN,
    TRANSACTION_DECLINE_RATIO,
)
from backend.app.services.campaign_service import assign_experiment_group
from backend.scripts.db_safety import validate_local_database


SCENARIO_PREFIX = "[시나리오]"
NOW = datetime.now(timezone.utc)
# 기본적으로 "집행 후 넉넉히 시간이 지난" 스냅샷을 만듭니다. 가장 긴 관측기간
# (안정 우량 90일)보다 커야 네 캠페인 모두 유지율·ROI가 집계됩니다.
DEFAULT_ELAPSED_DAYS = 120
# 대조군은 20%입니다. 100명이면 대조군 20명이라 유지율 정원의 반올림 단위가
# 5%p로 줄어, 설계한 증분 효과가 실행마다 부호를 바꾸지 않습니다.
DEFAULT_TARGETS_PER_CAMPAIGN = 100


@dataclass(frozen=True)
class ScenarioSpec:
    """캠페인 하나와 그 진행 단계를 정의합니다."""

    segment: BulkTargetingSegment
    title: str
    stage: str  # draft | in_progress | awaiting_retention | measured
    channel: str
    target_count: int
    # 캠페인 시작 시점(며칠 전). 유지 관측 기간과 함께 "관측이 끝났는지"를 결정하므로
    # 단계 의미에 맞게 지정해야 합니다 — measured는 완료일 + 관측기간이 이미 지나야
    # 성과 API가 유지율을 계산합니다.
    started_days_ago: int
    retention_window_days: int
    fixed_cost: float
    cost_per_contact: float
    revenue_per_conversion: float
    conversion_rate: float
    control_conversion_rate: float
    retention_rate: float
    control_retention_rate: float
    # 집행 후 시간이 꽤 지난 진행 중 캠페인인지. True면 대부분 처리가 끝나고
    # 일부만 잔여 물량으로 남은 모습으로 만듭니다(_advance가 설정).
    aged: bool = False


SCENARIOS = (
    ScenarioSpec(
        segment=BulkTargetingSegment.ACTIVE_FULL_PAYER,
        title="완납형 우량 고객 거래 활성화",
        # 마케팅이 대상만 뽑아두고 아직 실행 승인을 받지 않은 단계입니다.
        stage="draft",
        channel="앱 푸시",
        target_count=40,
        # 아직 시작 전 — 최근에 만들어둔 캠페인입니다.
        started_days_ago=3,
        retention_window_days=30,
        fixed_cost=150_000,
        cost_per_contact=800,
        revenue_per_conversion=60_000,
        # 원본 데이터 기준 이탈률 12%인 우량군입니다. 캠페인이 없어도 대부분
        # 남으므로 대조군 유지율이 이미 높고, 그만큼 증분 효과는 작습니다.
        # 다만 격차가 대조군 정원의 반올림 단위보다 작으면 증분이 음수로
        # 뒤집히므로(대조군 20명 기준 5%p), 최소 8%p는 벌려 둡니다.
        conversion_rate=0.22,
        control_conversion_rate=0.10,
        retention_rate=0.90,
        control_retention_rate=0.82,
    ),
    ScenarioSpec(
        segment=BulkTargetingSegment.SMALL_BALANCE_DECLINE,
        title="소액 잔액·거래 급감 컨택",
        # 운영팀이 지금 처리 중 — 대기/배정/접촉/완료가 섞여 있습니다.
        stage="in_progress",
        channel="전화",
        target_count=40,
        # 지금 처리 중 — 시작한 지 얼마 안 됐습니다.
        started_days_ago=6,
        retention_window_days=30,
        fixed_cost=200_000,
        cost_per_contact=4_500,
        revenue_per_conversion=110_000,
        # 이탈률 약 90%로 가장 위험한 군입니다. 컨택해도 상당수가 이탈하므로
        # 유지율 자체는 낮지만, 방치했을 때(대조군)와의 격차는 가장 큽니다.
        conversion_rate=0.30,
        control_conversion_rate=0.08,
        retention_rate=0.38,
        control_retention_rate=0.14,
    ),
    ScenarioSpec(
        segment=BulkTargetingSegment.STABLE_PRIME,
        title="안정 우량 고객 한도 상향 제안",
        # 처리 완료했지만 유지 관측 기간(90일)이 남아 아직 유지 여부를 못 넣습니다.
        stage="awaiting_retention",
        channel="이메일",
        target_count=40,
        # 처리는 끝났지만 관측기간 90일이 안 지나 유지 입력이 막힌 상태입니다.
        started_days_ago=20,
        retention_window_days=90,
        fixed_cost=120_000,
        cost_per_contact=1_200,
        revenue_per_conversion=140_000,
        # 이탈률 4.6%로 가장 안정적인 군입니다. 유지율은 양쪽 모두 높아
        # 리텐션 목적보다 업셀 매출로 성과를 판단해야 합니다.
        # 대조군은 20%뿐이라 정원 반올림이 거칩니다. 0.93을 주면 7명 기준
        # round(6.51)=7로 100%가 되어 증분 유지가 음수로 뒤집히므로, 반올림이
        # 한 명 아래로 떨어지는 값을 씁니다.
        conversion_rate=0.28,
        control_conversion_rate=0.11,
        retention_rate=0.95,
        control_retention_rate=0.86,
    ),
    ScenarioSpec(
        segment=BulkTargetingSegment.DORMANT_FULL_PAYER,
        title="완납형 저활동 고객 리텐션",
        # 전환·유지·매출까지 모두 관측이 끝나 성과 비교가 가능한 단계입니다.
        stage="measured",
        channel="전화",
        target_count=40,
        # 완료일(+2일) 기준 관측기간 30일이 이미 지나 유지율 집계가 가능합니다.
        started_days_ago=75,
        retention_window_days=30,
        fixed_cost=180_000,
        cost_per_contact=3_500,
        revenue_per_conversion=95_000,
        # 이탈률 72%입니다. 방치하면 대부분 이탈하므로(대조군 유지율 0.30)
        # 리텐션 캠페인의 증분 효과가 뚜렷하게 드러납니다.
        conversion_rate=0.26,
        control_conversion_rate=0.09,
        retention_rate=0.62,
        control_retention_rate=0.30,
    ),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--targets-per-campaign",
        type=int,
        default=None,
        help=(
            f"캠페인별 대상 수를 조정합니다(기본 {DEFAULT_TARGETS_PER_CAMPAIGN}, 최소 5)."
            " 대조군은 20%라 이 값이 작으면 유지율 정원의 반올림 단위가 커져"
            " 증분 효과가 실행마다 흔들립니다."
        ),
    )
    parser.add_argument(
        "--elapsed-days",
        type=int,
        default=DEFAULT_ELAPSED_DAYS,
        help=(
            f"캠페인 집행 후 며칠이 지난 시점으로 만들지 정합니다"
            f"(기본 {DEFAULT_ELAPSED_DAYS}). 0을 주면 초안·처리중·관측대기·측정완료"
            " 4단계가 섞인 진행 중 스냅샷을 만듭니다."
        ),
    )
    return parser


def _advance(spec: ScenarioSpec, elapsed_days: int) -> ScenarioSpec:
    """캠페인을 `elapsed_days`만큼 과거로 옮겨 관측이 끝난 상태로 만듭니다.

    유지 관측 자격은 `대상 완료일 + 관측기간 <= 현재`로 판정하므로(대조군은
    캠페인 시작일 기준), 시작일을 과거로 밀면 유지율과 ROI가 집계됩니다.
    0이면 원래의 진행 단계를 그대로 둡니다.

    다만 `in_progress` 캠페인 하나는 단계를 바꾸지 않고 날짜만 밉니다. 운영이
    지금 처리 중인 캠페인이 화면에 하나는 있어야 대기·배정·접촉·완료가 섞인
    목록과 미처리 병목을 확인할 수 있기 때문입니다.
    """
    if elapsed_days <= 0:
        return spec
    started_days_ago = spec.started_days_ago + elapsed_days
    if spec.stage == "in_progress":
        return replace(spec, started_days_ago=started_days_ago, aged=True)
    return replace(spec, stage="measured", started_days_ago=started_days_ago)


def _segment_filter(segment: BulkTargetingSegment):
    """세그먼트 정의와 동일한 조건으로 고객을 고릅니다.

    bulk_targeting_service._segment_condition과 같은 기준을 쓰되, 여기서는
    미리보기·제외 규칙 없이 시연용 대상만 뽑습니다.
    """
    if segment is BulkTargetingSegment.SMALL_BALANCE_DECLINE:
        return (
            Customer.total_revolving_bal > 0,
            Customer.total_revolving_bal < SMALL_BALANCE_LIMIT,
            Customer.total_ct_chng_q4_q1 < TRANSACTION_DECLINE_RATIO,
        )
    if segment is BulkTargetingSegment.DORMANT_FULL_PAYER:
        return (
            Customer.total_revolving_bal == 0,
            Customer.total_trans_ct < FULL_PAYER_ACTIVE_TRANSACTIONS,
        )
    if segment is BulkTargetingSegment.ACTIVE_FULL_PAYER:
        return (
            Customer.total_revolving_bal == 0,
            Customer.total_trans_ct >= FULL_PAYER_ACTIVE_TRANSACTIONS,
        )
    return (
        Customer.total_revolving_bal >= STABLE_BALANCE_MIN,
        Customer.total_revolving_bal < STABLE_BALANCE_MAX,
    )


def _latest_insight_by_customer(session: Session) -> dict[int, CustomerInsight]:
    """고객별 최신 분석 결과를 모읍니다(대상에 연결할 스냅샷)."""
    latest: dict[int, CustomerInsight] = {}
    for insight in session.scalars(select(CustomerInsight)).all():
        current = latest.get(insight.customer_id)
        if current is None or (
            (insight.as_of_date, insight.scored_at, insight.id)
            > (current.as_of_date, current.scored_at, current.id)
        ):
            latest[insight.customer_id] = insight
    return latest


def _remove_existing(session: Session) -> int:
    """이전에 만든 시나리오 캠페인을 지웁니다(재실행 가능하게)."""
    campaign_ids = session.scalars(
        select(Campaign.id).where(Campaign.name.like(f"{SCENARIO_PREFIX}%"))
    ).all()
    if not campaign_ids:
        return 0
    session.execute(
        delete(CampaignEvent).where(CampaignEvent.campaign_id.in_(campaign_ids))
    )
    session.execute(
        delete(CampaignTarget).where(CampaignTarget.campaign_id.in_(campaign_ids))
    )
    session.execute(delete(Campaign).where(Campaign.id.in_(campaign_ids)))
    return len(campaign_ids)


def _add_event(
    session: Session,
    *,
    campaign_id: int,
    target_id: int | None,
    event_type: CampaignEventType,
    actor_id: int | None,
    created_at: datetime,
    note: str,
    from_status: str | None = None,
    to_status: str | None = None,
) -> None:
    session.add(
        CampaignEvent(
            campaign_id=campaign_id,
            campaign_target_id=target_id,
            event_type=event_type.value,
            actor_user_id=actor_id,
            from_status=from_status,
            to_status=to_status,
            note=note,
            metadata_json={"scenario": True},
            created_at=created_at,
        )
    )


def _lifecycle_for(stage: str) -> CampaignLifecycleStatus:
    if stage == "draft":
        return CampaignLifecycleStatus.DRAFT
    if stage == "measured":
        return CampaignLifecycleStatus.COMPLETED
    return CampaignLifecycleStatus.ACTIVE


def _build_campaign(
    session: Session,
    spec: ScenarioSpec,
    *,
    admin: User | None,
    started_at: datetime,
) -> Campaign:
    lifecycle = _lifecycle_for(spec.stage)
    campaign = Campaign(
        name=f"{SCENARIO_PREFIX} {spec.title}",
        description=DEFAULT_CAMPAIGN_DESCRIPTIONS[spec.segment.value],
        channel=spec.channel,
        segment_code=spec.segment.value,
        status=lifecycle.value,
        start_at=None if spec.stage == "draft" else started_at,
        end_at=NOW if spec.stage == "measured" else None,
        experiment_enabled=True,
        control_group_ratio=0.2,
        experiment_seed=secrets.token_hex(16),
        experiment_assignment_version="sha256_seed_customer_v1",
        fixed_cost=spec.fixed_cost,
        cost_per_contact=spec.cost_per_contact,
        revenue_per_conversion=spec.revenue_per_conversion,
        retention_window_days=spec.retention_window_days,
        created_by_user_id=admin.id if admin else None,
        created_at=started_at,
        updated_at=NOW,
    )
    session.add(campaign)
    session.flush()
    _add_event(
        session,
        campaign_id=campaign.id,
        target_id=None,
        event_type=CampaignEventType.CREATED,
        actor_id=admin.id if admin else None,
        created_at=started_at,
        to_status=CampaignLifecycleStatus.DRAFT.value,
        note="시나리오 캠페인 생성",
    )
    if lifecycle is not CampaignLifecycleStatus.DRAFT:
        _add_event(
            session,
            campaign_id=campaign.id,
            target_id=None,
            event_type=CampaignEventType.STATUS_CHANGED,
            actor_id=admin.id if admin else None,
            created_at=started_at + timedelta(minutes=5),
            from_status=CampaignLifecycleStatus.DRAFT.value,
            to_status=CampaignLifecycleStatus.ACTIVE.value,
            note="캠페인 실행 시작",
        )
    return campaign


def _quota(rate: float, group_size: int) -> int:
    """비율을 그룹 크기에 맞는 실제 인원수로 환산합니다.

    `index % 100 < rate*100` 같은 방식은 그룹이 100명 미만이면 무너집니다
    (예: 40명이면 인덱스가 0~39라 62%든 41%든 전원이 조건을 만족).
    그룹 내 위치와 정원을 비교해야 의도한 비율이 나옵니다.
    """
    return int(round(rate * group_size))


def _target_plan(
    spec: ScenarioSpec,
    *,
    position: int,
    group_size: int,
    is_control: bool,
) -> dict:
    """진행 단계와 그룹 내 위치로 대상 하나의 최종 상태를 결정합니다.

    대조군은 접촉하지 않으므로 항상 pending으로 남습니다
    (campaign_service가 대조군의 assigned/contacted/completed를 금지합니다).
    """
    if spec.stage == "draft":
        return {"status": CampaignStatus.PENDING, "result_code": None, "converted": False}

    if is_control:
        # 대조군은 접촉하지 않으므로 pending으로 남지만, 캠페인과 무관하게
        # 자연 전환은 발생합니다. 이 값이 있어야 증분 효과(치료군 − 대조군)가
        # 의미를 갖습니다. 도메인 규칙상 "완료 후 전환" 제약은 치료군에만 적용됩니다.
        converted = position < _quota(spec.control_conversion_rate, group_size)
        return {
            "status": CampaignStatus.PENDING,
            "result_code": (
                CampaignResultCode.CONVERTED if converted else CampaignResultCode.NOT_CONVERTED
            ),
            "converted": converted,
        }

    if spec.stage == "in_progress":
        # 갓 시작한 캠페인은 4단계가 고르게 섞이지만(각 25%), 집행 후 시간이 지난
        # 캠페인은 대부분 처리가 끝나고 잔여 물량만 남습니다(완료 70%). 진척을
        # 실제 경과와 맞추지 않으면 미처리 대상이 치료군 전환율을 끌어내려
        # 대조군보다 낮아지고, 증분 효과가 음수로 뒤집힙니다.
        slots, completed_slots = (10, 7) if spec.aged else (4, 1)
        bucket = position % slots
        if bucket >= completed_slots:
            remainder = bucket - completed_slots
            if remainder == 0:
                return {
                    "status": CampaignStatus.CONTACTED,
                    "result_code": CampaignResultCode.CONTACTED,
                    "converted": False,
                }
            if remainder == 1:
                return {
                    "status": CampaignStatus.ASSIGNED,
                    "result_code": None,
                    "converted": False,
                }
            return {"status": CampaignStatus.PENDING, "result_code": None, "converted": False}
        # 완료된 대상 중 지정 비율만 전환 처리합니다.
        completed_position = (position // slots) * completed_slots + bucket
        completed_total = max(group_size * completed_slots // slots, 1)
        converted = completed_position < _quota(spec.conversion_rate, completed_total)
        return {
            "status": CampaignStatus.COMPLETED,
            "result_code": (
                CampaignResultCode.CONVERTED if converted else CampaignResultCode.NOT_CONVERTED
            ),
            "converted": converted,
        }

    # awaiting_retention / measured — 전부 처리 완료 상태입니다.
    converted = position < _quota(spec.conversion_rate, group_size)
    return {
        "status": CampaignStatus.COMPLETED,
        "result_code": (
            CampaignResultCode.CONVERTED if converted else CampaignResultCode.NOT_CONVERTED
        ),
        "converted": converted,
    }


def _create_targets(
    session: Session,
    spec: ScenarioSpec,
    campaign: Campaign,
    customers: list[Customer],
    insights: dict[int, CustomerInsight],
    *,
    admin: User | None,
    operations: User | None,
    started_at: datetime,
) -> dict[str, int]:
    counts = {"treatment": 0, "control": 0, "converted": 0, "retained": 0}
    contacted_at = started_at + timedelta(days=1)
    completed_at = started_at + timedelta(days=2)

    # 1단계 — 먼저 A/B 그룹을 확정합니다. 비율(전환·유지)을 그룹 크기 대비
    # 정원으로 환산하려면 각 그룹의 전체 인원을 미리 알아야 합니다.
    grouped: dict[str, list[Customer]] = {
        ExperimentGroup.TREATMENT.value: [],
        ExperimentGroup.CONTROL.value: [],
    }
    for customer in customers:
        grouped[assign_experiment_group(campaign, customer.customer_id)].append(customer)
    counts["treatment"] = len(grouped[ExperimentGroup.TREATMENT.value])
    counts["control"] = len(grouped[ExperimentGroup.CONTROL.value])

    # 2단계 — 그룹 내 위치로 상태·전환·유지를 배정합니다.
    ordered: list[tuple[Customer, str, int, int]] = []
    for group, members in grouped.items():
        for position, customer in enumerate(members):
            ordered.append((customer, group, position, len(members)))

    for customer, group, position, group_size in ordered:
        is_control = group == ExperimentGroup.CONTROL.value
        plan = _target_plan(
            spec, position=position, group_size=group_size, is_control=is_control
        )
        status = plan["status"]

        reached_contact = status in {CampaignStatus.CONTACTED, CampaignStatus.COMPLETED}
        is_completed = status is CampaignStatus.COMPLETED
        converted = bool(plan["converted"])

        # 유지 여부는 관측 기간이 지난 대상에만 입력합니다. 진행 중 캠페인도
        # 시작한 지 오래됐다면 이미 완료된 대상은 관측이 끝나므로 입력하고,
        # 아직 대기·배정·접촉 단계인 대상은 비워 둡니다(운영 잔여 물량).
        # 대조군은 캠페인 시작일이 기준이라 처리 상태와 무관하게 관측됩니다.
        retained: bool | None = None
        observation_done = spec.stage == "measured" or (
            # aged가 아닌 진행 중 캠페인은 아직 관측 기간이 지나지 않았으므로
            # 유지값을 남기지 않습니다(성과 API도 집계 대상에서 제외합니다).
            spec.stage == "in_progress" and spec.aged and (is_control or is_completed)
        )
        if observation_done:
            rate = spec.control_retention_rate if is_control else spec.retention_rate
            # 완료 대상은 그룹 안에 고르게 흩어져 있어(위치 % 4 == 3), 그룹 전체
            # 기준 정원을 그대로 써도 부분집합에서 목표 비율이 유지됩니다.
            retained = position < _quota(rate, group_size)
            if retained:
                counts["retained"] += 1
        if converted:
            counts["converted"] += 1

        target = CampaignTarget(
            customer_id=customer.customer_id,
            customer_insight_id=insights[customer.customer_id].id,
            campaign_id=campaign.id,
            campaign_name=campaign.name,
            experiment_group=group,
            assigned_to_user_id=(
                operations.id
                if (not is_control and status is not CampaignStatus.PENDING and operations)
                else None
            ),
            status=status.value,
            processed_at=completed_at if reached_contact else None,
            contacted_at=contacted_at if reached_contact else None,
            completed_at=completed_at if is_completed else None,
            converted_at=completed_at if converted else None,
            result=(
                "혜택 안내 후 전환" if converted
                else "혜택 안내 완료·미전환" if is_completed
                else "접촉 완료, 결과 대기" if reached_contact
                else None
            ),
            result_notes="시나리오 시연용 데이터이며 실제 고객 접촉 결과가 아닙니다.",
            result_code=plan["result_code"].value if plan["result_code"] else None,
            converted=converted,
            retained=retained,
            retention_checked_at=NOW if retained is not None else None,
            outcome_revenue=(
                round(spec.revenue_per_conversion * (0.9 + (position % 5) * 0.05), 2)
                if converted
                else None
            ),
            created_at=started_at,
            updated_at=NOW,
        )
        session.add(target)
        session.flush()

        _add_event(
            session,
            campaign_id=campaign.id,
            target_id=target.id,
            event_type=CampaignEventType.CREATED,
            actor_id=admin.id if admin else None,
            created_at=started_at,
            to_status=CampaignStatus.PENDING.value,
            note="시나리오 대상 생성",
        )
        if reached_contact:
            _add_event(
                session,
                campaign_id=campaign.id,
                target_id=target.id,
                event_type=CampaignEventType.STATUS_CHANGED,
                actor_id=operations.id if operations else None,
                created_at=contacted_at,
                from_status=CampaignStatus.ASSIGNED.value,
                to_status=CampaignStatus.CONTACTED.value,
                note="운영팀 접촉",
            )
        if is_completed:
            _add_event(
                session,
                campaign_id=campaign.id,
                target_id=target.id,
                event_type=CampaignEventType.STATUS_CHANGED,
                actor_id=operations.id if operations else None,
                created_at=completed_at,
                from_status=CampaignStatus.CONTACTED.value,
                to_status=CampaignStatus.COMPLETED.value,
                note="처리 완료",
            )
    return counts


def seed(
    session: Session, *, targets_per_campaign: int, elapsed_days: int = DEFAULT_ELAPSED_DAYS
) -> list[dict]:
    """시나리오 캠페인 4종을 생성합니다."""
    removed = _remove_existing(session)
    if removed:
        print(f"기존 시나리오 캠페인 {removed}개를 제거했습니다.")

    admin = session.scalar(
        select(User).where(User.role == "admin", User.is_active.is_(True)).order_by(User.id)
    )
    operations = session.scalar(
        select(User).where(User.role == "operations", User.is_active.is_(True)).order_by(User.id)
    )
    insights = _latest_insight_by_customer(session)
    if not insights:
        raise RuntimeError(
            "customer_insights가 비어 있습니다. 먼저 run_analysis_batch를 실행하세요."
        )

    used: set[int] = set()
    summaries: list[dict] = []
    for base_spec in SCENARIOS:
        spec = _advance(base_spec, elapsed_days)
        candidates = session.scalars(
            select(Customer).where(*_segment_filter(spec.segment)).order_by(Customer.customer_id)
        ).all()
        pool = [
            customer
            for customer in candidates
            if customer.customer_id not in used and customer.customer_id in insights
        ][:targets_per_campaign]
        if len(pool) < 5:
            print(
                f"[건너뜀] {spec.title}: 조건에 맞는 고객이 {len(pool)}명뿐입니다(최소 5명)."
            )
            continue
        used.update(customer.customer_id for customer in pool)

        started_at = NOW - timedelta(days=spec.started_days_ago)
        campaign = _build_campaign(session, spec, admin=admin, started_at=started_at)
        counts = _create_targets(
            session,
            spec,
            campaign,
            pool,
            insights,
            admin=admin,
            operations=operations,
            started_at=started_at,
        )
        summaries.append(
            {
                "campaign": campaign.name,
                "segment": spec.segment.value,
                "stage": spec.stage,
                "status": campaign.status,
                "targets": len(pool),
                **counts,
            }
        )
    session.commit()
    return summaries


def main() -> None:
    args = build_parser().parse_args()
    count = args.targets_per_campaign or DEFAULT_TARGETS_PER_CAMPAIGN
    if count < 5:
        raise ValueError("--targets-per-campaign must be at least 5.")
    elapsed_days = args.elapsed_days
    if elapsed_days < 0:
        raise ValueError("--elapsed-days must be zero or greater.")

    database_url = get_database_url()
    if not database_url:
        raise RuntimeError("DATABASE_URL must be configured before seeding scenarios.")
    validate_local_database(database_url)

    engine, session_factory = initialize_database(database_url)
    try:
        with session_factory() as session:
            summaries = seed(
                session, targets_per_campaign=count, elapsed_days=elapsed_days
            )
    finally:
        engine.dispose()

    if not summaries:
        print("생성된 시나리오가 없습니다.")
        return
    if elapsed_days > 0:
        print(f"\n집행 후 {elapsed_days}일이 지난 시점으로 생성했습니다(유지율·ROI 집계 가능).")
    else:
        print("\n진행 단계가 섞인 스냅샷으로 생성했습니다(일부 캠페인은 유지율이 비어 있습니다).")
    print("시나리오 캠페인 생성 완료:")
    for row in summaries:
        print(
            f"- [{row['stage']:18s}] {row['campaign']}\n"
            f"    상태={row['status']}  대상={row['targets']}"
            f" (대상군 {row['treatment']} / 대조군 {row['control']})"
            f"  전환={row['converted']}  유지={row['retained']}"
        )


if __name__ == "__main__":
    main()

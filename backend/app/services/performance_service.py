"""캠페인 A/B 실험·전환·유지·수익 성과를 서버에서 집계합니다."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..enums import CampaignStatus, ExperimentGroup
from ..models import Campaign, CampaignTarget, CustomerInsight, User


@dataclass(frozen=True)
class PerformanceMetrics:
    target_count: int
    treatment_count: int
    control_count: int
    contacted_count: int
    converted_count: int
    retained_count: int
    retention_eligible_count: int
    retention_observed_count: int
    retention_observation_rate: float | None
    contact_rate: float
    conversion_rate: float
    retention_rate: float | None
    treatment_contact_rate: float | None
    control_contact_rate: float | None
    treatment_conversion_rate: float | None
    control_conversion_rate: float | None
    treatment_retention_rate: float | None
    control_retention_rate: float | None
    incremental_conversion_effect: float | None
    incremental_retention_effect: float | None
    incremental_conversions: float
    total_cost: float
    observed_revenue: float
    incremental_revenue: float
    total_revenue: float
    roi: float | None


@dataclass(frozen=True)
class PerformanceRow:
    target: CampaignTarget
    campaign: Campaign
    assignee_label: str | None
    fixed_cost_share: float = 0.0
    cluster_name: str | None = None
    risk_level: str | None = None


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _optional_rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _is_contacted(target: CampaignTarget) -> bool:
    """치료군의 접촉만 접촉률에 포함하고, 기존 상태값도 호환합니다."""
    if target.experiment_group == ExperimentGroup.CONTROL.value:
        return False
    return bool(
        target.contacted_at is not None
        or target.status
        in {
            CampaignStatus.CONTACTED.value,
            CampaignStatus.COMPLETED.value,
        }
        or target.result_code
        in {
            "contacted",
            "converted",
            "not_converted",
            "no_response",
            "declined",
            "opted_out",
            "invalid_contact",
        }
    )


def _is_converted(target: CampaignTarget) -> bool:
    return bool(target.converted or target.result_code == "converted")


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _retention_is_eligible(row: PerformanceRow, now: datetime) -> bool:
    """치료군 완료일 또는 대조군 관측 시작일로 유지 관측 성숙 여부를 판단합니다."""
    anchor = (
        row.target.completed_at
        if row.target.experiment_group != ExperimentGroup.CONTROL.value
        else (row.campaign.start_at or row.target.created_at)
    )
    if anchor is None:
        return False
    return now >= _utc(anchor) + timedelta(days=row.campaign.retention_window_days)


def _conversion_revenue(row: PerformanceRow) -> float:
    if not _is_converted(row.target):
        return 0.0
    return float(
        row.target.outcome_revenue
        if row.target.outcome_revenue is not None
        else row.campaign.revenue_per_conversion
    )


def _incremental_financials(
    rows: list[PerformanceRow],
    benchmark_rows: list[PerformanceRow] | None = None,
) -> tuple[float, float]:
    """대조군 자연 전환을 제외한 증분 전환 수와 귀속 매출을 계산합니다."""
    incremental_conversions = 0.0
    incremental_revenue = 0.0
    grouped = _group_rows(rows, lambda row: str(row.campaign.id))
    benchmark_grouped = _group_rows(
        benchmark_rows if benchmark_rows is not None else rows,
        lambda row: str(row.campaign.id),
    )
    for campaign_rows in grouped.values():
        campaign = campaign_rows[0].campaign
        treatment_rows = [
            row
            for row in campaign_rows
            if row.target.experiment_group != ExperimentGroup.CONTROL.value
        ]
        control_rows = [
            row
            for row in benchmark_grouped.get(str(campaign.id), campaign_rows)
            if row.target.experiment_group == ExperimentGroup.CONTROL.value
        ]
        treatment_converted = sum(_is_converted(row.target) for row in treatment_rows)
        treatment_revenue = sum(_conversion_revenue(row) for row in treatment_rows)
        if campaign.experiment_enabled and treatment_rows and control_rows:
            control_rate = _rate(
                sum(_is_converted(row.target) for row in control_rows),
                len(control_rows),
            )
            campaign_incremental_conversions = (
                treatment_converted - control_rate * len(treatment_rows)
            )
            average_conversion_value = (
                treatment_revenue / treatment_converted
                if treatment_converted
                else float(campaign.revenue_per_conversion or 0.0)
            )
            campaign_incremental_revenue = (
                campaign_incremental_conversions * average_conversion_value
            )
        else:
            campaign_incremental_conversions = float(treatment_converted)
            campaign_incremental_revenue = treatment_revenue
        incremental_conversions += campaign_incremental_conversions
        incremental_revenue += campaign_incremental_revenue
    return incremental_conversions, incremental_revenue


def _group_rows(rows: Iterable[PerformanceRow], key_fn):
    grouped: dict[str, list[PerformanceRow]] = defaultdict(list)
    for row in rows:
        grouped[key_fn(row)].append(row)
    return grouped


def calculate_metrics(
    rows: list[PerformanceRow],
    *,
    now: datetime | None = None,
    benchmark_rows: list[PerformanceRow] | None = None,
) -> PerformanceMetrics:
    """대상 행 집합에 동일한 성과·비용 계산을 적용합니다."""
    target_count = len(rows)
    treatment_rows = [
        row
        for row in rows
        if row.target.experiment_group != ExperimentGroup.CONTROL.value
    ]
    control_rows = [
        row
        for row in rows
        if row.target.experiment_group == ExperimentGroup.CONTROL.value
    ]

    contacted_rows = [row for row in rows if _is_contacted(row.target)]
    converted_rows = [row for row in rows if _is_converted(row.target)]
    current = now or datetime.now(timezone.utc)
    eligible_retention_rows = [
        row for row in rows if _retention_is_eligible(row, current)
    ]
    observed_retention_rows = [
        row for row in eligible_retention_rows if row.target.retained is not None
    ]
    retained_rows = [row for row in observed_retention_rows if row.target.retained is True]

    treatment_contacted = sum(_is_contacted(row.target) for row in treatment_rows)
    control_contacted = sum(_is_contacted(row.target) for row in control_rows)
    treatment_converted = sum(_is_converted(row.target) for row in treatment_rows)
    control_converted = sum(_is_converted(row.target) for row in control_rows)
    treatment_eligible = [
        row for row in treatment_rows if _retention_is_eligible(row, current)
    ]
    control_eligible = [
        row for row in control_rows if _retention_is_eligible(row, current)
    ]
    treatment_observed_rows = [
        row for row in treatment_eligible if row.target.retained is not None
    ]
    control_observed_rows = [
        row for row in control_eligible if row.target.retained is not None
    ]
    treatment_retained = sum(row.target.retained is True for row in treatment_observed_rows)
    control_retained = sum(row.target.retained is True for row in control_observed_rows)
    treatment_observed = len(treatment_observed_rows)
    control_observed = len(control_observed_rows)

    total_cost = sum(row.fixed_cost_share for row in rows)
    total_cost += sum(
        float(row.campaign.cost_per_contact or 0.0) for row in contacted_rows
    )
    observed_revenue = sum(_conversion_revenue(row) for row in rows)
    incremental_conversions, incremental_revenue = _incremental_financials(
        rows,
        benchmark_rows,
    )
    roi = (
        (incremental_revenue - total_cost) / total_cost
        if total_cost > 0
        else None
    )

    treatment_conversion_rate = _optional_rate(
        treatment_converted,
        len(treatment_rows),
    )
    control_conversion_rate = _optional_rate(control_converted, len(control_rows))
    treatment_retention_rate = _optional_rate(treatment_retained, treatment_observed)
    control_retention_rate = _optional_rate(control_retained, control_observed)
    return PerformanceMetrics(
        target_count=target_count,
        treatment_count=len(treatment_rows),
        control_count=len(control_rows),
        contacted_count=len(contacted_rows),
        converted_count=len(converted_rows),
        retained_count=len(retained_rows),
        retention_eligible_count=len(eligible_retention_rows),
        retention_observed_count=len(observed_retention_rows),
        retention_observation_rate=_optional_rate(
            len(observed_retention_rows),
            len(eligible_retention_rows),
        ),
        contact_rate=_rate(len(contacted_rows), target_count),
        conversion_rate=_rate(len(converted_rows), target_count),
        retention_rate=_optional_rate(len(retained_rows), len(observed_retention_rows)),
        treatment_contact_rate=_optional_rate(treatment_contacted, len(treatment_rows)),
        control_contact_rate=_optional_rate(control_contacted, len(control_rows)),
        treatment_conversion_rate=treatment_conversion_rate,
        control_conversion_rate=control_conversion_rate,
        treatment_retention_rate=treatment_retention_rate,
        control_retention_rate=control_retention_rate,
        incremental_conversion_effect=(
            treatment_conversion_rate - control_conversion_rate
            if treatment_conversion_rate is not None
            and control_conversion_rate is not None
            else None
        ),
        incremental_retention_effect=(
            treatment_retention_rate - control_retention_rate
            if treatment_retention_rate is not None
            and control_retention_rate is not None
            else None
        ),
        incremental_conversions=incremental_conversions,
        total_cost=total_cost,
        observed_revenue=observed_revenue,
        incremental_revenue=incremental_revenue,
        total_revenue=incremental_revenue,
        roi=roi,
    )


def fetch_performance_rows(
    db: Session,
    *,
    campaign_id: int | None = None,
    segment_code: str | None = None,
    assigned_to_user_id: int | None = None,
) -> list[PerformanceRow]:
    """취소 대상을 제외한 성과 원천 데이터를 조회합니다."""
    query = (
        select(CampaignTarget, Campaign, User, CustomerInsight)
        .join(Campaign, Campaign.id == CampaignTarget.campaign_id)
        .outerjoin(User, User.id == CampaignTarget.assigned_to_user_id)
        .join(
            CustomerInsight,
            CustomerInsight.id == CampaignTarget.customer_insight_id,
        )
        .where(CampaignTarget.status != CampaignStatus.CANCELLED.value)
    )
    if campaign_id is not None:
        query = query.where(CampaignTarget.campaign_id == campaign_id)
    if segment_code is not None:
        query = query.where(Campaign.segment_code == segment_code)
    if assigned_to_user_id is not None:
        query = query.where(
            CampaignTarget.assigned_to_user_id == assigned_to_user_id
        )
    raw_rows = db.execute(query).all()
    campaign_ids = {campaign.id for _target, campaign, _assignee, _insight in raw_rows}
    campaign_target_counts: dict[int, int] = {}
    if campaign_ids:
        count_rows = db.execute(
            select(CampaignTarget.campaign_id, func.count(CampaignTarget.id))
            .where(
                CampaignTarget.campaign_id.in_(campaign_ids),
                CampaignTarget.status != CampaignStatus.CANCELLED.value,
            )
            .group_by(CampaignTarget.campaign_id)
        ).all()
        campaign_target_counts = {
            int(row_campaign_id): int(count)
            for row_campaign_id, count in count_rows
        }
    rows: list[PerformanceRow] = []
    for target, campaign, assignee, insight in raw_rows:
        campaign_target_count = campaign_target_counts.get(campaign.id, 0)
        rows.append(
            PerformanceRow(
                target=target,
                campaign=campaign,
                assignee_label=assignee.display_name if assignee is not None else None,
                fixed_cost_share=(
                    float(campaign.fixed_cost or 0.0) / campaign_target_count
                    if campaign_target_count
                    else 0.0
                ),
                cluster_name=insight.cluster_name,
                risk_level=insight.risk_level,
            )
        )
    return rows


def build_performance_breakdowns(
    rows: list[PerformanceRow],
    *,
    dimension: str,
    benchmark_rows: list[PerformanceRow] | None = None,
) -> list[dict[str, object]]:
    """세그먼트·캠페인·담당자별 비교 응답을 만듭니다."""
    if dimension == "campaign":
        grouped = _group_rows(rows, lambda row: str(row.campaign.id))
        labels = {
            key: group[0].campaign.name for key, group in grouped.items()
        }
    elif dimension == "segment":
        grouped = _group_rows(
            rows,
            lambda row: row.campaign.segment_code or "unsegmented",
        )
        labels = {
            key: ("미분류" if key == "unsegmented" else key)
            for key in grouped
        }
    elif dimension == "cluster":
        grouped = _group_rows(
            rows,
            lambda row: row.cluster_name or "unclustered",
        )
        labels = {
            key: ("미분류" if key == "unclustered" else key)
            for key in grouped
        }
    elif dimension == "risk_level":
        grouped = _group_rows(
            rows,
            lambda row: row.risk_level or "unclassified",
        )
        risk_level_labels = {
            "high": "높음 (고위험)",
            "medium": "주의 (중위험)",
            "low": "낮음 (저위험)",
        }
        labels = {
            key: risk_level_labels.get(key, "미분류")
            for key in grouped
        }
    else:
        grouped = _group_rows(
            rows,
            lambda row: (
                str(row.target.assigned_to_user_id)
                if row.target.assigned_to_user_id is not None
                else "unassigned"
            ),
        )
        labels = {
            key: (
                group[0].assignee_label
                if group[0].assignee_label is not None
                else "미배정"
            )
            for key, group in grouped.items()
        }

    result: list[dict[str, object]] = []
    for key in sorted(grouped):
        group = grouped[key]
        metrics = calculate_metrics(group, benchmark_rows=benchmark_rows)
        result.append(
            {
                **metrics.__dict__,
                "key": key,
                "label": labels[key],
                "campaign_count": len({row.campaign.id for row in group}),
            }
        )
    return result


def get_campaign_performance(
    db: Session,
    *,
    campaign_id: int | None = None,
    segment_code: str | None = None,
    assigned_to_user_id: int | None = None,
) -> dict[str, object]:
    """요약과 세 가지 비교 차원을 한 번에 반환합니다."""
    benchmark_rows = fetch_performance_rows(
        db,
        campaign_id=campaign_id,
        segment_code=segment_code,
        assigned_to_user_id=None,
    )
    rows = (
        [
            row
            for row in benchmark_rows
            if row.target.assigned_to_user_id == assigned_to_user_id
        ]
        if assigned_to_user_id is not None
        else benchmark_rows
    )
    return {
        "summary": calculate_metrics(rows, benchmark_rows=benchmark_rows),
        "by_campaign": build_performance_breakdowns(
            rows,
            dimension="campaign",
            benchmark_rows=benchmark_rows,
        ),
        "by_segment": build_performance_breakdowns(
            rows,
            dimension="segment",
            benchmark_rows=benchmark_rows,
        ),
        "by_assignee": build_performance_breakdowns(
            rows,
            dimension="assignee",
            benchmark_rows=benchmark_rows,
        ),
        "by_cluster": build_performance_breakdowns(
            rows,
            dimension="cluster",
            benchmark_rows=benchmark_rows,
        ),
        "by_risk_level": build_performance_breakdowns(
            rows,
            dimension="risk_level",
            benchmark_rows=benchmark_rows,
        ),
        "generated_at": datetime.now(timezone.utc),
    }

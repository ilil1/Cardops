"""A/B 그룹, 구조화된 결과, 유지율·증분효과·ROI 집계를 검증합니다."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.enums import (
    CampaignLifecycleStatus,
    CampaignResultCode,
    CampaignStatus,
    ExperimentGroup,
)
from backend.app.migration_runner import upgrade_database
from backend.app.models import Campaign, CampaignTarget
from backend.app.services.campaign_service import update_campaign_target
from backend.app.services.performance_service import get_campaign_performance

from test_bulk_targeting import _seed_database


def test_campaign_performance_calculates_ab_retention_incrementality_and_roi(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'campaign-performance.sqlite3'}"
    upgrade_database(database_url)
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            actor, insights = _seed_database(session)
            campaign = Campaign(
                name="A/B 리텐션 성과 캠페인",
                status=CampaignLifecycleStatus.ACTIVE.value,
                created_by_user_id=actor.id,
                experiment_enabled=True,
                control_group_ratio=0.5,
                experiment_seed="performance-test-seed",
                fixed_cost=100.0,
                cost_per_contact=10.0,
                revenue_per_conversion=200.0,
                segment_code="high_risk_retention",
                start_at=datetime.now(timezone.utc) - timedelta(days=31),
            )
            session.add(campaign)
            session.flush()
            treatment = CampaignTarget(
                customer_id=1,
                customer_insight_id=insights[0].id,
                campaign_id=campaign.id,
                campaign_name=campaign.name,
                experiment_group=ExperimentGroup.TREATMENT.value,
                assigned_to_user_id=actor.id,
                status=CampaignStatus.ASSIGNED.value,
            )
            control = CampaignTarget(
                customer_id=2,
                customer_insight_id=insights[1].id,
                campaign_id=campaign.id,
                campaign_name=campaign.name,
                experiment_group=ExperimentGroup.CONTROL.value,
                status=CampaignStatus.PENDING.value,
            )
            session.add_all([treatment, control])
            session.commit()

            update_campaign_target(
                session,
                target=treatment,
                status=CampaignStatus.CONTACTED,
                assignee=None,
                result=None,
                result_notes=None,
                result_code=None,
                converted=None,
                retained=None,
                outcome_revenue=None,
                actor=actor,
            )
            treatment.completed_at = datetime.now(timezone.utc) - timedelta(days=31)
            session.commit()
            update_campaign_target(
                session,
                target=treatment,
                status=CampaignStatus.COMPLETED,
                assignee=None,
                result=None,
                result_notes=None,
                result_code=CampaignResultCode.CONVERTED,
                converted=None,
                retained=True,
                outcome_revenue=250.0,
                actor=actor,
            )
            campaign.status = CampaignLifecycleStatus.COMPLETED.value
            session.commit()
            update_campaign_target(
                session,
                target=control,
                status=None,
                assignee=None,
                result=None,
                result_notes=None,
                result_code=CampaignResultCode.CONVERTED,
                converted=None,
                retained=True,
                outcome_revenue=None,
                actor=actor,
            )

            result = get_campaign_performance(session, campaign_id=campaign.id)
            summary = result["summary"]
            assert summary.target_count == 2
            assert summary.treatment_count == 1
            assert summary.control_count == 1
            assert summary.contacted_count == 1
            assert summary.converted_count == 2
            assert summary.retention_rate == 1.0
            assert summary.retention_eligible_count == 2
            assert summary.retention_observed_count == 2
            assert summary.retention_observation_rate == 1.0
            assert summary.incremental_conversion_effect == 0.0
            assert summary.incremental_retention_effect == 0.0
            assert summary.incremental_conversions == 0.0
            assert summary.total_cost == 110.0
            assert summary.observed_revenue == 450.0
            assert summary.incremental_revenue == 0.0
            assert summary.total_revenue == 0.0
            assert summary.roi == -1.0
            assert len(result["by_segment"]) == 1
            assert result["by_segment"][0]["key"] == "high_risk_retention"
            assert len(result["by_cluster"]) == 1
            assert result["by_cluster"][0]["key"] == "우선케어(거래 감소)"
            assert result["by_cluster"][0]["target_count"] == 2
            assert len(result["by_risk_level"]) == 1
            assert result["by_risk_level"][0]["key"] == "high"
            assert result["by_risk_level"][0]["label"] == "높음 (고위험)"
            assert result["by_risk_level"][0]["target_count"] == 2
            assignee_metrics = next(
                item
                for item in result["by_assignee"]
                if item["key"] == str(actor.id)
            )
            assert assignee_metrics["incremental_conversions"] == 0.0
            assert assignee_metrics["incremental_revenue"] == 0.0
            assert assignee_metrics["roi"] == -1.0

            filtered_result = get_campaign_performance(
                session,
                campaign_id=campaign.id,
                assigned_to_user_id=actor.id,
            )
            assert filtered_result["summary"].incremental_conversions == 0.0
            assert filtered_result["summary"].incremental_revenue == 0.0
            assert filtered_result["summary"].roi == -1.0
    finally:
        engine.dispose()

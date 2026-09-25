import { Injectable } from '@nestjs/common';
import { PerformanceRepository } from '../repositories/performance.repository';
import { Row, SEGMENTS, booleanValue, fail, numberValue, positiveId } from '../campaigns.shared';

type PerformanceRow = Row & { fixed_cost_share: number };

function rate(numerator: number, denominator: number): number { return denominator ? numerator / denominator : 0; }
function optionalRate(numerator: number, denominator: number): number | null { return denominator ? numerator / denominator : null; }
function isContacted(row: PerformanceRow): boolean {
  return row.experiment_group !== 'control' &&
    (row.contacted_at !== null || ['contacted', 'completed'].includes(row.status) ||
      ['contacted', 'converted', 'not_converted', 'no_response', 'declined', 'opted_out', 'invalid_contact'].includes(row.result_code));
}
function isConverted(row: PerformanceRow): boolean { return booleanValue(row.converted) || row.result_code === 'converted'; }
function eligible(row: PerformanceRow, now: number): boolean {
  const anchor = row.experiment_group === 'control' ? row.start_at ?? row.created_at : row.completed_at;
  return !!anchor && now >= new Date(anchor).getTime() + numberValue(row.retention_window_days, 30) * 86400000;
}
function revenue(row: PerformanceRow): number {
  return isConverted(row) ? numberValue(row.outcome_revenue, numberValue(row.revenue_per_conversion)) : 0;
}
function group(rows: PerformanceRow[], key: (row: PerformanceRow) => string): Map<string, PerformanceRow[]> {
  const grouped = new Map<string, PerformanceRow[]>();
  for (const row of rows) {
    const value = key(row);
    grouped.set(value, [...grouped.get(value) ?? [], row]);
  }
  return grouped;
}

function metrics(rows: PerformanceRow[], benchmark: PerformanceRow[], now: number): Row {
  const treatment = rows.filter((row) => row.experiment_group !== 'control');
  const control = rows.filter((row) => row.experiment_group === 'control');
  const contacted = rows.filter(isContacted), converted = rows.filter(isConverted);
  const retentionEligible = rows.filter((row) => eligible(row, now));
  const observed = retentionEligible.filter((row) => row.retained !== null);
  const retained = observed.filter((row) => booleanValue(row.retained));
  const treatmentEligible = treatment.filter((row) => eligible(row, now));
  const controlEligible = control.filter((row) => eligible(row, now));
  const treatmentObserved = treatmentEligible.filter((row) => row.retained !== null);
  const controlObserved = controlEligible.filter((row) => row.retained !== null);
  const treatmentConversionRate = optionalRate(treatment.filter(isConverted).length, treatment.length);
  const controlConversionRate = optionalRate(control.filter(isConverted).length, control.length);
  const treatmentRetentionRate = optionalRate(treatmentObserved.filter((row) => booleanValue(row.retained)).length,
    treatmentObserved.length);
  const controlRetentionRate = optionalRate(controlObserved.filter((row) => booleanValue(row.retained)).length,
    controlObserved.length);
  const benchmarkGroups = group(benchmark, (row) => String(row.campaign_id));
  let incrementalConversions = 0, incrementalRevenue = 0;
  for (const campaignRows of group(rows, (row) => String(row.campaign_id)).values()) {
    const first = campaignRows[0]!;
    const treated = campaignRows.filter((row) => row.experiment_group !== 'control');
    const comparison = (benchmarkGroups.get(String(first.campaign_id)) ?? campaignRows)
      .filter((row) => row.experiment_group === 'control');
    const convertedCount = treated.filter(isConverted).length;
    const treatmentRevenue = treated.reduce((sum, row) => sum + revenue(row), 0);
    if (booleanValue(first.experiment_enabled) && treated.length && comparison.length) {
      const naturalRate = rate(comparison.filter(isConverted).length, comparison.length);
      const delta = convertedCount - naturalRate * treated.length;
      incrementalConversions += delta;
      incrementalRevenue += delta * (convertedCount ? treatmentRevenue / convertedCount : numberValue(first.revenue_per_conversion));
    } else {
      incrementalConversions += convertedCount;
      incrementalRevenue += treatmentRevenue;
    }
  }
  const totalCost = rows.reduce((sum, row) => sum + row.fixed_cost_share +
    (isContacted(row) ? numberValue(row.cost_per_contact) : 0), 0);
  return {
    target_count: rows.length, treatment_count: treatment.length, control_count: control.length,
    contacted_count: contacted.length, converted_count: converted.length, retained_count: retained.length,
    retention_eligible_count: retentionEligible.length, retention_observed_count: observed.length,
    retention_observation_rate: optionalRate(observed.length, retentionEligible.length),
    contact_rate: rate(contacted.length, rows.length), conversion_rate: rate(converted.length, rows.length),
    retention_rate: optionalRate(retained.length, observed.length),
    treatment_contact_rate: optionalRate(treatment.filter(isContacted).length, treatment.length),
    control_contact_rate: optionalRate(control.filter(isContacted).length, control.length),
    treatment_conversion_rate: treatmentConversionRate, control_conversion_rate: controlConversionRate,
    treatment_retention_rate: treatmentRetentionRate, control_retention_rate: controlRetentionRate,
    incremental_conversion_effect: treatmentConversionRate !== null && controlConversionRate !== null
      ? treatmentConversionRate - controlConversionRate : null,
    incremental_retention_effect: treatmentRetentionRate !== null && controlRetentionRate !== null
      ? treatmentRetentionRate - controlRetentionRate : null,
    incremental_conversions: incrementalConversions, total_cost: totalCost,
    observed_revenue: rows.reduce((sum, row) => sum + revenue(row), 0),
    incremental_revenue: incrementalRevenue, total_revenue: incrementalRevenue,
    roi: totalCost > 0 ? (incrementalRevenue - totalCost) / totalCost : null,
  };
}

@Injectable()
export class PerformanceService {
  constructor(private readonly repository: PerformanceRepository) {}

  async get(query: Row): Promise<Row> {
    const campaignId = query.campaign_id === undefined ? null : positiveId(query.campaign_id);
    const assigneeId = query.assigned_to_user_id === undefined ? null : positiveId(query.assigned_to_user_id);
    const segment = query.segment ?? null;
    if (segment !== null && !SEGMENTS.includes(segment)) fail(422, 'Invalid targeting segment.');
    if (campaignId !== null) {
      const campaign = await this.repository.findCampaign(campaignId);
      if (!campaign) fail(404, 'The campaign was not found.');
    }
    const { raw, counts } = await this.repository.outcomes(campaignId, segment);
    const benchmark: PerformanceRow[] = raw.map((row) => ({ ...row,
      fixed_cost_share: numberValue(row.fixed_cost) / (counts.get(numberValue(row.campaign_id)) ?? 1) }));
    const rows = assigneeId === null ? benchmark : benchmark.filter((row) => numberValue(row.assigned_to_user_id) === assigneeId);
    const now = Date.now();
    const dimension = (key: (row: PerformanceRow) => string, label: (row: PerformanceRow, key: string) => string) =>
      [...group(rows, key).entries()].sort(([a], [b]) => a.localeCompare(b)).map(([value, groupRows]) => ({
        ...metrics(groupRows, benchmark, now), key: value,
        label: label(groupRows[0]!, value),
        campaign_count: new Set(groupRows.map((row) => row.campaign_id)).size,
      }));
    return {
      campaign_id: campaignId, segment_code: segment, assigned_to_user_id: assigneeId,
      summary: metrics(rows, benchmark, now),
      by_campaign: dimension((row) => String(row.campaign_id), (row) => row.campaign_label),
      by_segment: dimension((row) => row.segment_code ?? 'unsegmented', (_row, key) => key === 'unsegmented' ? '미분류' : key),
      by_assignee: dimension((row) => row.assigned_to_user_id === null ? 'unassigned' : String(row.assigned_to_user_id),
        (row) => row.assignee_label ?? '미배정'),
      by_cluster: dimension((row) => row.cluster_name ?? 'unclustered', (_row, key) => key === 'unclustered' ? '미분류' : key),
      by_risk_level: dimension((row) => row.risk_level ?? 'unclassified', (_row, key) => ({ high: '높음 (고위험)',
        medium: '주의 (중위험)', low: '낮음 (저위험)' })[key as 'high' | 'medium' | 'low'] ?? '미분류'),
      generated_at: new Date().toISOString(),
    };
  }
}

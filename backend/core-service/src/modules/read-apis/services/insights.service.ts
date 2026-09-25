import { Injectable, HttpStatus } from '@nestjs/common';
import { UnitOfWork } from '../../../infrastructure/database/unit-of-work';
import { InsightsRepository } from '../repositories/insights.repository';
import {
  InsightFilters, Row, detail, insightResponse, customerResponse, snapshotResponse,
  numeric, nullableNumeric, reasonCodeList,
} from '../read-apis.util';


@Injectable()
export class InsightsService {
  constructor(private readonly unitOfWork: UnitOfWork, private readonly repository: InsightsRepository) {}

  async list(filters: InsightFilters, sortBy: string, sortOrder: string, page: number, pageSize: number): Promise<Row> {
    return this.unitOfWork.transaction(async session => {
    const campaign = await this.repository.campaignContext(filters, session);
    if (filters.campaignCandidatesOnly && filters.campaignId !== undefined && !campaign)
      detail(HttpStatus.NOT_FOUND, 'The campaign was not found.');
    const { items, summary, risks, clusters, options } = await this.repository.list(
      filters, sortBy, sortOrder, page, pageSize, campaign?.segment_code ?? null, session);
    const counts = (rows: Row[]): Record<string, number> => Object.fromEntries(rows.map(row => [String(row.name), numeric(row.count)]));
    const total = numeric(summary?.total);
    return {
      items: items.map(insightResponse), page, page_size: pageSize, total,
      total_pages: total === 0 ? 0 : Math.ceil(total / pageSize),
      stats: {
        total, average_churn_probability: numeric(summary?.average_churn_probability),
        risk_counts: counts(risks), cluster_counts: counts(clusters), cluster_options: counts(options),
      },
    };
    });
  }

  async highRiskCoverage(): Promise<Row> {
    const row = await this.repository.highRiskCoverage();
    const total = numeric(row?.total_high_risk);
    const enrolled = numeric(row?.enrolled_high_risk);
    return { total_high_risk: total, enrolled_high_risk: enrolled, coverage_rate: total ? enrolled / total : null };
  }

  async reasonDistribution(riskLevel?: string): Promise<Row> {
    const rows = await this.repository.reasonDistribution(riskLevel);
    const counts: Record<string, number> = {};
    for (const row of rows) {
      for (const code of reasonCodeList(row.reason_codes)) counts[code] = (counts[code] ?? 0) + 1;
    }
    return { total_customers: rows.length, counts };
  }

  async dualSignalCount(): Promise<Row> {
    const rows = await this.repository.dualSignalCount();
    if (rows.length === 0) return { count: 0, activity_gap_threshold: null };
    const gaps = rows.map(row => numeric(row.activity_gap)).sort((a, b) => a - b);
    const rank = Math.max(1, Math.ceil(gaps.length * 0.2));
    const threshold = gaps[rank - 1]!;
    return {
      count: rows.filter(row => row.risk_level === 'high' && numeric(row.activity_gap) <= threshold).length,
      activity_gap_threshold: threshold,
    };
  }

  async history(customerId: number, limit: number): Promise<Row> {
    const rows = await this.repository.history(customerId, limit);
    if (!rows.length) detail(HttpStatus.NOT_FOUND, 'The customer insight history was not found.');
    return { customer_id: customerId, items: rows.map(insightResponse) };
  }

  async detail(customerId: number): Promise<Row> {
    const insight = await this.repository.detail(customerId);
    if (!insight) detail(HttpStatus.NOT_FOUND, 'The customer insight was not found.');
    const [customer, snapshot] = await Promise.all([
      this.repository.customer(customerId),
      insight.customer_snapshot_id == null ? Promise.resolve(undefined) :
        this.repository.snapshot(insight.customer_snapshot_id),
    ]);
    if (!customer) detail(HttpStatus.NOT_FOUND, 'The customer insight was not found.');
    return { ...insightResponse(insight), customer: customerResponse(customer), customer_snapshot: snapshotResponse(snapshot ?? undefined) };
  }
}

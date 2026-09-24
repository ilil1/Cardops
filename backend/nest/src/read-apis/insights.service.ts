import { Injectable, HttpStatus } from '@nestjs/common';
import { DatabaseService, type SqlSession } from '../database/database.service';
import {
  InsightFilters, Row, detail, insightResponse, customerResponse, snapshotResponse,
  numeric, nullableNumeric, reasonCodeList,
} from './read-apis.util';

type QueryParts = { sql: string; params: unknown[] };

@Injectable()
export class InsightsService {
  constructor(private readonly db: DatabaseService) {}

  // The row number ordering is shared by every endpoint that uses the latest insight.
  private readonly latest = `WITH ranked AS (
    SELECT ci.*, ROW_NUMBER() OVER (
      PARTITION BY ci.customer_id ORDER BY ci.as_of_date DESC, ci.scored_at DESC, ci.id DESC
    ) AS insight_rank FROM customer_insights ci
  )`;

  private readonly selectedPriority = `CASE ?
    WHEN 'small_balance_decline' THEN 400
    WHEN 'dormant_full_payer' THEN 350
    WHEN 'high_risk_retention' THEN 300
    WHEN 'medium_reactivation' THEN 200
    WHEN 'active_full_payer' THEN 120
    WHEN 'low_risk_upsell' THEN 100
    WHEN 'stable_prime' THEN 90
    ELSE 1000 END`;

  // Matches the original campaign candidate rule, including its three-way priority
  // expression for already-open targets.
  private readonly activePriority = `CASE
    WHEN camp.segment_code = 'high_risk_retention' THEN 300
    WHEN camp.segment_code = 'medium_reactivation' THEN 200
    WHEN camp.segment_code = 'low_risk_upsell' THEN 100
    ELSE 1000 END`;

  async campaignContext(filters: InsightFilters, session: SqlSession = this.db): Promise<string | null> {
    if (!filters.campaignCandidatesOnly || filters.campaignId === undefined) return null;
    const campaign = await session.one<Row>('SELECT segment_code FROM campaigns WHERE id = ?', [filters.campaignId]);
    if (!campaign) detail(HttpStatus.NOT_FOUND, 'The campaign was not found.');
    return campaign.segment_code ?? null;
  }

  baseQuery(filters: InsightFilters, selectedSegment: string | null = null): QueryParts {
    const conditions = ['ci.insight_rank = 1'];
    const params: unknown[] = [];
    if (filters.riskLevel !== undefined) { conditions.push('ci.risk_level = ?'); params.push(filters.riskLevel); }
    if (filters.clusterName !== undefined) { conditions.push('ci.cluster_name = ?'); params.push(filters.clusterName); }
    if (filters.customerId !== undefined) { conditions.push('ci.customer_id = ?'); params.push(filters.customerId); }
    if (filters.campaignCandidatesOnly) {
      conditions.push(`NOT EXISTS (
        SELECT 1 FROM customers contact_customer
        WHERE contact_customer.customer_id = ci.customer_id
          AND (contact_customer.marketing_opt_out = 1 OR
               contact_customer.last_contacted_at >= UTC_TIMESTAMP() - INTERVAL 30 DAY)
      )`);
      conditions.push(`NOT EXISTS (
        SELECT 1 FROM campaign_targets recent_target
        WHERE recent_target.customer_id = ci.customer_id
          AND recent_target.status IN ('contacted', 'completed')
          AND recent_target.processed_at >= UTC_TIMESTAMP() - INTERVAL 30 DAY
      )`);
      let active = `NOT EXISTS (
        SELECT 1 FROM campaign_targets active_target
        JOIN campaigns camp ON camp.id = active_target.campaign_id
        WHERE active_target.customer_id = ci.customer_id
          AND active_target.status IN ('pending', 'assigned', 'contacted')
          AND camp.status IN ('draft', 'scheduled', 'active', 'paused')`;
      if (filters.campaignId !== undefined) {
        active += ` AND (active_target.status = 'contacted' OR ${this.activePriority} >= ${this.selectedPriority})`;
        params.push(selectedSegment);
      }
      conditions.push(`${active})`);
      if (filters.campaignId !== undefined) {
        conditions.push(`NOT EXISTS (
          SELECT 1 FROM campaign_targets same_target
          WHERE same_target.customer_id = ci.customer_id AND same_target.campaign_id = ?
        )`);
        params.push(filters.campaignId);
      }
    }
    return {
      sql: `${this.latest} SELECT %FIELDS% FROM ranked ci JOIN customers c ON c.customer_id = ci.customer_id WHERE ${conditions.join(' AND ')}`,
      params,
    };
  }

  private querySql(parts: QueryParts, fields: string, suffix = ''): string {
    return `${parts.sql.replace('%FIELDS%', fields)} ${suffix}`;
  }

  async list(filters: InsightFilters, sortBy: string, sortOrder: string, page: number, pageSize: number): Promise<Row> {
    return this.db.transaction(async session => {
    const selectedSegment = await this.campaignContext(filters, session);
    const parts = this.baseQuery(filters, selectedSegment);
    const withoutCluster = this.baseQuery({ ...filters, clusterName: undefined }, selectedSegment);
    const aggregateSql = this.querySql(parts,
      `COUNT(*) AS total, COALESCE(AVG(ci.churn_probability), 0) AS average_churn_probability`);
    const summary = await session.one<Row>(aggregateSql, parts.params);
    const risks = await session.query<Row>(this.querySql(parts, 'ci.risk_level AS name, COUNT(*) AS count', 'GROUP BY ci.risk_level'), parts.params);
    const clusters = await session.query<Row>(this.querySql(parts, 'ci.cluster_name AS name, COUNT(*) AS count', 'GROUP BY ci.cluster_name'), parts.params);
    const options = await session.query<Row>(this.querySql(withoutCluster, 'ci.cluster_name AS name, COUNT(*) AS count', 'GROUP BY ci.cluster_name'), withoutCluster.params);
    const sortable: Record<string, string> = {
      churn_probability: 'ci.churn_probability',
      actual_transaction_count: '(ci.expected_transaction_count + ci.activity_gap)',
      activity_gap: 'ci.activity_gap',
      expected_transaction_count: 'ci.expected_transaction_count',
      total_trans_amt: 'c.total_trans_amt',
      card_category: `CASE c.card_category WHEN 'Blue' THEN 1 WHEN 'Silver' THEN 2 WHEN 'Gold' THEN 3 WHEN 'Platinum' THEN 4 ELSE 0 END`,
      contacts_count_12_mon: 'c.contacts_count_12_mon',
      scored_at: 'ci.scored_at',
    };
    const orderColumn = sortable[sortBy];
    if (!orderColumn) detail(HttpStatus.UNPROCESSABLE_ENTITY, `Unsupported sort_by: ${sortBy}`);
    const direction = sortOrder === 'asc' ? 'ASC' : 'DESC';
    const items = await session.query<Row>(
      this.querySql(parts, `ci.*, c.total_trans_amt, c.card_category, c.contacts_count_12_mon`,
        `ORDER BY ${orderColumn} ${direction}, ci.id DESC LIMIT ? OFFSET ?`),
      [...parts.params, pageSize, (page - 1) * pageSize],
    );
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
    const parts = this.baseQuery({ riskLevel: 'high' });
    const row = await this.db.one<Row>(this.querySql(parts, `COUNT(*) AS total_high_risk,
      SUM(CASE WHEN EXISTS (
        SELECT 1 FROM campaign_targets ct WHERE ct.customer_id = ci.customer_id
      ) THEN 1 ELSE 0 END) AS enrolled_high_risk`), parts.params);
    const total = numeric(row?.total_high_risk);
    const enrolled = numeric(row?.enrolled_high_risk);
    return { total_high_risk: total, enrolled_high_risk: enrolled, coverage_rate: total ? enrolled / total : null };
  }

  async reasonDistribution(riskLevel?: string): Promise<Row> {
    const parts = this.baseQuery({ riskLevel });
    const rows = await this.db.query<Row>(this.querySql(parts, 'ci.reason_codes'), parts.params);
    const counts: Record<string, number> = {};
    for (const row of rows) {
      for (const code of reasonCodeList(row.reason_codes)) counts[code] = (counts[code] ?? 0) + 1;
    }
    return { total_customers: rows.length, counts };
  }

  async dualSignalCount(): Promise<Row> {
    const parts = this.baseQuery({});
    const rows = await this.db.query<Row>(this.querySql(parts, 'ci.activity_gap, ci.risk_level'), parts.params);
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
    const rows = await this.db.query<Row>(`SELECT ci.*, c.total_trans_amt, c.card_category, c.contacts_count_12_mon
      FROM customer_insights ci JOIN customers c ON c.customer_id = ci.customer_id
      WHERE ci.customer_id = ?
      ORDER BY ci.as_of_date DESC, ci.scored_at DESC, ci.id DESC LIMIT ?`, [customerId, limit]);
    if (!rows.length) detail(HttpStatus.NOT_FOUND, 'The customer insight history was not found.');
    return { customer_id: customerId, items: rows.map(insightResponse) };
  }

  async detail(customerId: number): Promise<Row> {
    const parts = this.baseQuery({ customerId });
    const insight = await this.db.one<Row>(this.querySql(parts, 'ci.*, c.total_trans_amt, c.card_category, c.contacts_count_12_mon'), parts.params);
    if (!insight) detail(HttpStatus.NOT_FOUND, 'The customer insight was not found.');
    const [customer, snapshot] = await Promise.all([
      this.db.one<Row>('SELECT * FROM customers WHERE customer_id = ?', [customerId]),
      insight.customer_snapshot_id == null ? Promise.resolve(undefined) :
        this.db.one<Row>('SELECT * FROM customer_feature_snapshots WHERE id = ?', [insight.customer_snapshot_id]),
    ]);
    if (!customer) detail(HttpStatus.NOT_FOUND, 'The customer insight was not found.');
    return { ...insightResponse(insight), customer: customerResponse(customer), customer_snapshot: snapshotResponse(snapshot ?? undefined) };
  }
}

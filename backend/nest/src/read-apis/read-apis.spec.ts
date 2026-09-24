import { describe, expect, it } from 'vitest';
import type { DatabaseService } from '../database/database.service';
import { InsightsService } from './insights.service';
import { AnalyticsService } from './analytics.service';
import { ModelRunsService } from './model-runs.service';
import type { Row } from './read-apis.util';

describe('read API parity', () => {
  it('builds campaign candidate filters with the selected campaign priority and exact parameter order', () => {
    const service = new InsightsService({} as DatabaseService);
    const query = service.baseQuery({
      riskLevel: 'high', clusterName: 'at-risk', customerId: 123,
      campaignCandidatesOnly: true, campaignId: 7,
    }, 'medium_reactivation');
    expect(query.params).toEqual(['high', 'at-risk', 123, 'medium_reactivation', 7]);
    expect(query.sql).toContain('contact_customer.marketing_opt_out = 1');
    expect(query.sql).toContain("recent_target.status IN ('contacted', 'completed')");
    expect(query.sql).toContain("active_target.status IN ('pending', 'assigned', 'contacted')");
    expect(query.sql).toContain("active_target.status = 'contacted' OR");
    expect(query.sql).toContain('same_target.campaign_id = ?');
  });

  it('uses NumPy-compatible linear percentiles within each risk group', async () => {
    const db = { query: async () => [
      { risk_level: 'high', value: 1 }, { risk_level: 'high', value: 2 },
      { risk_level: 'high', value: 3 }, { risk_level: 'high', value: 4 },
      { risk_level: 'low', value: 10 },
    ] } as unknown as DatabaseService;
    const result = await new AnalyticsService(db, new InsightsService(db))
      .numericDistribution('Total_Trans_Ct', {});
    expect(result.by_target.high).toEqual({
      min: 1, q1: 1.75, median: 2.5, q3: 3.25, max: 4, count: 4,
    });
    expect(result.by_target.low).toEqual({
      min: 10, q1: 10, median: 10, q3: 10, max: 10, count: 1,
    });
  });

  it('falls back to the most recent successful run for each legacy task', async () => {
    const rows: Row[] = [
      { id: 4, task: 'regression', status: 'succeeded', started_at: '2026-08-03T00:00:00Z', completed_at: null, processed_rows: 2, dataset_sha256: null },
      { id: 3, task: 'classification', status: 'succeeded', started_at: '2026-08-02T00:00:00Z', completed_at: '2026-08-02T01:00:00Z', processed_rows: 4, dataset_sha256: 'new' },
      { id: 2, task: 'classification', status: 'succeeded', started_at: '2026-08-01T00:00:00Z', completed_at: null, processed_rows: 9, dataset_sha256: 'old' },
      { id: 1, task: 'clustering', status: 'succeeded', started_at: '2026-07-31T00:00:00Z', completed_at: '2026-08-01T01:00:00Z', processed_rows: 3, dataset_sha256: null },
    ];
    const db = { one: async () => null, query: async () => rows } as unknown as DatabaseService;
    const result = await new ModelRunsService(db).latest();
    expect(result.runs.map((run: Row) => run.id)).toEqual([3, 4, 1]);
    expect(result.processed_rows).toBe(4);
    expect(result.dataset_sha256).toBe('new');
    expect(result.started_at).toBe('2026-07-31T00:00:00.000Z');
  });
});

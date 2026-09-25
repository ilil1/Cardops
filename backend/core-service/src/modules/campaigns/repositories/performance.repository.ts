import { Injectable } from '@nestjs/common';
import { DatabaseService } from '../../../infrastructure/database/database.service';
import { Row, numberValue } from '../campaigns.shared';

@Injectable()
export class PerformanceRepository {
  constructor(private readonly db: DatabaseService) {}

  findCampaign(id: number) {
    return this.db.one<Row>('SELECT id FROM campaigns WHERE id = ?', [id]);
  }

  async outcomes(campaignId: number | null, segment: string | null) {
    const predicates = ["t.status <> 'cancelled'"], params: unknown[] = [];
    if (campaignId !== null) { predicates.push('t.campaign_id = ?'); params.push(campaignId); }
    if (segment !== null) { predicates.push('c.segment_code = ?'); params.push(segment); }
    const raw = await this.db.query<Row>(`SELECT t.*, c.name AS campaign_label,
      c.segment_code, c.start_at, c.experiment_enabled, c.fixed_cost,
      c.cost_per_contact, c.revenue_per_conversion, c.retention_window_days,
      u.display_name AS assignee_label, i.cluster_name, i.risk_level
      FROM campaign_targets t JOIN campaigns c ON c.id = t.campaign_id
      LEFT JOIN users u ON u.id = t.assigned_to_user_id
      JOIN customer_insights i ON i.id = t.customer_insight_id
      WHERE ${predicates.join(' AND ')}`, params);
    const campaignIds = [...new Set(raw.map((row) => numberValue(row.campaign_id)))];
    const counts = new Map<number, number>();
    if (campaignIds.length) {
      const countRows = await this.db.query<Row>(`SELECT campaign_id, COUNT(*) AS total FROM campaign_targets
        WHERE campaign_id IN (?) AND status <> 'cancelled' GROUP BY campaign_id`, [campaignIds]);
      for (const row of countRows) counts.set(numberValue(row.campaign_id), numberValue(row.total));
    }
    return { raw, counts };
  }
}

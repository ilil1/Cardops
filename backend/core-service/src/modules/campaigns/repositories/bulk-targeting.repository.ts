import { Injectable } from '@nestjs/common';
import { DatabaseService, type SqlSession } from '../../../infrastructure/database/database.service';
import type { Row } from '../campaigns.shared';

@Injectable()
export class BulkTargetingRepository {
  constructor(private readonly db: DatabaseService) {}

  findScoringBatch(batchId: number | undefined, asOfDate: string | undefined, session: SqlSession = this.db) {
    const where = ["status = 'succeeded'"], values: unknown[] = [];
    if (batchId !== undefined) { where.push('id = ?'); values.push(batchId); }
    if (asOfDate) { where.push('as_of_date <= ?'); values.push(asOfDate); }
    return session.one<Row>(`SELECT * FROM scoring_batches WHERE ${where.join(' AND ')}
      ORDER BY as_of_date DESC, completed_at DESC, id DESC LIMIT 1`, values);
  }

  activityGaps(batchId: unknown, session: SqlSession = this.db) {
    return session.query<Row>('SELECT activity_gap FROM customer_insights WHERE scoring_batch_id = ?', [batchId]);
  }

  scoredCustomers(batchId: unknown, session: SqlSession = this.db) {
    return session.query<Row>(`SELECT i.*, c.total_revolving_bal, c.total_trans_ct, c.total_trans_amt,
      c.total_ct_chng_q4_q1, c.marketing_opt_out, c.last_contacted_at
      FROM customer_insights i JOIN customers c ON c.customer_id = i.customer_id
      WHERE i.scoring_batch_id = ?`, [batchId]);
  }

  customerTargets(customerIds: unknown, session: SqlSession = this.db) {
    return session.query<Row>(`SELECT t.customer_id, t.status, t.processed_at, c.segment_code,
      c.status AS campaign_status FROM campaign_targets t LEFT JOIN campaigns c ON c.id = t.campaign_id
      WHERE t.customer_id IN (?)`, [customerIds]);
  }

  findAssigneeRole(id: unknown, session: SqlSession = this.db) {
    return session.one<Row>('SELECT role, is_active FROM users WHERE id = ?', [id]);
  }

  insertRun(segment: unknown, actorId: unknown, rerunOfId: unknown, batchId: unknown, asOfDate: unknown, rules: unknown, previewCount: unknown, eligibleCount: unknown, skippedActive: unknown, skippedRecent: unknown, skippedOptOut: unknown, session: SqlSession = this.db) {
    return session.execute(`INSERT INTO bulk_targeting_runs
      (segment_code, status, requested_by_user_id, rerun_of_id, scoring_batch_id,
       source_as_of_date, rules_json, preview_count, eligible_count,
       skipped_active_campaign_count, skipped_recent_contact_count, skipped_opt_out_count)
      VALUES (?, 'previewed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`, [segment, actorId, rerunOfId, batchId, asOfDate, rules, previewCount, eligibleCount, skippedActive, skippedRecent, skippedOptOut]);
  }

  insertCandidate(runId: unknown, customerId: unknown, insightId: unknown, rank: unknown, eligible: unknown, selected: unknown, exclusion: unknown, session: SqlSession = this.db) {
    return session.execute(`INSERT INTO bulk_targeting_candidates
        (run_id, customer_id, customer_insight_id, \`rank\`, eligible, selected, exclusion_reason, execution_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')`, [runId, customerId, insightId, rank, eligible, selected, exclusion]);
  }

  findRun(lock: boolean, id: unknown, session: SqlSession = this.db) {
    return session.one<Row>(`SELECT r.*, c.status AS campaign_status FROM bulk_targeting_runs r
      LEFT JOIN campaigns c ON c.id = r.campaign_id WHERE r.id = ? ${lock ? 'FOR UPDATE' : ''}`, [id]);
  }

  selectedInsights(runId: unknown, session: SqlSession = this.db) {
    return session.query<Row>(`SELECT i.* FROM bulk_targeting_candidates s
      JOIN customer_insights i ON i.id = s.customer_insight_id
      WHERE s.run_id = ? AND s.selected = 1 ORDER BY s.\`rank\``, [runId]);
  }

  countRuns(session: SqlSession = this.db) {
    return session.one<Row>('SELECT COUNT(*) AS total FROM bulk_targeting_runs', []);
  }

  listRuns(limit: unknown, offset: unknown, session: SqlSession = this.db) {
    return session.query<Row>(`SELECT r.*, c.status AS campaign_status FROM bulk_targeting_runs r
      LEFT JOIN campaigns c ON c.id = r.campaign_id ORDER BY r.created_at DESC, r.id DESC LIMIT ? OFFSET ?`, [limit, offset]);
  }

  lockSelectedCandidates(runId: unknown, session: SqlSession = this.db) {
    return session.query<Row>(`SELECT * FROM bulk_targeting_candidates
          WHERE run_id = ? AND selected = 1 ORDER BY \`rank\` FOR UPDATE`, [runId]);
  }

  insertCampaign(name: unknown, description: unknown, channel: unknown, segment: unknown, experimentEnabled: unknown, controlGroupRatio: unknown, seed: unknown, fixedCost: unknown, costPerContact: unknown, revenuePerConversion: unknown, retentionWindowDays: unknown, actorId: unknown, session: SqlSession = this.db) {
    return session.execute(`INSERT INTO campaigns
          (name, description, channel, segment_code, status, experiment_enabled, control_group_ratio,
           experiment_seed, experiment_assignment_version, fixed_cost, cost_per_contact,
           revenue_per_conversion, retention_window_days, created_by_user_id)
          VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, 'sha256_seed_customer_v1', ?, ?, ?, ?, ?)`, [name, description, channel, segment, experimentEnabled, controlGroupRatio, seed, fixedCost, costPerContact, revenuePerConversion, retentionWindowDays, actorId]);
  }

  markRunExecuted(campaignId: unknown, status: unknown, executedAt: unknown, id: unknown, session: SqlSession = this.db) {
    return session.execute('UPDATE bulk_targeting_runs SET campaign_id = ?, status = ?, executed_at = ? WHERE id = ?', [campaignId, status, executedAt, id]);
  }

  findAssignee(id: unknown, session: SqlSession = this.db) {
    return session.one<Row>('SELECT * FROM users WHERE id = ?', [id]);
  }

  findInsight(id: unknown, session: SqlSession = this.db) {
    return session.one<Row>('SELECT * FROM customer_insights WHERE id = ?', [id]);
  }

  lockCustomer(id: unknown, session: SqlSession = this.db) {
    return session.one<Row>('SELECT * FROM customers WHERE customer_id = ? FOR UPDATE', [id]);
  }

  markCandidateCreated(status: unknown, targetId: unknown, id: unknown, session: SqlSession = this.db) {
    return session.execute('UPDATE bulk_targeting_candidates SET execution_status = ?, campaign_target_id = ? WHERE id = ?', [status, targetId, id]);
  }

  updateCreatedCount(count: unknown, id: unknown, session: SqlSession = this.db) {
    return session.execute('UPDATE bulk_targeting_runs SET created_count = ? WHERE id = ?', [count, id]);
  }

  skipCandidate(status: unknown, reason: unknown, id: unknown, session: SqlSession = this.db) {
    return session.execute('UPDATE bulk_targeting_candidates SET execution_status = ?, exclusion_reason = ? WHERE id = ?', [status, reason, id]);
  }

  cancelPendingCandidates(runId: unknown, session: SqlSession = this.db) {
    return session.execute(`UPDATE bulk_targeting_candidates SET execution_status = 'cancelled'
          WHERE run_id = ? AND selected = 1 AND execution_status = 'pending'`, [runId]);
  }

  cancelPreview(status: unknown, cancelledAt: unknown, id: unknown, session: SqlSession = this.db) {
    return session.execute('UPDATE bulk_targeting_runs SET status = ?, cancelled_at = ? WHERE id = ?', [status, cancelledAt, id]);
  }

  lockUncontactedTargets(runId: unknown, session: SqlSession = this.db) {
    return session.query<Row>(`SELECT * FROM campaign_targets WHERE bulk_targeting_run_id = ?
        AND status IN ('pending', 'assigned') FOR UPDATE`, [runId]);
  }

  cancelTarget(status: unknown, processedAt: unknown, id: unknown, session: SqlSession = this.db) {
    return session.execute('UPDATE campaign_targets SET status = ?, processed_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', [status, processedAt, id]);
  }

  cancelCandidate(runId: unknown, targetId: unknown, session: SqlSession = this.db) {
    return session.execute(`UPDATE bulk_targeting_candidates SET execution_status = 'cancelled'
          WHERE run_id = ? AND campaign_target_id = ?`, [runId, targetId]);
  }

  cancelExecutedRun(cancelledAt: unknown, count: unknown, id: unknown, session: SqlSession = this.db) {
    return session.execute(`UPDATE bulk_targeting_runs SET status = 'cancelled', cancelled_at = ?,
        cancelled_target_count = cancelled_target_count + ? WHERE id = ?`, [cancelledAt, count, id]);
  }
}

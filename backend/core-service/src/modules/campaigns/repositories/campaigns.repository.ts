import { Injectable } from '@nestjs/common';
import { DatabaseService, type SqlSession } from '../../../infrastructure/database/database.service';
import type { Row } from '../campaigns.shared';

@Injectable()
export class CampaignsRepository {
  constructor(private readonly db: DatabaseService) {}

  findCampaign(lock: boolean, id: unknown, session: SqlSession = this.db) {
    return session.one<Row>(`SELECT c.*, u.display_name AS created_by_display_name FROM campaigns c
      LEFT JOIN users u ON u.id = c.created_by_user_id WHERE c.id = ? ${lock ? 'FOR UPDATE' : ''}`, [id]);
  }

  findTarget(lock: boolean, id: unknown, session: SqlSession = this.db) {
    return session.one<Row>(`SELECT t.*, c.status AS campaign_status, a.display_name AS assigned_to_display_name
      FROM campaign_targets t LEFT JOIN campaigns c ON c.id = t.campaign_id
      LEFT JOIN users a ON a.id = t.assigned_to_user_id WHERE t.id = ? ${lock ? 'FOR UPDATE' : ''}`, [id]);
  }

  targetStats(campaignId: unknown, session: SqlSession = this.db) {
    return session.query<Row>('SELECT status, experiment_group, converted FROM campaign_targets WHERE campaign_id = ?', [campaignId]);
  }

  private countCampaigns(predicate: string, values: readonly unknown[], session: SqlSession = this.db) {
    return session.one<Row>(`SELECT COUNT(*) AS total FROM campaigns c ${predicate}`, values);
  }

  private listCampaigns(predicate: string, values: readonly unknown[], session: SqlSession = this.db) {
    return session.query<Row>(`SELECT c.*, u.display_name AS created_by_display_name
      FROM campaigns c LEFT JOIN users u ON u.id = c.created_by_user_id ${predicate}
      ORDER BY c.created_at DESC, c.id DESC LIMIT ? OFFSET ?`, values);
  }

  insertCampaign(name: unknown, description: unknown, channel: unknown, segmentCode: unknown, startAt: unknown, endAt: unknown, experimentEnabled: unknown, controlGroupRatio: unknown, experimentSeed: unknown, fixedCost: unknown, costPerContact: unknown, revenuePerConversion: unknown, retentionWindowDays: unknown, actorId: unknown, session: SqlSession = this.db) {
    return session.execute(`INSERT INTO campaigns
          (name, description, channel, segment_code, status, start_at, end_at, experiment_enabled,
          control_group_ratio, experiment_seed, experiment_assignment_version, fixed_cost,
          cost_per_contact, revenue_per_conversion, retention_window_days, created_by_user_id)
          VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, 'sha256_seed_customer_v1', ?, ?, ?, ?, ?)`, [name, description, channel, segmentCode, startAt, endAt, experimentEnabled, controlGroupRatio, experimentSeed, fixedCost, costPerContact, revenuePerConversion, retentionWindowDays, actorId]);
  }

  lockCampaignTargets(campaignId: unknown, session: SqlSession = this.db) {
    return session.query<Row>('SELECT id, status, experiment_group FROM campaign_targets WHERE campaign_id = ? FOR UPDATE', [campaignId]);
  }

  renameTargetCampaign(name: unknown, campaignId: unknown, session: SqlSession = this.db) {
    return session.execute('UPDATE campaign_targets SET campaign_name = ? WHERE campaign_id = ?', [name, campaignId]);
  }

  updateTargetStatus(status: unknown, processedAt: unknown, id: unknown, session: SqlSession = this.db) {
    return session.execute('UPDATE campaign_targets SET status = ?, processed_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', [status, processedAt, id]);
  }

  updateCampaign(name: unknown, description: unknown, channel: unknown, segmentCode: unknown, status: unknown, startAt: unknown, endAt: unknown, experimentEnabled: unknown, controlGroupRatio: unknown, fixedCost: unknown, costPerContact: unknown, revenuePerConversion: unknown, retentionWindowDays: unknown, id: unknown, session: SqlSession = this.db) {
    return session.execute(`UPDATE campaigns SET name = ?, description = ?, channel = ?, segment_code = ?, status = ?,
          start_at = ?, end_at = ?, experiment_enabled = ?, control_group_ratio = ?, fixed_cost = ?,
          cost_per_contact = ?, revenue_per_conversion = ?, retention_window_days = ?, updated_at = CURRENT_TIMESTAMP
          WHERE id = ?`, [name, description, channel, segmentCode, status, startAt, endAt, experimentEnabled, controlGroupRatio, fixedCost, costPerContact, revenuePerConversion, retentionWindowDays, id]);
  }

  private countTargets(where: string, values: readonly unknown[], session: SqlSession = this.db) {
    return session.one<Row>(`SELECT COUNT(*) AS total FROM campaign_targets t ${where}`, values);
  }

  private listTargetStats(where: string, values: readonly unknown[], session: SqlSession = this.db) {
    return session.query<Row>(`SELECT t.status, t.experiment_group, t.converted FROM campaign_targets t ${where}`, values);
  }

  private listTargets(where: string, values: readonly unknown[], session: SqlSession = this.db) {
    return session.query<Row>(`SELECT t.*, c.status AS campaign_status,
      a.display_name AS assigned_to_display_name FROM campaign_targets t
      LEFT JOIN campaigns c ON c.id = t.campaign_id LEFT JOIN users a ON a.id = t.assigned_to_user_id
      ${where} ORDER BY t.created_at DESC, t.id DESC LIMIT ? OFFSET ?`, values);
  }

  private countEvents(where: string, values: readonly unknown[], session: SqlSession = this.db) {
    return session.one<Row>(`SELECT COUNT(*) AS total FROM campaign_events e ${where}`, values);
  }

  private listEvents(where: string, values: readonly unknown[], session: SqlSession = this.db) {
    return session.query<Row>(`SELECT e.*, u.display_name AS actor_display_name FROM campaign_events e
      LEFT JOIN users u ON u.id = e.actor_user_id ${where} ORDER BY e.created_at DESC, e.id DESC
      LIMIT ? OFFSET ?`, values);
  }

  contactDurations(session: SqlSession = this.db) {
    return session.query<Row>(`SELECT i.risk_level, t.created_at, t.contacted_at
      FROM campaign_targets t JOIN customer_insights i ON i.id = t.customer_insight_id
      WHERE t.contacted_at IS NOT NULL AND t.experiment_group <> 'control' AND t.status <> 'cancelled'`, []);
  }

  findInsight(id: unknown, session: SqlSession = this.db) {
    return session.one<Row>('SELECT * FROM customer_insights WHERE id = ?', [id]);
  }

  lockCampaignByName(name: unknown, session: SqlSession = this.db) {
    return session.one<Row>('SELECT * FROM campaigns WHERE name = ? FOR UPDATE', [name]);
  }

  insertLegacyCampaign(name: unknown, status: unknown, actorId: unknown, session: SqlSession = this.db) {
    return session.execute('INSERT INTO campaigns (name, status, created_by_user_id) VALUES (?, ?, ?)', [name, status, actorId]);
  }

  findAssignee(id: unknown, session: SqlSession = this.db) {
    return session.one<Row>('SELECT * FROM users WHERE id = ?', [id]);
  }

  lockCustomer(customerId: unknown, session: SqlSession = this.db) {
    return session.one<Row>('SELECT * FROM customers WHERE customer_id = ? FOR UPDATE', [customerId]);
  }

  findRecentContact(customerId: unknown, cutoff: unknown, session: SqlSession = this.db) {
    return session.one<Row>(`SELECT id FROM campaign_targets WHERE customer_id = ?
      AND status IN ('contacted', 'completed') AND processed_at >= ? LIMIT 1`, [customerId, cutoff]);
  }

  findDuplicateTarget(customerId: unknown, campaignId: unknown, session: SqlSession = this.db) {
    return session.one<Row>('SELECT id FROM campaign_targets WHERE customer_id = ? AND campaign_id = ? LIMIT 1', [customerId, campaignId]);
  }

  lockOpenTargets(customerId: unknown, session: SqlSession = this.db) {
    return session.query<Row>(`SELECT t.*, c.segment_code FROM campaign_targets t
      JOIN campaigns c ON c.id = t.campaign_id WHERE t.customer_id = ?
      AND t.status IN ('pending','assigned','contacted')
      AND c.status IN ('draft','scheduled','active','paused') FOR UPDATE`, [customerId]);
  }

  insertTarget(customerId: unknown, insightId: unknown, campaignId: unknown, bulkRunId: unknown, campaignName: unknown, experimentGroup: unknown, assignedId: unknown, status: unknown, session: SqlSession = this.db) {
    return session.execute(`INSERT INTO campaign_targets
      (customer_id, customer_insight_id, campaign_id, bulk_targeting_run_id, campaign_name,
       experiment_group, assigned_to_user_id, status, converted)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)`, [customerId, insightId, campaignId, bulkRunId, campaignName, experimentGroup, assignedId, status]);
  }

  updateLastContact(contactedAt: unknown, customerId: unknown, session: SqlSession = this.db) {
    return session.execute('UPDATE customers SET last_contacted_at = ? WHERE customer_id = ?', [contactedAt, customerId]);
  }

  optOutCustomer(customerId: unknown, session: SqlSession = this.db) {
    return session.execute('UPDATE customers SET marketing_opt_out = 1 WHERE customer_id = ?', [customerId]);
  }

  updateTarget(updates: Row, id: number, session: SqlSession = this.db) {
    const fields = Object.keys(updates);
    const allowed = new Set(['assigned_to_user_id', 'status', 'processed_at', 'contacted_at', 'completed_at',
      'result', 'result_notes', 'result_code', 'converted', 'converted_at', 'retained', 'retention_checked_at', 'outcome_revenue']);
    if (fields.some(field => !allowed.has(field))) throw new Error('Unsupported target update field.');
    const values = [...fields.map(field => updates[field]), id];
    return session.execute(`UPDATE campaign_targets SET ${fields.map((field) => `${field} = ?`).join(', ')},
          updated_at = CURRENT_TIMESTAMP WHERE id = ?`, values);
  }

  findCustomer(customerId: unknown, session: SqlSession = this.db) {
    return session.one<Row>('SELECT customer_id FROM customers WHERE customer_id = ?', [customerId]);
  }

  updateOptOut(optOut: unknown, customerId: unknown, session: SqlSession = this.db) {
    return session.execute('UPDATE customers SET marketing_opt_out = ?, updated_at = CURRENT_TIMESTAMP WHERE customer_id = ?', [optOut, customerId]);
  }

  contactPreferences(customerId: unknown, session: SqlSession = this.db) {
    return session.one<Row>('SELECT customer_id, marketing_opt_out, last_contacted_at FROM customers WHERE customer_id = ?', [customerId]);
  }
  async campaignPage(query: Row, pageSize: number, offset: number) {
    const where: string[] = [], params: unknown[] = [];
    if (query.status !== undefined) {
      where.push('c.status = ?'); params.push(query.status);
    }
    if (query.name !== undefined) { where.push('LOWER(c.name) LIKE ?'); params.push(`%${String(query.name).toLowerCase()}%`); }
    if (query.created_by_user_id !== undefined) {
      where.push('c.created_by_user_id = ?'); params.push(query.created_by_user_id);
    }
    const predicate = where.length ? `WHERE ${where.join(' AND ')}` : '';
    const count = await this.countCampaigns(predicate, params);
    const rows = await this.listCampaigns(predicate, [...params, pageSize, offset]);
    return { count, rows };
  }
  private targetFilters(query: Row): { where: string; params: unknown[] } {
    const predicates: string[] = [], params: unknown[] = [];
    if (query.status !== undefined) {
      predicates.push('t.status = ?'); params.push(query.status);
    }
    for (const field of ['campaign_id', 'assigned_to_user_id', 'customer_id']) {
      if (query[field] !== undefined) { predicates.push(`t.${field} = ?`); params.push(query[field]); }
    }
    if (query.campaign_name !== undefined) { predicates.push('t.campaign_name = ?'); params.push(query.campaign_name); }
    const converted = query.converted ?? null;
    if (converted !== null) { predicates.push('t.converted = ?'); params.push(converted); }
    return { where: predicates.length ? `WHERE ${predicates.join(' AND ')}` : '', params };
  }

  async targetPage(query: Row, pageSize: number, offset: number) {
    const { where, params } = this.targetFilters(query);
    const count = await this.countTargets(where, params);
    const allForStats = await this.listTargetStats(where, params);
    const rows = await this.listTargets(where, [...params, pageSize, offset]);
    return { count, allForStats, rows };
  }
  async eventPage(campaignId: number, targetId: number | undefined, pageSize: number, offset: number) {
    const params: unknown[] = [campaignId];
    let where = 'WHERE e.campaign_id = ?';
    if (targetId !== undefined) { where += ' AND e.campaign_target_id = ?'; params.push(targetId); }
    const count = await this.countEvents(where, params);
    const rows = await this.listEvents(where, [...params, pageSize, offset]);
    return { count, rows };
  }
}

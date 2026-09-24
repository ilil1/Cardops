import { Injectable } from '@nestjs/common';
import { DatabaseService } from '../database/database.service';
import {
  Actor, CAMPAIGN_STATES, FINAL_RESULTS, OPEN_CAMPAIGN_STATES, OPEN_TARGET_STATES,
  RESULT_CODES, Row, SEGMENT_PRIORITY, SEGMENTS, SqlClient, TARGET_STATES,
  addEvent, booleanValue, campaignResponse, campaignStats, dateValue, fail, insertedId,
  isDuplicate, numberValue, optionalBoolean, pageQuery, positiveId, stamp, targetResponse,
  seed, sha256,
} from './campaigns.shared';

const campaignTransitions: Record<string, string[]> = {
  draft: ['scheduled', 'active', 'cancelled'], scheduled: ['active', 'paused', 'cancelled'],
  active: ['paused', 'completed', 'cancelled'], paused: ['active', 'completed', 'cancelled'],
  completed: [], cancelled: [],
};
const targetTransitions: Record<string, string[]> = {
  pending: ['assigned', 'cancelled'], assigned: ['pending', 'contacted', 'cancelled'],
  contacted: ['completed', 'cancelled'], completed: [], cancelled: [],
};
const campaignColumns = ['name', 'description', 'channel', 'segment_code', 'status', 'start_at', 'end_at',
  'experiment_enabled', 'control_group_ratio', 'fixed_cost', 'cost_per_contact',
  'revenue_per_conversion', 'retention_window_days'];

function validateCampaign(values: Row, creating: boolean): void {
  if (creating && (!values.name || typeof values.name !== 'string')) fail(422, 'name is required.');
  if (values.name !== undefined && (typeof values.name !== 'string' || !values.name.trim() || values.name.trim().length > 150))
    fail(422, 'Campaign name must contain 1 to 150 characters.');
  if (values.description !== undefined && values.description !== null && String(values.description).length > 4000)
    fail(422, 'description is too long.');
  if (values.channel !== undefined && values.channel !== null && String(values.channel).length > 30)
    fail(422, 'channel is too long.');
  if (values.segment_code !== undefined && values.segment_code !== null && !SEGMENTS.includes(values.segment_code))
    fail(422, 'Invalid segment_code.');
  if (values.status !== undefined && values.status !== null && !CAMPAIGN_STATES.includes(values.status))
    fail(422, 'Invalid campaign status.');
  if (creating && values.status !== undefined && values.status !== 'draft')
    fail(422, 'campaigns must be created with draft status');
  if (values.control_group_ratio !== undefined && values.control_group_ratio !== null &&
    (numberValue(values.control_group_ratio, -1) < 0 || numberValue(values.control_group_ratio, 1) >= 1))
    fail(422, 'control_group_ratio must be between 0 and 1.');
  for (const field of ['fixed_cost', 'cost_per_contact', 'revenue_per_conversion']) {
    if (values[field] !== undefined && values[field] !== null && numberValue(values[field], -1) < 0)
      fail(422, 'Campaign financial values cannot be negative.');
  }
  if (values.retention_window_days !== undefined && values.retention_window_days !== null &&
    (!Number.isInteger(Number(values.retention_window_days)) || Number(values.retention_window_days) < 1 || Number(values.retention_window_days) > 365))
    fail(422, 'retention_window_days must be between 1 and 365.');
  if (values.start_at !== undefined) dateValue(values.start_at);
  if (values.end_at !== undefined) dateValue(values.end_at);
}

function checkCampaignDates(status: string, startAt: unknown, endAt: unknown): void {
  const start = dateValue(startAt), end = dateValue(endAt), now = Date.now();
  if (start && end && end.getTime() < start.getTime()) fail(422, 'Campaign end_at must be after start_at.');
  if (status === 'scheduled' && !start) fail(422, 'A scheduled campaign requires start_at.');
  if (status === 'scheduled' && start && start.getTime() <= now) fail(422, 'A scheduled campaign must start in the future.');
  if (status === 'active' && start && start.getTime() > now) fail(422, 'A campaign cannot be active before start_at.');
  if (status === 'active' && end && end.getTime() <= now) fail(422, 'A campaign cannot be active after end_at.');
}

function checkExperiment(row: Row): void {
  const ratio = numberValue(row.control_group_ratio);
  if (ratio < 0 || ratio >= 1) fail(422, 'control_group_ratio must be between 0 and 1.');
  if (booleanValue(row.experiment_enabled) && ratio <= 0)
    fail(422, 'An A/B campaign must reserve a positive control group ratio.');
  if (['fixed_cost', 'cost_per_contact', 'revenue_per_conversion'].some((key) => numberValue(row[key]) < 0))
    fail(422, 'Campaign financial values cannot be negative.');
  const days = numberValue(row.retention_window_days);
  if (days < 1 || days > 365) fail(422, 'retention_window_days must be between 1 and 365.');
}

@Injectable()
export class CampaignsService {
  constructor(private readonly db: DatabaseService) {}

  async campaign(db: SqlClient, id: number, lock = false): Promise<Row | null> {
    return db.one<Row>(`SELECT c.*, u.display_name AS created_by_display_name FROM campaigns c
      LEFT JOIN users u ON u.id = c.created_by_user_id WHERE c.id = ? ${lock ? 'FOR UPDATE' : ''}`, [id]);
  }

  async target(db: SqlClient, id: number, lock = false): Promise<Row | null> {
    return db.one<Row>(`SELECT t.*, c.status AS campaign_status, a.display_name AS assigned_to_display_name
      FROM campaign_targets t LEFT JOIN campaigns c ON c.id = t.campaign_id
      LEFT JOIN users a ON a.id = t.assigned_to_user_id WHERE t.id = ? ${lock ? 'FOR UPDATE' : ''}`, [id]);
  }

  private async statsFor(db: SqlClient, campaignId: number): Promise<Row> {
    return campaignStats(await db.query<Row>(
      'SELECT status, experiment_group, converted FROM campaign_targets WHERE campaign_id = ?', [campaignId]));
  }

  async listCampaigns(query: Row): Promise<Row> {
    const { page, pageSize, offset } = pageQuery(query);
    const where: string[] = [], params: unknown[] = [];
    if (query.status !== undefined) {
      if (!CAMPAIGN_STATES.includes(query.status)) fail(422, 'Invalid campaign status.');
      where.push('c.status = ?'); params.push(query.status);
    }
    if (query.name !== undefined) { where.push('LOWER(c.name) LIKE ?'); params.push(`%${String(query.name).toLowerCase()}%`); }
    if (query.created_by_user_id !== undefined) {
      where.push('c.created_by_user_id = ?'); params.push(positiveId(query.created_by_user_id));
    }
    const predicate = where.length ? `WHERE ${where.join(' AND ')}` : '';
    const count = await this.db.one<Row>(`SELECT COUNT(*) AS total FROM campaigns c ${predicate}`, params);
    const rows = await this.db.query<Row>(`SELECT c.*, u.display_name AS created_by_display_name
      FROM campaigns c LEFT JOIN users u ON u.id = c.created_by_user_id ${predicate}
      ORDER BY c.created_at DESC, c.id DESC LIMIT ? OFFSET ?`, [...params, pageSize, offset]);
    const items = await Promise.all(rows.map(async (row) => campaignResponse(row, await this.statsFor(this.db, row.id))));
    const total = numberValue(count?.total);
    return { items, page, page_size: pageSize, total, total_pages: Math.ceil(total / pageSize) };
  }

  async getCampaign(id: number): Promise<Row> {
    const row = await this.campaign(this.db, id);
    if (!row) fail(404, 'The campaign was not found.');
    return campaignResponse(row, await this.statsFor(this.db, id));
  }

  async createCampaign(payload: Row, actor: Actor): Promise<Row> {
    validateCampaign(payload, true);
    const row: Row = {
      name: String(payload.name).trim(), description: payload.description ?? null,
      channel: payload.channel ?? null, segment_code: payload.segment_code ?? null,
      status: 'draft', start_at: dateValue(payload.start_at), end_at: dateValue(payload.end_at),
      experiment_enabled: booleanValue(payload.experiment_enabled),
      control_group_ratio: booleanValue(payload.experiment_enabled) ? numberValue(payload.control_group_ratio, 0.2) : 0,
      fixed_cost: numberValue(payload.fixed_cost), cost_per_contact: numberValue(payload.cost_per_contact),
      revenue_per_conversion: numberValue(payload.revenue_per_conversion),
      retention_window_days: numberValue(payload.retention_window_days, 30),
    };
    checkCampaignDates(row.status, row.start_at, row.end_at);
    checkExperiment(row);
    try {
      const id = await this.db.transaction(async (tx) => {
        const result = await tx.execute(`INSERT INTO campaigns
          (name, description, channel, segment_code, status, start_at, end_at, experiment_enabled,
          control_group_ratio, experiment_seed, experiment_assignment_version, fixed_cost,
          cost_per_contact, revenue_per_conversion, retention_window_days, created_by_user_id)
          VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, 'sha256_seed_customer_v1', ?, ?, ?, ?, ?)`,
          [row.name, row.description, row.channel, row.segment_code, row.start_at, row.end_at,
            row.experiment_enabled, row.control_group_ratio, seed(), row.fixed_cost,
            row.cost_per_contact, row.revenue_per_conversion, row.retention_window_days, actor.id]);
        const campaignId = insertedId(result);
        await addEvent(tx, campaignId, actor.id, 'created', { to_status: 'draft' });
        return campaignId;
      });
      return this.getCampaign(id);
    } catch (error) {
      if (isDuplicate(error)) fail(409, 'A campaign with the same name already exists.');
      throw error;
    }
  }

  async updateCampaign(id: number, payload: Row, actor: Actor): Promise<Row> {
    validateCampaign(payload, false);
    try {
      await this.db.transaction(async (tx) => {
        const current = await this.campaign(tx, id, true);
        if (!current) fail(404, 'The campaign was not found.');
        const supplied = Object.keys(payload);
        if (['completed', 'cancelled'].includes(current.status) && supplied.length)
          fail(409, 'A closed campaign is immutable.');
        const next = { ...current };
        for (const key of campaignColumns) {
          if (!Object.prototype.hasOwnProperty.call(payload, key)) continue;
          if (payload[key] === null && !['description', 'channel', 'segment_code', 'start_at', 'end_at'].includes(key)) continue;
          next[key] = key === 'name' ? String(payload[key]).trim() : payload[key];
        }
        next.experiment_enabled = booleanValue(next.experiment_enabled);
        for (const key of ['control_group_ratio', 'fixed_cost', 'cost_per_contact', 'revenue_per_conversion', 'retention_window_days'])
          next[key] = numberValue(next[key]);
        checkCampaignDates(next.status, next.start_at, next.end_at);
        checkExperiment(next);
        if (next.status !== current.status && !campaignTransitions[current.status]?.includes(next.status))
          fail(409, `Campaign status cannot change from ${current.status} to ${next.status}.`);
        const targets = await tx.query<Row>('SELECT id, status, experiment_group FROM campaign_targets WHERE campaign_id = ? FOR UPDATE', [id]);
        const numericPolicy = ['control_group_ratio', 'fixed_cost', 'cost_per_contact',
          'revenue_per_conversion', 'retention_window_days'];
        const policyChanged = next.segment_code !== current.segment_code ||
          booleanValue(next.experiment_enabled) !== booleanValue(current.experiment_enabled) ||
          numericPolicy.some((field) => numberValue(next[field]) !== numberValue(current[field]));
        if (targets.length && policyChanged)
          fail(409, 'Experiment, segment, and financial policies are immutable after targets exist.');
        if (next.status === 'completed' && current.status !== 'completed' &&
          targets.some((target) => target.experiment_group !== 'control' && OPEN_TARGET_STATES.includes(target.status)))
          fail(409, 'A campaign cannot be completed while treatment targets remain open.');
        if (next.status === 'active' && !next.start_at) next.start_at = new Date();
        if (next.name !== current.name && targets.length)
          await tx.execute('UPDATE campaign_targets SET campaign_name = ? WHERE campaign_id = ?', [next.name, id]);
        if (next.status === 'cancelled' && current.status !== 'cancelled') {
          for (const target of targets.filter((item) => OPEN_TARGET_STATES.includes(item.status))) {
            await tx.execute('UPDATE campaign_targets SET status = ?, processed_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
              ['cancelled', new Date(), target.id]);
            await addEvent(tx, id, actor.id, 'status_changed', { target_id: target.id,
              from_status: target.status, to_status: 'cancelled', note: 'Cancelled when the campaign was cancelled.' });
          }
        }
        await tx.execute(`UPDATE campaigns SET name = ?, description = ?, channel = ?, segment_code = ?, status = ?,
          start_at = ?, end_at = ?, experiment_enabled = ?, control_group_ratio = ?, fixed_cost = ?,
          cost_per_contact = ?, revenue_per_conversion = ?, retention_window_days = ?, updated_at = CURRENT_TIMESTAMP
          WHERE id = ?`, [next.name, next.description, next.channel, next.segment_code, next.status,
          dateValue(next.start_at), dateValue(next.end_at), next.experiment_enabled,
          next.control_group_ratio, next.fixed_cost, next.cost_per_contact,
          next.revenue_per_conversion, next.retention_window_days, id]);
        if (next.status !== current.status)
          await addEvent(tx, id, actor.id, 'status_changed', { from_status: current.status, to_status: next.status });
      });
      return this.getCampaign(id);
    } catch (error) {
      if (isDuplicate(error)) fail(409, 'A campaign with the same name already exists.');
      throw error;
    }
  }

  private targetFilters(query: Row): { where: string; params: unknown[] } {
    const predicates: string[] = [], params: unknown[] = [];
    if (query.status !== undefined) {
      if (!TARGET_STATES.includes(query.status)) fail(422, 'Invalid target status.');
      predicates.push('t.status = ?'); params.push(query.status);
    }
    for (const field of ['campaign_id', 'assigned_to_user_id', 'customer_id']) {
      if (query[field] !== undefined) { predicates.push(`t.${field} = ?`); params.push(positiveId(query[field])); }
    }
    if (query.campaign_name !== undefined) { predicates.push('t.campaign_name = ?'); params.push(query.campaign_name); }
    const converted = optionalBoolean(query.converted);
    if (converted !== null) { predicates.push('t.converted = ?'); params.push(converted); }
    return { where: predicates.length ? `WHERE ${predicates.join(' AND ')}` : '', params };
  }

  async listTargets(query: Row): Promise<Row> {
    const { page, pageSize, offset } = pageQuery(query);
    if (query.campaign_id !== undefined && !(await this.campaign(this.db, positiveId(query.campaign_id))))
      fail(404, 'The campaign was not found.');
    const { where, params } = this.targetFilters(query);
    const count = await this.db.one<Row>(`SELECT COUNT(*) AS total FROM campaign_targets t ${where}`, params);
    const allForStats = await this.db.query<Row>(`SELECT t.status, t.experiment_group, t.converted FROM campaign_targets t ${where}`, params);
    const rows = await this.db.query<Row>(`SELECT t.*, c.status AS campaign_status,
      a.display_name AS assigned_to_display_name FROM campaign_targets t
      LEFT JOIN campaigns c ON c.id = t.campaign_id LEFT JOIN users a ON a.id = t.assigned_to_user_id
      ${where} ORDER BY t.created_at DESC, t.id DESC LIMIT ? OFFSET ?`, [...params, pageSize, offset]);
    const total = numberValue(count?.total);
    return { items: rows.map(targetResponse), page, page_size: pageSize, total,
      total_pages: Math.ceil(total / pageSize), stats: campaignStats(allForStats) };
  }

  async listEvents(campaignId: number, query: Row): Promise<Row> {
    if (!(await this.campaign(this.db, campaignId))) fail(404, 'The campaign was not found.');
    const { page, pageSize, offset } = pageQuery(query, 50);
    const params: unknown[] = [campaignId];
    let where = 'WHERE e.campaign_id = ?';
    if (query.campaign_target_id !== undefined) { where += ' AND e.campaign_target_id = ?'; params.push(positiveId(query.campaign_target_id)); }
    const count = await this.db.one<Row>(`SELECT COUNT(*) AS total FROM campaign_events e ${where}`, params);
    const rows = await this.db.query<Row>(`SELECT e.*, u.display_name AS actor_display_name FROM campaign_events e
      LEFT JOIN users u ON u.id = e.actor_user_id ${where} ORDER BY e.created_at DESC, e.id DESC
      LIMIT ? OFFSET ?`, [...params, pageSize, offset]);
    return { items: rows.map((row) => ({ ...row, metadata_json: row.metadata_json ?? null,
      created_at: stamp(row.created_at) })), page, page_size: pageSize, total: numberValue(count?.total) };
  }

  async slaSummary(): Promise<Row> {
    const rows = await this.db.query<Row>(`SELECT i.risk_level, t.created_at, t.contacted_at
      FROM campaign_targets t JOIN customer_insights i ON i.id = t.customer_insight_id
      WHERE t.contacted_at IS NOT NULL AND t.experiment_group <> 'control' AND t.status <> 'cancelled'`);
    return { tiers: Object.entries({ low: 6, medium: 12, high: 4 }).map(([risk, target]) => {
      const durations = rows.filter((row) => row.risk_level === risk)
        .map((row) => (new Date(row.contacted_at).getTime() - new Date(row.created_at).getTime()) / 3600000);
      const met = durations.filter((hours) => hours <= target).length;
      return { risk_level: risk, target_hours: target, contacted_count: durations.length,
        met_count: met, met_rate: durations.length ? met / durations.length : null };
    }) };
  }

  async createTarget(payload: Row, actor: Actor): Promise<Row> {
    const insightId = positiveId(payload.customer_insight_id);
    if (!payload.campaign_id && !payload.campaign_name) fail(422, 'campaign_id or campaign_name is required');
    try {
      const id = await this.db.transaction(async (tx) => {
        const insight = await tx.one<Row>('SELECT * FROM customer_insights WHERE id = ?', [insightId]);
        if (!insight) fail(404, 'The customer insight was not found.');
        let campaign: Row | null;
        if (payload.campaign_id) {
          campaign = await this.campaign(tx, positiveId(payload.campaign_id), true);
          if (!campaign) fail(404, 'The campaign was not found.');
        } else {
          const name = String(payload.campaign_name).trim();
          if (!name || name.length > 150) fail(422, 'campaign_name must contain 1 to 150 characters.');
          campaign = await tx.one<Row>('SELECT * FROM campaigns WHERE name = ? FOR UPDATE', [name]);
          if (!campaign) {
            const result = await tx.execute('INSERT INTO campaigns (name, status, created_by_user_id) VALUES (?, ?, ?)',
              [name, 'draft', actor.id]);
            const campaignId = insertedId(result);
            await addEvent(tx, campaignId, actor.id, 'created', { to_status: 'draft',
              note: 'Created from legacy campaign_name target request.' });
            campaign = await this.campaign(tx, campaignId, true);
          }
        }
        let assignee: Row | null = null;
        if (payload.assigned_to_user_id !== undefined && payload.assigned_to_user_id !== null) {
          assignee = await tx.one<Row>('SELECT * FROM users WHERE id = ?', [positiveId(payload.assigned_to_user_id)]);
          if (!assignee) fail(404, 'The assigned user was not found.');
        }
        return this.createTargetInTx(tx, campaign!, insight, assignee, actor);
      });
      const target = await this.target(this.db, id);
      return targetResponse(target!);
    } catch (error) {
      if (isDuplicate(error)) fail(409, 'The campaign target already exists or conflicts with an active target.');
      throw error;
    }
  }

  async createTargetInTx(db: SqlClient, campaign: Row, insight: Row, assignee: Row | null,
    actor: Actor, bulkRunId: number | null = null): Promise<number> {
    if (!['draft', 'scheduled', 'active'].includes(campaign.status))
      fail(409, 'Targets can only be added to draft, scheduled, or active campaigns.');
    if (assignee && !booleanValue(assignee.is_active)) fail(422, 'The assigned user must be active.');
    if (assignee && assignee.role !== 'operations') fail(422, 'Only active operations users can be assigned.');
    const customerId = numberValue(insight.customer_id);
    const customer = await db.one<Row>('SELECT * FROM customers WHERE customer_id = ? FOR UPDATE', [customerId]);
    if (!customer) fail(422, 'The target customer was not found.');
    if (booleanValue(customer.marketing_opt_out)) fail(409, 'The customer has opted out of marketing contact.');
    const cutoff = new Date(Date.now() - 30 * 86400000);
    if (customer.last_contacted_at && new Date(customer.last_contacted_at).getTime() >= cutoff.getTime())
      fail(409, 'The customer was contacted within the contact cooldown period.');
    const recent = await db.one<Row>(`SELECT id FROM campaign_targets WHERE customer_id = ?
      AND status IN ('contacted', 'completed') AND processed_at >= ? LIMIT 1`, [customerId, cutoff]);
    if (recent) fail(409, 'The customer was contacted within the contact cooldown period.');
    const duplicate = await db.one<Row>('SELECT id FROM campaign_targets WHERE customer_id = ? AND campaign_id = ? LIMIT 1',
      [customerId, campaign.id]);
    if (duplicate) fail(409, 'The customer is already registered in this campaign.');
    const open = await db.query<Row>(`SELECT t.*, c.segment_code FROM campaign_targets t
      JOIN campaigns c ON c.id = t.campaign_id WHERE t.customer_id = ?
      AND t.status IN ('pending','assigned','contacted')
      AND c.status IN ('draft','scheduled','active','paused') FOR UPDATE`, [customerId]);
    const priority = SEGMENT_PRIORITY[campaign.segment_code] ?? 1000;
    for (const existing of open) {
      const existingPriority = SEGMENT_PRIORITY[existing.segment_code] ?? 1000;
      if (existing.status === 'contacted' || priority <= existingPriority)
        fail(409, 'The customer already has an equal-or-higher priority active campaign.');
    }
    for (const existing of open) {
      await db.execute('UPDATE campaign_targets SET status = ?, processed_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
        ['cancelled', new Date(), existing.id]);
      await addEvent(db, existing.campaign_id, actor.id, 'status_changed', {
        target_id: existing.id, from_status: existing.status, to_status: 'cancelled',
        note: `Preempted by higher-priority campaign ${campaign.id}.`,
        metadata_json: { replacement_campaign_id: campaign.id },
      });
    }
    const experimentGroup = this.experimentGroup(campaign, customerId);
    const assignedId = experimentGroup === 'treatment' ? assignee?.id ?? null : null;
    const status = assignedId ? 'assigned' : 'pending';
    const result = await db.execute(`INSERT INTO campaign_targets
      (customer_id, customer_insight_id, campaign_id, bulk_targeting_run_id, campaign_name,
       experiment_group, assigned_to_user_id, status, converted)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)`,
      [customerId, insight.id, campaign.id, bulkRunId, campaign.name, experimentGroup, assignedId, status]);
    const id = insertedId(result);
    await addEvent(db, campaign.id, actor.id, 'created', { target_id: id, to_status: status });
    if (assignedId) await addEvent(db, campaign.id, actor.id, 'assigned', {
      target_id: id, to_status: status, metadata_json: { assigned_to_user_id: assignedId },
    });
    return id;
  }

  private experimentGroup(campaign: Row, customerId: number): 'treatment' | 'control' {
    if (!booleanValue(campaign.experiment_enabled) || numberValue(campaign.control_group_ratio) <= 0) return 'treatment';
    const seedValue = campaign.experiment_seed || String(campaign.id);
    const key = campaign.experiment_assignment_version === 'sha256_campaign_customer_v1'
      ? `${seedValue}:${campaign.id}:${customerId}` : `${seedValue}:${customerId}`;
    const digest = sha256(key);
    const bucket = Number(digest.readBigUInt64BE(0)) / 2 ** 64;
    return bucket < numberValue(campaign.control_group_ratio) ? 'control' : 'treatment';
  }

  async updateTarget(id: number, payload: Row, actor: Actor): Promise<Row> {
    if (payload.status !== undefined && payload.status !== null && !TARGET_STATES.includes(payload.status)) fail(422, 'Invalid target status.');
    if (payload.result_code !== undefined && payload.result_code !== null && !RESULT_CODES.includes(payload.result_code)) fail(422, 'Invalid result_code.');
    if (payload.result !== undefined && payload.result !== null && String(payload.result).length > 100) fail(422, 'result is too long.');
    if (payload.result_notes !== undefined && payload.result_notes !== null && String(payload.result_notes).length > 2000) fail(422, 'result_notes is too long.');
    await this.db.transaction(async (tx) => {
      const target = await this.target(tx, id, true);
      if (!target) fail(404, 'The campaign target was not found.');
      const campaign = await this.campaign(tx, numberValue(target.campaign_id), true);
      if (!campaign) fail(422, 'The campaign target is not linked to a campaign.');
      const provided = (key: string) => Object.prototype.hasOwnProperty.call(payload, key);
      const anyUpdate = Object.values(payload).some((value) => value !== null && value !== undefined) ||
        provided('assigned_to_user_id') || provided('retained') || provided('outcome_revenue');
      if ((campaign.status === 'cancelled' || target.status === 'cancelled') && anyUpdate)
        fail(409, 'Cancelled campaign targets cannot be changed.');
      if (campaign.status === 'completed' && (payload.status != null || provided('assigned_to_user_id')))
        fail(409, 'A completed campaign does not allow target workflow changes.');
      let assignee: Row | null = null;
      if (provided('assigned_to_user_id') && payload.assigned_to_user_id !== null) {
        assignee = await tx.one<Row>('SELECT * FROM users WHERE id = ?', [positiveId(payload.assigned_to_user_id)]);
        if (!assignee) fail(404, 'The assigned user was not found.');
        if (!booleanValue(assignee.is_active)) fail(422, 'The assigned user must be active.');
        if (assignee.role !== 'operations') fail(422, 'Only active operations users can be assigned.');
      }
      if (actor.role === 'operations') {
        if (target.experiment_group === 'control') fail(403, 'Operations users cannot edit control-group outcomes.');
        if (target.assigned_to_user_id !== null && numberValue(target.assigned_to_user_id) !== actor.id)
          fail(403, 'Operations users can only process their own assigned targets.');
        if (assignee && numberValue(assignee.id) !== actor.id)
          fail(403, 'Operations users can only assign a target to themselves.');
      }
      const previous = target.status;
      let next = payload.status ?? previous;
      if (provided('assigned_to_user_id') && payload.status == null) {
        if (assignee && previous === 'pending') next = 'assigned';
        if (!assignee && previous === 'assigned') next = 'pending';
      }
      const assignedId = provided('assigned_to_user_id') ? assignee?.id ?? null : target.assigned_to_user_id;
      if (target.experiment_group === 'control' && ((provided('assigned_to_user_id') && assignee) ||
        ['assigned', 'contacted', 'completed'].includes(next)))
        fail(409, 'Control-group targets cannot be assigned or contacted.');
      if (next === 'assigned' && assignedId === null) fail(422, 'An assigned target must have an operations assignee.');
      const contactChange = (['contacted', 'completed'].includes(next) && next !== previous) || payload.result_code === 'contacted';
      if (target.experiment_group === 'treatment' && contactChange && campaign.status !== 'active')
        fail(409, 'Treatment targets can only be contacted or completed in an active campaign.');
      if (next !== previous && !targetTransitions[previous]?.includes(next))
        fail(409, `Target status cannot change from ${previous} to ${next}.`);
      if (provided('assigned_to_user_id') && !['pending', 'assigned'].includes(previous))
        fail(409, 'A target cannot be reassigned after contact has started.');
      const oldResult = { result_code: target.result_code, converted: booleanValue(target.converted),
        retained: target.retained === null ? null : booleanValue(target.retained),
        outcome_revenue: target.outcome_revenue === null ? null : numberValue(target.outcome_revenue) };
      const now = new Date();
      const updates: Row = {};
      if (provided('assigned_to_user_id')) {
        updates.assigned_to_user_id = assignedId;
        await addEvent(tx, campaign.id, actor.id, 'assigned', { target_id: id, from_status: previous,
          to_status: next, metadata_json: { from_assigned_to_user_id: target.assigned_to_user_id,
            assigned_to_user_id: assignedId } });
      }
      if (next !== previous) {
        updates.status = next;
        if (['contacted', 'completed'].includes(next)) {
          updates.processed_at = target.processed_at ?? now;
          await tx.execute('UPDATE customers SET last_contacted_at = ? WHERE customer_id = ?', [now, target.customer_id]);
        }
        if (next === 'contacted') updates.contacted_at = target.contacted_at ?? now;
        if (next === 'completed') updates.completed_at = target.completed_at ?? now;
        if (next === 'cancelled') updates.processed_at = target.processed_at ?? now;
        await addEvent(tx, campaign.id, actor.id, 'status_changed', { target_id: id,
          from_status: previous, to_status: next });
      }
      let resultCode = payload.result_code ?? target.result_code;
      let converted = provided('converted') && payload.converted !== null ? booleanValue(payload.converted) : booleanValue(target.converted);
      if (provided('result') && payload.result !== null) updates.result = payload.result;
      if (provided('result_notes') && payload.result_notes !== null) updates.result_notes = payload.result_notes;
      if (next === 'contacted' && !payload.result_code) resultCode = 'contacted';
      if (resultCode === 'contacted' && !['contacted', 'completed'].includes(next))
        fail(422, 'The contacted result code requires a contacted or completed target.');
      if (FINAL_RESULTS.has(resultCode) && target.experiment_group === 'treatment' && next !== 'completed')
        fail(422, 'A treatment result code requires a completed target.');
      if (next === 'completed' && target.experiment_group === 'treatment' && !FINAL_RESULTS.has(resultCode))
        fail(422, 'A completed treatment target requires a final structured result code.');
      if (provided('result_code') && resultCode === 'converted') converted = true;
      if (provided('result_code') && FINAL_RESULTS.has(resultCode) && resultCode !== 'converted') converted = false;
      if (provided('converted') && payload.converted !== null) {
        if (converted && target.experiment_group === 'treatment' && next !== 'completed')
          fail(422, 'A target must be completed before it can be marked converted.');
        resultCode = converted ? 'converted' : resultCode === 'converted' ? 'not_converted' : resultCode;
      }
      if (resultCode !== target.result_code) updates.result_code = resultCode;
      if (converted !== booleanValue(target.converted)) {
        updates.converted = converted;
        updates.converted_at = converted ? target.converted_at ?? now : null;
      }
      if (resultCode === 'opted_out')
        await tx.execute('UPDATE customers SET marketing_opt_out = 1 WHERE customer_id = ?', [target.customer_id]);
      if (provided('retained')) {
        if (payload.retained === null) { updates.retained = null; updates.retention_checked_at = null; }
        else {
          if (target.experiment_group === 'treatment' && next !== 'completed')
            fail(422, 'A treatment target must be completed before retention is recorded.');
          const anchor = target.experiment_group === 'treatment' ? updates.completed_at ?? target.completed_at
            : campaign.start_at ?? target.created_at;
          if (!anchor) fail(422, 'Retention cannot be recorded before the observation period starts.');
          if (Date.now() < new Date(anchor).getTime() + numberValue(campaign.retention_window_days) * 86400000)
            fail(422, 'Retention cannot be recorded before retention_window_days has elapsed.');
          updates.retained = booleanValue(payload.retained);
          updates.retention_checked_at = now;
        }
      }
      if (provided('outcome_revenue')) {
        if (payload.outcome_revenue !== null && numberValue(payload.outcome_revenue, -1) < 0)
          fail(422, 'Outcome revenue cannot be negative.');
        if (payload.outcome_revenue !== null && !converted)
          fail(422, 'Outcome revenue can only be recorded for a converted target.');
        updates.outcome_revenue = payload.outcome_revenue;
      }
      const changedResult = ['result', 'result_notes', 'result_code', 'converted', 'retained', 'outcome_revenue']
        .some((key) => provided(key)) || (next === 'contacted' && next !== previous);
      if (changedResult) await addEvent(tx, campaign.id, actor.id,
        provided('converted') || resultCode === 'converted' ? 'conversion_updated' : 'result_updated', {
          target_id: id, metadata_json: { before: oldResult, result_code: resultCode,
            converted, retained: updates.retained ?? target.retained,
            outcome_revenue: updates.outcome_revenue ?? target.outcome_revenue,
            experiment_group: target.experiment_group },
        });
      if (Object.keys(updates).length) {
        const fields = Object.keys(updates);
        await tx.execute(`UPDATE campaign_targets SET ${fields.map((field) => `${field} = ?`).join(', ')},
          updated_at = CURRENT_TIMESTAMP WHERE id = ?`, [...fields.map((field) => updates[field]), id]);
      }
    });
    return targetResponse((await this.target(this.db, id))!);
  }

  async updateContactPreferences(customerId: number, payload: Row): Promise<Row> {
    if (typeof payload.marketing_opt_out !== 'boolean') fail(422, 'marketing_opt_out is required.');
    const customer = await this.db.one<Row>('SELECT customer_id FROM customers WHERE customer_id = ?', [customerId]);
    if (!customer) fail(404, 'The customer was not found.');
    await this.db.execute('UPDATE customers SET marketing_opt_out = ?, updated_at = CURRENT_TIMESTAMP WHERE customer_id = ?',
      [payload.marketing_opt_out, customerId]);
    const updated = await this.db.one<Row>('SELECT customer_id, marketing_opt_out, last_contacted_at FROM customers WHERE customer_id = ?', [customerId]);
    return { customer_id: numberValue(updated!.customer_id), marketing_opt_out: booleanValue(updated!.marketing_opt_out),
      last_contacted_at: stamp(updated!.last_contacted_at) };
  }
}

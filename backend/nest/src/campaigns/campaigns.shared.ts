import { createHash, randomBytes } from 'node:crypto';
import { HttpException } from '@nestjs/common';
import type { DatabaseService } from '../database/database.service';

export type Row = Record<string, any>;
export type SqlClient = Pick<DatabaseService, 'query' | 'one' | 'execute'>;
export type Actor = { id: number; role: string; display_name?: string };

export const CAMPAIGN_STATES = ['draft', 'scheduled', 'active', 'paused', 'completed', 'cancelled'] as const;
export const TARGET_STATES = ['pending', 'assigned', 'contacted', 'completed', 'cancelled'] as const;
export const SEGMENTS = [
  'high_risk_retention', 'medium_reactivation', 'low_risk_upsell',
  'small_balance_decline', 'dormant_full_payer', 'active_full_payer', 'stable_prime',
] as const;
export const RESULT_CODES = [
  'contacted', 'converted', 'not_converted', 'no_response', 'declined', 'opted_out', 'invalid_contact',
] as const;
export const FINAL_RESULTS = new Set(RESULT_CODES.filter((code) => code !== 'contacted'));
export const OPEN_TARGET_STATES = ['pending', 'assigned', 'contacted'];
export const OPEN_CAMPAIGN_STATES = ['draft', 'scheduled', 'active', 'paused'];
export const SEGMENT_PRIORITY: Record<string, number> = {
  small_balance_decline: 400, dormant_full_payer: 350, high_risk_retention: 300,
  medium_reactivation: 200, active_full_payer: 120, low_risk_upsell: 100, stable_prime: 90,
};

export function fail(status: number, detail: string): never {
  throw new HttpException({ detail }, status);
}

export function numberValue(value: unknown, fallback = 0): number {
  if (value === null || value === undefined || value === '') return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function booleanValue(value: unknown): boolean {
  return value === true || value === 1 || value === '1' || value === 'true';
}

export function jsonValue(value: unknown): Row {
  if (typeof value === 'string') {
    try { return JSON.parse(value) as Row; } catch { return {}; }
  }
  return value && typeof value === 'object' ? value as Row : {};
}

export function positiveId(value: unknown): number {
  const id = Number(value);
  if (!Number.isSafeInteger(id) || id < 1) fail(422, 'A positive integer is required.');
  return id;
}

export function pageQuery(query: Row, defaultSize = 20): { page: number; pageSize: number; offset: number } {
  const page = query.page === undefined ? 1 : positiveId(query.page);
  const pageSize = query.page_size === undefined ? defaultSize : positiveId(query.page_size);
  if (pageSize > 100) fail(422, 'page_size must be between 1 and 100.');
  return { page, pageSize, offset: (page - 1) * pageSize };
}

export function optionalBoolean(value: unknown): boolean | null {
  if (value === undefined || value === null) return null;
  if (value === true || value === 'true' || value === '1' || value === 1) return true;
  if (value === false || value === 'false' || value === '0' || value === 0) return false;
  fail(422, 'A boolean value is required.');
}

export function dateValue(value: unknown): Date | null {
  if (value === undefined || value === null || value === '') return null;
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) fail(422, 'A valid date-time is required.');
  return date;
}

export function stamp(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (value instanceof Date) return value.toISOString();
  return String(value);
}

export function dateOnly(value: unknown): string | null {
  const valueString = stamp(value);
  return valueString ? valueString.slice(0, 10) : null;
}

export function sha256(value: string): Buffer {
  return createHash('sha256').update(value).digest();
}

export function seed(): string { return randomBytes(16).toString('hex'); }

export function insertedId(result: unknown): number {
  const row = Array.isArray(result) ? result[0] : result;
  return numberValue((row as Row | undefined)?.insertId);
}

export function isDuplicate(error: unknown): boolean {
  const code = (error as Row | undefined)?.code;
  return code === 'ER_DUP_ENTRY' || code === 'SQLITE_CONSTRAINT_UNIQUE';
}

export function campaignStats(rows: Row[]): Row {
  const counts: Record<string, number> = Object.fromEntries(TARGET_STATES.map((state) => [state, 0]));
  let unprocessed = 0, contacted = 0, converted = 0;
  for (const row of rows) {
    counts[String(row.status)] = (counts[String(row.status)] ?? 0) + 1;
    if (row.experiment_group !== 'control' && ['pending', 'assigned'].includes(row.status)) unprocessed++;
    if (['contacted', 'completed'].includes(row.status)) contacted++;
    if (booleanValue(row.converted)) converted++;
  }
  return { total_targets: rows.length, unprocessed_targets: unprocessed,
    contacted_targets: contacted, converted_targets: converted, status_counts: counts };
}

export function campaignResponse(row: Row, stats: Row): Row {
  return {
    id: numberValue(row.id), name: row.name, description: row.description ?? null,
    channel: row.channel ?? null, segment_code: row.segment_code ?? null,
    status: row.status, start_at: stamp(row.start_at), end_at: stamp(row.end_at),
    experiment_enabled: booleanValue(row.experiment_enabled),
    control_group_ratio: numberValue(row.control_group_ratio),
    experiment_policy_locked: stats.total_targets > 0,
    experiment_assignment_version: row.experiment_assignment_version,
    fixed_cost: numberValue(row.fixed_cost), cost_per_contact: numberValue(row.cost_per_contact),
    revenue_per_conversion: numberValue(row.revenue_per_conversion),
    retention_window_days: numberValue(row.retention_window_days),
    created_by_user_id: row.created_by_user_id ?? null,
    created_by_display_name: row.created_by_display_name ?? null,
    created_at: stamp(row.created_at), updated_at: stamp(row.updated_at), stats,
  };
}

export function targetResponse(row: Row): Row {
  return {
    id: numberValue(row.id), customer_id: numberValue(row.customer_id),
    customer_insight_id: numberValue(row.customer_insight_id), campaign_id: row.campaign_id ?? null,
    campaign_name: row.campaign_name, experiment_group: row.experiment_group,
    bulk_targeting_run_id: row.bulk_targeting_run_id ?? null,
    campaign_status: row.campaign_status ?? null,
    assigned_to_user_id: row.assigned_to_user_id ?? null,
    assigned_to_display_name: row.assigned_to_display_name ?? null,
    status: row.status, processed_at: stamp(row.processed_at), contacted_at: stamp(row.contacted_at),
    completed_at: stamp(row.completed_at), converted_at: stamp(row.converted_at),
    result: row.result ?? null, result_notes: row.result_notes ?? null,
    result_code: row.result_code ?? null, converted: booleanValue(row.converted),
    retained: row.retained === null || row.retained === undefined ? null : booleanValue(row.retained),
    retention_checked_at: stamp(row.retention_checked_at),
    outcome_revenue: row.outcome_revenue === null || row.outcome_revenue === undefined ? null : numberValue(row.outcome_revenue),
    created_at: stamp(row.created_at), updated_at: stamp(row.updated_at),
  };
}

export async function addEvent(db: SqlClient, campaignId: number, actorId: number | null,
  eventType: string, options: Row = {}): Promise<void> {
  await db.execute(
    `INSERT INTO campaign_events (campaign_id, campaign_target_id, event_type, from_status, to_status,
      actor_user_id, note, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
    [campaignId, options.target_id ?? null, eventType, options.from_status ?? null,
      options.to_status ?? null, actorId, options.note ?? null,
      options.metadata_json === undefined ? null : JSON.stringify(options.metadata_json)],
  );
}

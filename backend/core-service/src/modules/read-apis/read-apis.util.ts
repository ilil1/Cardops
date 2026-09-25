import { HttpException, HttpStatus } from '@nestjs/common';

export type Row = Record<string, any>;
export type InsightFilters = {
  riskLevel?: string;
  clusterName?: string;
  customerId?: number;
  campaignCandidatesOnly?: boolean;
  campaignId?: number;
};

export function detail(status: number, message: string): never {
  throw new HttpException({ detail: message }, status);
}

export function positiveInteger(value: unknown, name: string, fallback?: number, max?: number): number {
  if (value === undefined || value === null) {
    if (fallback !== undefined) return fallback;
    return detail(HttpStatus.UNPROCESSABLE_ENTITY, `${name} is required.`);
  }
  if (typeof value !== 'string' && typeof value !== 'number') {
    return detail(HttpStatus.UNPROCESSABLE_ENTITY, `${name} must be an integer greater than zero.`);
  }
  if (!/^\+?\d+$/.test(String(value))) {
    return detail(HttpStatus.UNPROCESSABLE_ENTITY, `${name} must be an integer greater than zero.`);
  }
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 1 || (max !== undefined && parsed > max)) {
    return detail(HttpStatus.UNPROCESSABLE_ENTITY, `${name} must be an integer between 1 and ${max ?? 'infinity'}.`);
  }
  return parsed;
}

export function optionalPositiveInteger(value: unknown, name: string): number | undefined {
  if (value === undefined || value === null) return undefined;
  return positiveInteger(value, name);
}

export function riskLevel(value: unknown, status = HttpStatus.UNPROCESSABLE_ENTITY): string | undefined {
  if (value === undefined || value === null) return undefined;
  if (value !== 'low' && value !== 'medium' && value !== 'high') {
    return detail(status, status === 400 ? `Unsupported risk_level: ${String(value)}` : 'risk_level must be low, medium, or high.');
  }
  return value;
}

export function boundedString(value: unknown, name: string, max = 100): string | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value !== 'string' || value.length < 1 || value.length > max) {
    return detail(HttpStatus.UNPROCESSABLE_ENTITY, `${name} must contain 1 to ${max} characters.`);
  }
  return value;
}

export function booleanQuery(value: unknown, fallback = false): boolean {
  if (value === undefined || value === null) return fallback;
  if (value === true) return true;
  if (value === false) return false;
  if (typeof value === 'string') {
    const normalized = value.toLowerCase();
    if (['true', '1', 'on', 'yes'].includes(normalized)) return true;
    if (['false', '0', 'off', 'no'].includes(normalized)) return false;
  }
  return detail(HttpStatus.UNPROCESSABLE_ENTITY, 'campaign_candidates_only must be a boolean.');
}

export function numeric(value: unknown): number {
  return Number(value ?? 0);
}

export function nullableNumeric(value: unknown): number | null {
  return value == null ? null : Number(value);
}

export function dateOnly(value: unknown): string | null {
  if (value == null) return null;
  if (value instanceof Date) return value.toISOString().slice(0, 10);
  return String(value).slice(0, 10);
}

export function isoDateTime(value: unknown): string | null {
  if (value == null) return null;
  if (value instanceof Date) return value.toISOString();
  const raw = String(value);
  return new Date(/(?:Z|[+-]\d\d:?\d\d)$/.test(raw) ? raw : `${raw.replace(' ', 'T')}Z`).toISOString();
}

export function reasonCodes(value: unknown): string[] | Record<string, unknown> | null {
  if (value == null) return null;
  if (typeof value === 'string') {
    try { return reasonCodes(JSON.parse(value)); } catch { return null; }
  }
  return Array.isArray(value) || (typeof value === 'object' && value !== null) ? value as string[] | Record<string, unknown> : null;
}

export function reasonCodeList(value: unknown): string[] {
  const parsed = reasonCodes(value);
  if (Array.isArray(parsed)) return parsed.map(String);
  if (parsed && typeof parsed === 'object') return Object.keys(parsed);
  return [];
}

const CUSTOMER_FIELDS = [
  'customer_id', 'customer_age', 'gender', 'dependent_count', 'education_level',
  'marital_status', 'income_category', 'card_category', 'months_on_book',
  'total_relationship_count', 'months_inactive_12_mon', 'contacts_count_12_mon',
  'credit_limit', 'total_revolving_bal', 'avg_open_to_buy', 'total_amt_chng_q4_q1',
  'total_trans_amt', 'total_trans_ct', 'total_ct_chng_q4_q1', 'avg_utilization_ratio',
] as const;

export function customerResponse(row: Row): Row {
  const customer: Row = {};
  for (const field of CUSTOMER_FIELDS) customer[field] = row[field];
  customer.customer_id = numeric(customer.customer_id);
  customer.credit_limit = numeric(customer.credit_limit);
  customer.avg_open_to_buy = numeric(customer.avg_open_to_buy);
  customer.total_amt_chng_q4_q1 = numeric(customer.total_amt_chng_q4_q1);
  customer.total_ct_chng_q4_q1 = numeric(customer.total_ct_chng_q4_q1);
  customer.avg_utilization_ratio = numeric(customer.avg_utilization_ratio);
  customer.marketing_opt_out = Boolean(row.marketing_opt_out);
  customer.last_contacted_at = isoDateTime(row.last_contacted_at);
  customer.created_at = isoDateTime(row.created_at);
  customer.updated_at = isoDateTime(row.updated_at);
  return customer;
}

export function snapshotResponse(row: Row | undefined): Row | null {
  if (!row) return null;
  const snapshot: Row = {};
  for (const field of CUSTOMER_FIELDS) snapshot[field] = row[field];
  snapshot.id = numeric(row.id);
  snapshot.customer_id = numeric(row.customer_id);
  snapshot.feature_sha256 = row.feature_sha256;
  snapshot.source_dataset_sha256 = row.source_dataset_sha256;
  snapshot.as_of_date = dateOnly(row.as_of_date);
  snapshot.as_of_at = isoDateTime(row.as_of_at);
  return snapshot;
}

export function insightResponse(row: Row): Row {
  return {
    id: numeric(row.id), customer_id: numeric(row.customer_id),
    customer_snapshot_id: nullableNumeric(row.customer_snapshot_id),
    scoring_batch_id: nullableNumeric(row.scoring_batch_id),
    as_of_date: dateOnly(row.as_of_date),
    classification_run_id: numeric(row.classification_run_id),
    regression_run_id: numeric(row.regression_run_id),
    clustering_run_id: numeric(row.clustering_run_id),
    churn_probability: numeric(row.churn_probability), risk_level: row.risk_level,
    expected_transaction_count: numeric(row.expected_transaction_count),
    activity_gap: numeric(row.activity_gap), total_trans_amt: numeric(row.total_trans_amt),
    card_category: row.card_category, contacts_count_12_mon: numeric(row.contacts_count_12_mon),
    cluster_name: row.cluster_name, cluster_confidence: nullableNumeric(row.cluster_confidence),
    recommended_action: row.recommended_action, reason_codes: reasonCodes(row.reason_codes),
    scored_at: isoDateTime(row.scored_at),
  };
}

export function modelRunResponse(row: Row): Row {
  return {
    id: numeric(row.id), task: row.task, model_name: row.model_name,
    model_version: row.model_version, artifact_sha256: row.artifact_sha256,
    dataset_sha256: row.dataset_sha256, scoring_batch_id: nullableNumeric(row.scoring_batch_id),
    decision_policy_sha256: row.decision_policy_sha256,
    medium_threshold: nullableNumeric(row.medium_threshold),
    high_threshold: nullableNumeric(row.high_threshold),
    activity_gap_quantile: nullableNumeric(row.activity_gap_quantile),
    status: row.status, processed_rows: nullableNumeric(row.processed_rows),
    started_at: isoDateTime(row.started_at), completed_at: isoDateTime(row.completed_at),
  };
}

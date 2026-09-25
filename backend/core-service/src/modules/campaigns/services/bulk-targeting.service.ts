import { CampaignEventsRepository } from '../repositories/campaign-events.repository';
import { Injectable } from '@nestjs/common';
import { UnitOfWork } from '../../../infrastructure/database/unit-of-work';
import { BulkTargetingRepository } from '../repositories/bulk-targeting.repository';
import { CampaignsService } from './campaigns.service';
import {
  Actor, OPEN_CAMPAIGN_STATES, OPEN_TARGET_STATES, Row, SEGMENT_PRIORITY, SEGMENTS,
  SqlClient, booleanValue, dateOnly, fail, insertedId, isDuplicate,
  jsonValue, numberValue, pageQuery, positiveId, seed, sha256, stamp,
} from '../campaigns.shared';

const defaultNames: Record<string, string> = {
  high_risk_retention: '고위험 고객 리텐션 일괄 캠페인',
  medium_reactivation: '중위험 고객 재활성화 일괄 캠페인',
  low_risk_upsell: '우량 고객 업셀링 일괄 캠페인',
  small_balance_decline: '소액 잔액·거래 급감 긴급 컨택',
  dormant_full_payer: '완납형 저활동 고객 리텐션',
  active_full_payer: '완납형 우량 고객 거래 활성화',
  stable_prime: '안정 우량 고객 업셀링',
};
const defaultDescriptions: Record<string, string> = {
  high_risk_retention: '선정 근거: 이탈 예측 모델이 고위험(high)으로 분류한 고객입니다. 이탈 확률이 높은 순으로 우선 배정합니다.',
  medium_reactivation: '선정 근거: 중위험(medium)이면서 활동성 갭이 하위 분위수에 속하는 고객입니다. 예상 대비 거래가 줄어든 정도가 큰 순으로 배정합니다.',
  low_risk_upsell: "선정 근거: 저위험(low)이면서 '우량(예상이상)' 군집에 속하는 고객입니다. 예상 거래 건수가 많은 순으로 배정합니다.",
  small_balance_decline: '선정 근거: 리볼빙 잔액이 1~499원으로 소액인데 분기 거래건수가 0.6배 미만으로 급감한 고객입니다. 이 조건의 실제 이탈률은 약 90% 전체 평균 16.1%의 5배가 넘습니다. 대상 수는 적지만 이탈이 임박한 신호이므로 가장 먼저 컨택합니다.',
  dormant_full_payer: '선정 근거: 리볼빙 잔액이 0원(완납)이면서 연간 거래가 55건 미만인 고객입니다. 완납 고객 전체의 실제 이탈률은 36.2%인데, 그중 거래가 저조한 이 그룹만 보면 72.0%로 치솟습니다 잔액이 없어 전환 비용이 없고 카드 사용도 줄어든 상태라 이탈 직전으로 판단합니다.',
  active_full_payer: '선정 근거: 리볼빙 잔액이 0원(완납)이지만 연간 거래가 55건 이상인 고객입니다. 같은 완납 고객이라도 거래가 활발하면 실제 이탈률이 12.2%로 전체 평균(16.1%)보다 낮습니다. 이미 안정적인 고객이므로 리볼빙 잔액을 늘리도록 유도하지 않고, 거래 리워드와 상품 교차판매로 관계를 넓히는 것을 목표로 합니다.',
  stable_prime: '선정 근거: 리볼빙 잔액이 1,000~1,999원 구간인 고객입니다. 이 구간의 실제 이탈률은 4.6%로 전체 잔액 구간 중 가장 낮습니다. 잔액이 0원이거나 2,000원을 넘으면 이탈률이 다시 올라가므로(각 36.2%, 15.3%) 이 구간을 유지시키는 것이 목표이며, 한도 상향·프리미엄 전환 제안에 적합합니다.',
};

type Candidate = { insight: Row; customer: Row; exclusion: string | null; selected?: boolean };
type Scan = { evaluated: Candidate[]; eligible: Candidate[]; skippedActive: number; skippedRecent: number; skippedOptOut: number };

function quantile(values: number[], fraction: number): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const position = (sorted.length - 1) * fraction;
  const low = Math.floor(position), high = Math.min(low + 1, sorted.length - 1);
  return sorted[low]! + (sorted[high]! - sorted[low]!) * (position - low);
}

function text(value: unknown): string | null {
  if (value === undefined || value === null) return null;
  const normalized = String(value).trim();
  return normalized || null;
}

function validatePreview(payload: Row, internalRerun = false): void {
  const accepted = new Set([
    'segment', 'campaign_name', 'description', 'channel', 'assigned_to_user_id',
    'recent_contact_days', 'activity_gap_quantile', 'cluster_name', 'max_targets',
    'source_as_of_date', 'scoring_batch_id', 'experiment_enabled', 'control_group_ratio',
    'fixed_cost', 'cost_per_contact', 'revenue_per_conversion', 'retention_window_days',
    ...(internalRerun ? ['decision_policy_id', 'dataset_sha256', 'activity_gap_threshold', 'experiment_seed'] : []),
  ]);
  if (Object.keys(payload).some((key) => !accepted.has(key))) fail(422, 'Extra inputs are not permitted.');
  if (!SEGMENTS.includes(payload.segment)) fail(422, 'Invalid targeting segment.');
  for (const field of ['campaign_name', 'description', 'channel', 'cluster_name']) {
    if (payload[field] !== undefined && payload[field] !== null && typeof payload[field] !== 'string')
      fail(422, `${field} must be a string.`);
  }
  if (payload.campaign_name !== undefined && text(payload.campaign_name) && text(payload.campaign_name)!.length > 150)
    fail(422, 'campaign_name is too long.');
  if (payload.description !== undefined && text(payload.description) && text(payload.description)!.length > 4000)
    fail(422, 'description is too long.');
  if (payload.channel !== undefined && text(payload.channel) && text(payload.channel)!.length > 30)
    fail(422, 'channel is too long.');
  if (payload.cluster_name !== undefined && text(payload.cluster_name) && text(payload.cluster_name)!.length > 100)
    fail(422, 'cluster_name is too long.');
  for (const field of ['recent_contact_days', 'activity_gap_quantile', 'max_targets', 'control_group_ratio',
    'fixed_cost', 'cost_per_contact', 'revenue_per_conversion', 'retention_window_days']) {
    if (payload[field] !== undefined && payload[field] !== null &&
      (payload[field] === '' || !Number.isFinite(Number(payload[field]))))
      fail(422, `${field} must be a number.`);
  }
  if (payload.experiment_enabled !== undefined && payload.experiment_enabled !== null &&
    typeof payload.experiment_enabled !== 'boolean') fail(422, 'experiment_enabled must be a boolean.');
  if (payload.assigned_to_user_id != null) positiveId(payload.assigned_to_user_id);
  if (payload.scoring_batch_id != null) positiveId(payload.scoring_batch_id);
  if (payload.source_as_of_date != null &&
    (typeof payload.source_as_of_date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(payload.source_as_of_date) ||
      Number.isNaN(new Date(payload.source_as_of_date).getTime())))
    fail(422, 'source_as_of_date must be a date.');
  const days = numberValue(payload.recent_contact_days, 30);
  const q = numberValue(payload.activity_gap_quantile, 0.2);
  const max = numberValue(payload.max_targets, 1000);
  const ratio = numberValue(payload.control_group_ratio, 0.2);
  const retentionDays = numberValue(payload.retention_window_days, 30);
  if (!Number.isInteger(days) || days < 0 || days > 365) fail(422, 'recent_contact_days must be between 0 and 365.');
  if (q <= 0 || q > 0.5) fail(422, 'activity_gap_quantile must be greater than 0 and at most 0.5.');
  if (!Number.isInteger(max) || max < 1 || max > 10000) fail(422, 'max_targets must be between 1 and 10000.');
  if (ratio < 0 || ratio >= 1 || (booleanValue(payload.experiment_enabled) && ratio <= 0))
    fail(422, 'control_group_ratio must be greater than 0 for A/B tests');
  if (['fixed_cost', 'cost_per_contact', 'revenue_per_conversion'].some((field) => numberValue(payload[field]) < 0))
    fail(422, 'Campaign financial values cannot be negative.');
  if (!Number.isInteger(retentionDays) || retentionDays < 1 || retentionDays > 365)
    fail(422, 'retention_window_days must be between 1 and 365.');
}

function segmentMatches(row: Row, rules: Row): boolean {
  switch (rules.segment) {
    case 'high_risk_retention': return row.risk_level === 'high';
    case 'medium_reactivation': return row.risk_level === 'medium' &&
      numberValue(row.activity_gap) <= numberValue(rules.activity_gap_threshold);
    case 'low_risk_upsell': return row.risk_level === 'low' && row.cluster_name === rules.cluster_name;
    case 'small_balance_decline': return numberValue(row.total_revolving_bal) > 0 &&
      numberValue(row.total_revolving_bal) < 500 && numberValue(row.total_ct_chng_q4_q1) < 0.6;
    case 'dormant_full_payer': return numberValue(row.total_revolving_bal) === 0 && numberValue(row.total_trans_ct) < 55;
    case 'active_full_payer': return numberValue(row.total_revolving_bal) === 0 && numberValue(row.total_trans_ct) >= 55;
    case 'stable_prime': return numberValue(row.total_revolving_bal) >= 1000 && numberValue(row.total_revolving_bal) < 2000;
    default: return false;
  }
}

function candidateOrder(a: Row, b: Row, segment: string): number {
  const desc = (key: string) => numberValue(b[key]) - numberValue(a[key]);
  const asc = (key: string) => numberValue(a[key]) - numberValue(b[key]);
  const recent = () => new Date(b.scored_at).getTime() - new Date(a.scored_at).getTime();
  if (segment === 'high_risk_retention') return desc('churn_probability') || asc('activity_gap') || recent();
  if (segment === 'medium_reactivation') return asc('activity_gap') || desc('churn_probability') || recent();
  if (['small_balance_decline', 'dormant_full_payer'].includes(segment))
    return asc('total_trans_ct') || asc('total_ct_chng_q4_q1') || desc('churn_probability');
  if (['active_full_payer', 'stable_prime'].includes(segment))
    return desc('total_trans_ct') || desc('total_trans_amt') || asc('churn_probability');
  return desc('expected_transaction_count') || desc('activity_gap') || asc('churn_probability');
}

@Injectable()
export class BulkTargetingService {
  constructor(private readonly events: CampaignEventsRepository, private readonly unitOfWork: UnitOfWork, private readonly repository: BulkTargetingRepository, private readonly campaigns: CampaignsService) {}

  private async buildRules(db: SqlClient | undefined, payload: Row, overrideSeed?: string): Promise<Row> {
    const batchId = payload.scoring_batch_id == null ? undefined : positiveId(payload.scoring_batch_id);
    const batch = await this.repository.findScoringBatch(batchId, payload.source_as_of_date, db);
    if (!batch) fail(422, 'A succeeded scoring batch is required for bulk targeting.');
    const enabled = booleanValue(payload.experiment_enabled);
    const rules: Row = {
      segment: payload.segment,
      campaign_name: text(payload.campaign_name) ?? defaultNames[payload.segment],
      description: text(payload.description) ?? defaultDescriptions[payload.segment],
      channel: text(payload.channel),
      assigned_to_user_id: payload.assigned_to_user_id ?? null,
      recent_contact_days: numberValue(payload.recent_contact_days, 30),
      activity_gap_quantile: numberValue(payload.activity_gap_quantile, 0.2),
      cluster_name: text(payload.cluster_name) ?? '우량(예상이상)',
      max_targets: numberValue(payload.max_targets, 1000),
      source_as_of_date: dateOnly(batch.as_of_date),
      scoring_batch_id: numberValue(batch.id),
      decision_policy_id: batch.decision_policy_id,
      dataset_sha256: batch.dataset_sha256,
      experiment_enabled: enabled,
      control_group_ratio: enabled ? numberValue(payload.control_group_ratio, 0.2) : 0,
      fixed_cost: numberValue(payload.fixed_cost),
      cost_per_contact: numberValue(payload.cost_per_contact),
      revenue_per_conversion: numberValue(payload.revenue_per_conversion),
      retention_window_days: numberValue(payload.retention_window_days, 30),
      experiment_seed: overrideSeed ?? seed(),
    };
    if (payload.segment === 'medium_reactivation') {
      const gaps = await this.repository.activityGaps(batch.id, db);
      rules.activity_gap_threshold = quantile(gaps.map((row) => numberValue(row.activity_gap)), rules.activity_gap_quantile);
    }
    return rules;
  }

  private async scan(db: SqlClient | undefined, rules: Row): Promise<Scan> {
    const rows = await this.repository.scoredCustomers(rules.scoring_batch_id, db);
    const matches = rows.filter((row) => segmentMatches(row, rules)).sort((a, b) => candidateOrder(a, b, rules.segment));
    if (!matches.length) return { evaluated: [], eligible: [], skippedActive: 0, skippedRecent: 0, skippedOptOut: 0 };
    const customerIds = matches.map((row) => row.customer_id);
    const targets = await this.repository.customerTargets(customerIds, db);
    const byCustomer = new Map<number, Row[]>();
    for (const target of targets) {
      const id = numberValue(target.customer_id);
      byCustomer.set(id, [...byCustomer.get(id) ?? [], target]);
    }
    const cutoff = Date.now() - numberValue(rules.recent_contact_days) * 86400000;
    const priority = SEGMENT_PRIORITY[rules.segment] ?? 0;
    const evaluated: Candidate[] = [], eligible: Candidate[] = [];
    let skippedActive = 0, skippedRecent = 0, skippedOptOut = 0;
    for (const insight of matches) {
      const history = byCustomer.get(numberValue(insight.customer_id)) ?? [];
      const active = history.some((target) => OPEN_TARGET_STATES.includes(target.status) &&
        OPEN_CAMPAIGN_STATES.includes(target.campaign_status) &&
        (target.status === 'contacted' || (SEGMENT_PRIORITY[target.segment_code] ?? 1000) >= priority));
      const recent = (insight.last_contacted_at && new Date(insight.last_contacted_at).getTime() >= cutoff) ||
        history.some((target) => ['contacted', 'completed'].includes(target.status) &&
          target.processed_at && new Date(target.processed_at).getTime() >= cutoff);
      const exclusion = booleanValue(insight.marketing_opt_out) ? 'opted_out' : active ? 'active_campaign' : recent ? 'recent_contact' : null;
      const candidate = { insight, customer: insight, exclusion };
      evaluated.push(candidate);
      if (exclusion === 'opted_out') skippedOptOut++;
      else if (exclusion === 'active_campaign') skippedActive++;
      else if (exclusion === 'recent_contact') skippedRecent++;
      else eligible.push(candidate);
    }
    return { evaluated, eligible, skippedActive, skippedRecent, skippedOptOut };
  }

  private async previewInTx(db: SqlClient | undefined, payload: Row, actor: Actor, rerunOfId?: number,
    overrideSeed?: string): Promise<number> {
    validatePreview(payload, rerunOfId !== undefined);
    if (payload.assigned_to_user_id !== undefined && payload.assigned_to_user_id !== null) {
      const assignee = await this.repository.findAssigneeRole(positiveId(payload.assigned_to_user_id), db);
      if (!assignee) fail(422, 'The assigned user was not found.');
      if (!booleanValue(assignee.is_active)) fail(422, 'The assigned user must be active.');
      if (assignee.role !== 'operations') fail(422, 'Only active operations users can be assigned.');
    }
    const rules = await this.buildRules(db, payload, overrideSeed);
    const scan = await this.scan(db, rules);
    const selectedIds = new Set(scan.eligible.slice(0, rules.max_targets).map((item) => numberValue(item.insight.customer_id)));
    const result = await this.repository.insertRun(rules.segment, actor.id, rerunOfId ?? null, rules.scoring_batch_id, rules.source_as_of_date, JSON.stringify(rules), selectedIds.size, scan.eligible.length, scan.skippedActive, scan.skippedRecent, scan.skippedOptOut, db);
    const runId = insertedId(result);
    for (const [index, candidate] of scan.evaluated.entries()) {
      await this.repository.insertCandidate(runId, candidate.insight.customer_id, candidate.insight.id, index + 1, candidate.exclusion === null, selectedIds.has(numberValue(candidate.insight.customer_id)), candidate.exclusion, db);
    }
    return runId;
  }

  async preview(payload: Row, actor: Actor): Promise<Row> {
    const id = await this.unitOfWork.transaction((tx) => this.previewInTx(tx, payload ?? {}, actor));
    return this.get(id);
  }

  private async run(db: SqlClient | undefined, id: number, lock = false): Promise<Row | null> {
    return this.repository.findRun(lock, id, db);
  }

  private async response(db: SqlClient | undefined, run: Row, includePreview: boolean): Promise<Row> {
    const rules = { ...jsonValue(run.rules_json) };
    const experimentSeed = rules.experiment_seed;
    delete rules.experiment_seed;
    if (experimentSeed) {
      rules.experiment_assignment_policy = 'sha256_seed_customer_v1';
      rules.experiment_seed_sha256 = sha256(String(experimentSeed)).toString('hex');
    }
    const selected = includePreview ? await this.repository.selectedInsights(run.id, db) : [];
    return {
      id: numberValue(run.id), segment: run.segment_code, status: run.status,
      campaign_id: run.campaign_id ?? null, campaign_name: rules.campaign_name,
      campaign_status: run.campaign_status ?? null,
      requested_by_user_id: run.requested_by_user_id ?? null,
      rerun_of_id: run.rerun_of_id ?? null,
      source_as_of_date: dateOnly(run.source_as_of_date), scoring_batch_id: run.scoring_batch_id ?? null,
      rules, preview_count: numberValue(run.preview_count), eligible_count: numberValue(run.eligible_count),
      created_count: numberValue(run.created_count),
      skipped_active_campaign_count: numberValue(run.skipped_active_campaign_count),
      skipped_recent_contact_count: numberValue(run.skipped_recent_contact_count),
      skipped_opt_out_count: numberValue(run.skipped_opt_out_count),
      cancelled_target_count: numberValue(run.cancelled_target_count),
      items: selected.map((row) => ({
        customer_id: numberValue(row.customer_id), customer_insight_id: numberValue(row.id),
        risk_level: row.risk_level, cluster_name: row.cluster_name,
        churn_probability: numberValue(row.churn_probability),
        expected_transaction_count: numberValue(row.expected_transaction_count),
        activity_gap: numberValue(row.activity_gap), recommended_action: row.recommended_action,
        as_of_date: dateOnly(row.as_of_date),
      })),
      created_at: stamp(run.created_at), executed_at: stamp(run.executed_at), cancelled_at: stamp(run.cancelled_at),
    };
  }

  async list(query: Row): Promise<Row> {
    const { page, pageSize, offset } = pageQuery(query);
    const count = await this.repository.countRuns();
    const runs = await this.repository.listRuns(pageSize, offset);
    const items = await Promise.all(runs.map((run) => this.response(undefined, run, false)));
    const total = numberValue(count?.total);
    return { items, page, page_size: pageSize, total, total_pages: Math.ceil(total / pageSize) };
  }

  async get(id: number): Promise<Row> {
    const run = await this.run(undefined, id);
    if (!run) fail(404, 'The bulk targeting run was not found.');
    return this.response(undefined, run, true);
  }

  async execute(id: number, actor: Actor): Promise<Row> {
    try {
      await this.unitOfWork.transaction(async (tx) => {
        const run = await this.run(tx, id, true);
        if (!run) fail(404, 'The bulk targeting run was not found.');
        if (run.status === 'executed') return;
        if (run.status !== 'previewed') fail(409, 'Only a previewed bulk targeting run can be executed.');
        const snapshots = await this.repository.lockSelectedCandidates(id, tx);
        if (!snapshots.length) fail(409, 'The preview has no selected candidates to execute.');
        const rules = jsonValue(run.rules_json);
        const inserted = await this.repository.insertCampaign(rules.campaign_name, rules.description, rules.channel, run.segment_code, booleanValue(rules.experiment_enabled), numberValue(rules.control_group_ratio), rules.experiment_seed ?? seed(), numberValue(rules.fixed_cost), numberValue(rules.cost_per_contact), numberValue(rules.revenue_per_conversion), numberValue(rules.retention_window_days, 30), actor.id, tx);
        const campaignId = insertedId(inserted);
        await this.repository.markRunExecuted(campaignId, 'executed', new Date(), id, tx);
        await this.events.append(tx, campaignId, actor.id, 'created', { to_status: 'draft',
          note: 'Created by segment bulk targeting.',
          metadata_json: { bulk_targeting_run_id: id, segment: run.segment_code,
            eligible_count: run.eligible_count, preview_count: run.preview_count,
            scoring_batch_id: run.scoring_batch_id } });
        const campaign = await this.campaigns.campaign(tx, campaignId);
        const assignee = rules.assigned_to_user_id ? await this.repository.findAssignee(rules.assigned_to_user_id, tx) : null;
        let created = 0;
        for (const snapshot of snapshots) {
          const insight = await this.repository.findInsight(snapshot.customer_insight_id, tx);
          if (!insight) { await this.skipSnapshot(tx, snapshot.id, null); continue; }
          const customer = await this.repository.lockCustomer(snapshot.customer_id, tx);
          if (!customer) { await this.skipSnapshot(tx, snapshot.id, null); continue; }
          const cutoff = Date.now() - numberValue(rules.recent_contact_days, 30) * 86400000;
          if (booleanValue(customer.marketing_opt_out)) { await this.skipSnapshot(tx, snapshot.id, 'opted_out'); continue; }
          if (customer.last_contacted_at && new Date(customer.last_contacted_at).getTime() >= cutoff) {
            await this.skipSnapshot(tx, snapshot.id, 'recent_contact'); continue;
          }
          try {
            const targetId = await this.campaigns.createTargetInTx(tx, campaign!, insight, assignee, actor, id);
            await this.repository.markCandidateCreated('created', targetId, snapshot.id, tx);
            created++;
          } catch (error) {
            const status = (error as Row)?.getStatus?.();
            if (status !== 409) throw error;
            const detail = JSON.stringify((error as Row)?.getResponse?.() ?? '').toLowerCase();
            const reason = detail.includes('opted out') ? 'opted_out' : detail.includes('cooldown') ? 'recent_contact' : 'active_campaign';
            await this.skipSnapshot(tx, snapshot.id, reason);
          }
        }
        await this.repository.updateCreatedCount(created, id, tx);
      });
      return this.get(id);
    } catch (error) {
      if (isDuplicate(error)) fail(409, 'A campaign with the same name already exists.');
      throw error;
    }
  }

  private async skipSnapshot(tx: SqlClient, id: number, reason: string | null): Promise<void> {
    await this.repository.skipCandidate('skipped', reason, id, tx);
  }

  async cancel(id: number, actor: Actor): Promise<Row> {
    await this.unitOfWork.transaction(async (tx) => {
      const run = await this.run(tx, id, true);
      if (!run) fail(404, 'The bulk targeting run was not found.');
      if (run.status === 'cancelled') return;
      const now = new Date();
      if (run.status === 'previewed') {
        await this.repository.cancelPendingCandidates(id, tx);
        await this.repository.cancelPreview('cancelled', now, id, tx);
        return;
      }
      const targets = await this.repository.lockUncontactedTargets(id, tx);
      for (const target of targets) {
        await this.repository.cancelTarget('cancelled', now, target.id, tx);
        await this.events.append(tx, target.campaign_id, actor.id, 'status_changed', { target_id: target.id,
          from_status: target.status, to_status: 'cancelled', note: 'Cancelled by bulk targeting run.' });
        await this.repository.cancelCandidate(id, target.id, tx);
      }
      await this.repository.cancelExecutedRun(now, targets.length, id, tx);
    });
    return this.get(id);
  }

  async rerun(id: number, payload: Row, actor: Actor): Promise<Row> {
    const newId = await this.unitOfWork.transaction(async (tx) => {
      const run = await this.run(tx, id, true);
      if (!run) fail(404, 'The bulk targeting run was not found.');
      if (run.status !== 'cancelled') fail(409, 'Only a cancelled bulk targeting run can be rerun.');
      const rules = jsonValue(run.rules_json);
      const name = text(payload?.campaign_name) ?? `${rules.campaign_name} 재실행`;
      if (name.length > 150) fail(422, 'campaign_name is too long.');
      const max = payload?.max_targets === undefined || payload.max_targets === null ? rules.max_targets : positiveId(payload.max_targets);
      const previewPayload = { ...rules, segment: run.segment_code, campaign_name: name, max_targets: max,
        scoring_batch_id: run.scoring_batch_id, source_as_of_date: dateOnly(run.source_as_of_date) };
      return this.previewInTx(tx, previewPayload, actor, id, String(rules.experiment_seed));
    });
    return this.get(newId);
  }
}

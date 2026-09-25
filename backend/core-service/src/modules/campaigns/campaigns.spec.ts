import { CampaignsRepository } from './repositories/campaigns.repository';
import { CampaignEventsRepository } from './repositories/campaign-events.repository';
import { HttpException } from '@nestjs/common';
import { describe, expect, it } from 'vitest';
import type { DatabaseService } from '../../infrastructure/database/database.service';
import { CampaignsService } from './services/campaigns.service';
import type { Row, SqlClient } from './campaigns.shared';

const actor = { id: 7, role: 'marketing' };
const insight = { id: 40, customer_id: 101 };
const campaign = {
  id: 20, name: 'urgent', status: 'draft', segment_code: 'small_balance_decline',
  experiment_enabled: 0, control_group_ratio: 0,
};

function fakeSession(options: { optOut?: boolean; existing?: Row } = {}) {
  const statements: Array<{ sql: string; params: readonly unknown[] }> = [];
  const session = {
    one: async (sql: string) => {
      if (sql.includes('FROM customers WHERE customer_id')) return {
        customer_id: 101, marketing_opt_out: options.optOut ? 1 : 0, last_contacted_at: null,
      };
      return null;
    },
    query: async () => options.existing ? [options.existing] : [],
    execute: async (sql: string, params: readonly unknown[] = []) => {
      statements.push({ sql, params });
      return { insertId: 99 };
    },
  } as unknown as SqlClient;
  return { session, statements };
}

describe('campaign contact eligibility', () => {
  const service = new CampaignsService(new CampaignEventsRepository({} as DatabaseService), {} as DatabaseService, new CampaignsRepository({} as DatabaseService));

  it('preempts an uncontacted lower-priority target and records the replacement before creating the new target', async () => {
    const { session, statements } = fakeSession({ existing: {
      id: 12, campaign_id: 3, status: 'assigned', segment_code: 'medium_reactivation',
    } });
    const id = await service.createTargetInTx(session, campaign, insight, null, actor);
    expect(id).toBe(99);
    expect(statements[0]?.sql).toContain('UPDATE campaign_targets SET status');
    expect(statements[0]?.params[0]).toBe('cancelled');
    expect(statements[1]?.sql).toContain('INSERT INTO campaign_events');
    expect(statements[2]?.sql).toContain('INSERT INTO campaign_targets');
  });

  it('rejects equal-priority work without changing either target', async () => {
    const { session, statements } = fakeSession({ existing: {
      id: 12, campaign_id: 3, status: 'pending', segment_code: 'small_balance_decline',
    } });
    await expect(service.createTargetInTx(session, campaign, insight, null, actor))
      .rejects.toMatchObject({ status: 409 });
    expect(statements).toHaveLength(0);
  });

  it('blocks a customer who opted out before any campaign change', async () => {
    const { session, statements } = fakeSession({ optOut: true });
    await expect(service.createTargetInTx(session, campaign, insight, null, actor))
      .rejects.toBeInstanceOf(HttpException);
    expect(statements).toHaveLength(0);
  });
});

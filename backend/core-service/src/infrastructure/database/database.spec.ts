import { afterEach, describe, expect, it, vi } from 'vitest';
import { DatabaseService } from './database.service';
import { CampaignEventsRepository } from '../../modules/campaigns/repositories/campaign-events.repository';
import { CampaignsRepository } from '../../modules/campaigns/repositories/campaigns.repository';

const fake = vi.hoisted(() => {
  const connection = { beginTransaction: vi.fn(), commit: vi.fn(), rollback: vi.fn(), release: vi.fn(),
    query: vi.fn(), execute: vi.fn().mockResolvedValue([{ insertId: 12 }]) };
  return { connection, pool: { getConnection: vi.fn().mockResolvedValue(connection), end: vi.fn() } };
});
vi.mock('mysql2/promise', () => ({ createPool: () => fake.pool }));
afterEach(() => { vi.unstubAllEnvs(); vi.clearAllMocks(); });

describe('repository transaction scope', () => {
  it.each([false, true])('uses one connection and rolls back on failure=%s', async failure => {
    vi.stubEnv('DATABASE_URL', 'mysql://test:test@localhost/test');
    const db = new DatabaseService();
    const campaigns = new CampaignsRepository(db);
    const events = new CampaignEventsRepository(db);
    const work = db.transaction(async tx => {
      await campaigns.updateTargetStatus('cancelled', new Date(), 12, tx);
      await events.append(tx, 4, 7, 'status_changed', { target_id: 12 });
      if (failure) throw new Error('audit failed');
      return 12;
    });
    if (failure) await expect(work).rejects.toThrow('audit failed');
    else await expect(work).resolves.toBe(12);
    expect(fake.pool.getConnection).toHaveBeenCalledTimes(1);
    expect(fake.connection.execute).toHaveBeenCalledTimes(2);
    expect(fake.connection.commit).toHaveBeenCalledTimes(failure ? 0 : 1);
    expect(fake.connection.rollback).toHaveBeenCalledTimes(failure ? 1 : 0);
    expect(fake.connection.release).toHaveBeenCalledTimes(1);
  });
});

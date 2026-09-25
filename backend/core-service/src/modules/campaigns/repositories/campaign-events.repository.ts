import { Injectable } from '@nestjs/common';
import { DatabaseService, type SqlSession } from '../../../infrastructure/database/database.service';
import type { Row } from '../campaigns.shared';

@Injectable()
export class CampaignEventsRepository {
  constructor(private readonly db: DatabaseService) {}

  async append(session: SqlSession | undefined, campaignId: number, actorId: number | null,
  eventType: string, options: Row = {}): Promise<void> {
  await (session ?? this.db).execute(
    `INSERT INTO campaign_events (campaign_id, campaign_target_id, event_type, from_status, to_status,
      actor_user_id, note, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
    [campaignId, options.target_id ?? null, eventType, options.from_status ?? null,
      options.to_status ?? null, actorId, options.note ?? null,
      options.metadata_json === undefined ? null : JSON.stringify(options.metadata_json)],
  );
}
}

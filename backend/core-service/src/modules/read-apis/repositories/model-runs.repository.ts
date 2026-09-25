import { Injectable } from '@nestjs/common';
import { DatabaseService, type SqlSession } from '../../../infrastructure/database/database.service';
import type { Row } from '../read-apis.util';

@Injectable()
export class ModelRunsRepository {
  constructor(private readonly db: DatabaseService) {}

  latestBatch(session: SqlSession = this.db) {
    return session.one<Row>(`SELECT sb.*, dp.policy_sha256
      FROM scoring_batches sb JOIN decision_policies dp ON dp.id = sb.decision_policy_id
      WHERE sb.status = 'succeeded'
      ORDER BY sb.as_of_date DESC, sb.completed_at DESC, sb.id DESC LIMIT 1`, []);
  }

  runsForBatch(batchId: unknown, session: SqlSession = this.db) {
    return session.query<Row>('SELECT * FROM model_runs WHERE scoring_batch_id = ? ORDER BY task ASC, id ASC', [batchId]);
  }

  successfulLegacyRuns(session: SqlSession = this.db) {
    return session.query<Row>(`SELECT * FROM model_runs
      WHERE status = 'succeeded' AND task IN ('classification', 'regression', 'clustering')
      ORDER BY started_at DESC, id DESC`, []);
  }

  history(limit: unknown, session: SqlSession = this.db) {
    return session.query<Row>(`SELECT * FROM scoring_batches
      ORDER BY started_at DESC, id DESC LIMIT ?`, [limit]);
  }
}

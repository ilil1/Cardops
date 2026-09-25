import { HttpStatus, Injectable } from '@nestjs/common';
import { ModelRunsRepository } from '../repositories/model-runs.repository';
import {
  Row, dateOnly, detail, isoDateTime, modelRunResponse, nullableNumeric, numeric,
} from '../read-apis.util';

@Injectable()
export class ModelRunsService {
  constructor(private readonly repository: ModelRunsRepository) {}

  async latest(): Promise<Row> {
    const batch = await this.repository.latestBatch();
    if (batch) {
      const rows = await this.repository.runsForBatch(batch.id);
      if (!rows.length) detail(HttpStatus.NOT_FOUND, 'No successful model batch was found.');
      return {
        scoring_batch_id: numeric(batch.id), attempt_number: numeric(batch.attempt_number),
        as_of_date: dateOnly(batch.as_of_date), decision_policy_id: numeric(batch.decision_policy_id),
        decision_policy_sha256: batch.policy_sha256, status: 'succeeded',
        started_at: isoDateTime(batch.started_at), completed_at: isoDateTime(batch.completed_at),
        processed_rows: nullableNumeric(batch.processed_rows), dataset_sha256: batch.dataset_sha256,
        runs: rows.map(modelRunResponse),
      };
    }
    const legacy = await this.repository.successfulLegacyRuns();
    const latestByTask = new Map<string, Row>();
    for (const row of legacy) if (!latestByTask.has(row.task)) latestByTask.set(row.task, row);
    const runs = ['classification', 'regression', 'clustering']
      .map(task => latestByTask.get(task)).filter((run): run is Row => run !== undefined);
    if (!runs.length) detail(HttpStatus.NOT_FOUND, 'No successful model batch was found.');
    const startedAt = runs.reduce((earliest, run) =>
      new Date(run.started_at).getTime() < new Date(earliest).getTime() ? run.started_at : earliest, runs[0]!.started_at);
    const completedRuns = runs.filter(run => run.completed_at != null);
    const completedAt = completedRuns.length ? completedRuns.reduce((latestTime, run) =>
      new Date(run.completed_at).getTime() > new Date(latestTime).getTime() ? run.completed_at : latestTime,
      completedRuns[0]!.completed_at) : null;
    const processed = runs.map(run => nullableNumeric(run.processed_rows)).filter((value): value is number => value !== null);
    return {
      scoring_batch_id: null, attempt_number: null, as_of_date: null,
      decision_policy_id: null, decision_policy_sha256: null,
      status: runs[0]!.status, started_at: isoDateTime(startedAt), completed_at: isoDateTime(completedAt),
      processed_rows: processed.length ? Math.max(...processed) : null,
      dataset_sha256: runs.find(run => run.dataset_sha256)?.dataset_sha256 ?? null,
      runs: runs.map(modelRunResponse),
    };
  }

  async history(limit: number): Promise<Row> {
    const rows = await this.repository.history(limit);
    return { items: rows.map(row => ({
      id: numeric(row.id), attempt_number: numeric(row.attempt_number),
      as_of_date: dateOnly(row.as_of_date), status: row.status,
      processed_rows: nullableNumeric(row.processed_rows), error_message: row.error_message,
      started_at: isoDateTime(row.started_at), completed_at: isoDateTime(row.completed_at),
    })) };
  }
}

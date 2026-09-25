import { Injectable } from '@nestjs/common';
import { AnalyticsRepository, NUMERIC_FIELDS } from '../repositories/analytics.repository';
export { CATEGORICAL_FIELDS, NUMERIC_FIELDS } from '../repositories/analytics.repository';
import { InsightFilters, Row, numeric, reasonCodeList } from '../read-apis.util';

function percentile(sorted: number[], fraction: number): number {
  const position = (sorted.length - 1) * fraction;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  return sorted[lower]! + (sorted[upper]! - sorted[lower]!) * (position - lower);
}

@Injectable()
export class AnalyticsService {
  constructor(private readonly repository: AnalyticsRepository) {}

  async categorical(field: string, filters: InsightFilters): Promise<Row> {
    const rows = await this.repository.categorical(field, filters);
    return { field, items: rows.map(row => ({
      group: String(row.category_value), churn_rate: numeric(row.churn_rate), count: numeric(row.count),
    })) };
  }

  async numericDistribution(field: string, filters: InsightFilters): Promise<Row> {
    const rows = await this.repository.numericDistribution(field, filters);
    const buckets: Record<string, number[]> = {};
    for (const row of rows) {
      if (row.value == null) continue;
      (buckets[String(row.risk_level)] ??= []).push(numeric(row.value));
    }
    const byTarget: Record<string, Row> = {};
    for (const [risk, values] of Object.entries(buckets)) {
      values.sort((a, b) => a - b);
      byTarget[risk] = {
        min: values[0], q1: percentile(values, 0.25), median: percentile(values, 0.5),
        q3: percentile(values, 0.75), max: values[values.length - 1], count: values.length,
      };
    }
    return { field, by_target: byTarget };
  }

  async featureCorrelation(filters: InsightFilters): Promise<Row> {
    const rows = await this.repository.featureCorrelation(filters);
    const features = NUMERIC_FIELDS;
    if (!rows.length) return { items: [] };
    const churn = rows.map(row => numeric(row.churn_probability));
    const meanY = churn.reduce((sum, value) => sum + value, 0) / churn.length;
    const varianceY = churn.reduce((sum, value) => sum + (value - meanY) ** 2, 0);
    if (varianceY === 0) return { items: [] };
    const items: Row[] = [];
    for (const feature of features) {
      const values = rows.map(row => numeric(row[feature]));
      const meanX = values.reduce((sum, value) => sum + value, 0) / values.length;
      const varianceX = values.reduce((sum, value) => sum + (value - meanX) ** 2, 0);
      if (varianceX === 0) continue;
      const covariance = values.reduce((sum, value, index) => sum + (value - meanX) * (churn[index]! - meanY), 0);
      const correlation = covariance / Math.sqrt(varianceX * varianceY);
      if (Number.isFinite(correlation)) items.push({ feature, correlation });
    }
    items.sort((a, b) => Math.abs(b.correlation) - Math.abs(a.correlation));
    return { items };
  }

  async clusterProfile(filters: InsightFilters): Promise<Row> {
    const rows = await this.repository.clusterProfile(filters);
    return { items: rows.map(row => ({
      cluster_name: String(row.cluster_name), count: numeric(row.count),
      avg_churn_probability: numeric(row.avg_churn_probability),
      avg_activity_gap: numeric(row.avg_activity_gap),
      avg_total_trans_amt: numeric(row.avg_total_trans_amt),
    })) };
  }

  async riskClusterCrosstab(filters: InsightFilters): Promise<Row> {
    const rows = await this.repository.riskClusterCrosstab(filters);
    const riskLevels = ['high', 'medium', 'low'].filter(risk => rows.some(row => row.risk_level === risk));
    const clusters = [...new Set(rows.map(row => String(row.cluster_name)))].sort();
    const counts = new Map<string, number>(rows.map(row => [`${row.risk_level}\u0000${row.cluster_name}`, numeric(row.count)] as const));
    const cells = riskLevels.flatMap(risk => clusters.map(cluster => ({
      risk_level: risk, cluster_name: cluster, count: counts.get(`${risk}\u0000${cluster}`) ?? 0,
    })));
    return { risk_levels: riskLevels, clusters, cells };
  }

  async reasonCodeCooccurrence(filters: InsightFilters): Promise<Row> {
    const rows = await this.repository.reasonCodeCooccurrence(filters);
    const codeLists = rows.map(row => reasonCodeList(row.reason_codes).filter(code => code !== 'transaction_decline'));
    const singleCounts: Record<string, number> = {};
    for (const codes of codeLists) {
      for (const code of codes) singleCounts[code] = (singleCounts[code] ?? 0) + 1;
    }
    const codes = Object.keys(singleCounts).sort((a, b) => singleCounts[b]! - singleCounts[a]!).slice(0, 6);
    const topCodes = new Set(codes);
    const pairCounts = new Map<string, number>();
    for (const codeList of codeLists) {
      const present = [...new Set(codeList.filter(code => topCodes.has(code)))].sort();
      for (let i = 0; i < present.length; i++) {
        for (let j = i + 1; j < present.length; j++) {
          const key = `${present[i]}\u0000${present[j]}`;
          pairCounts.set(key, (pairCounts.get(key) ?? 0) + 1);
        }
      }
    }
    const pairs = [...pairCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10).map(([pair, count]) => {
      const [code_a, code_b] = pair.split('\u0000');
      return { code_a, code_b, count };
    });
    return { codes, single_counts: singleCounts, pairs };
  }
}

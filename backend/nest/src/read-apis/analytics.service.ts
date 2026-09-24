import { Injectable } from '@nestjs/common';
import { DatabaseService } from '../database/database.service';
import { InsightsService } from './insights.service';
import { InsightFilters, Row, numeric, reasonCodeList } from './read-apis.util';

const categoricalColumns: Record<string, string> = {
  Gender: 'c.gender', Card_Category: 'c.card_category',
  Income_Category: 'c.income_category', Education_Level: 'c.education_level',
  Marital_Status: 'c.marital_status',
};
const numericColumns: Record<string, string> = {
  Total_Trans_Ct: 'c.total_trans_ct', Total_Trans_Amt: 'c.total_trans_amt',
  Avg_Utilization_Ratio: 'c.avg_utilization_ratio',
  Months_Inactive_12_mon: 'c.months_inactive_12_mon',
  Contacts_Count_12_mon: 'c.contacts_count_12_mon',
  Total_Relationship_Count: 'c.total_relationship_count',
};

export const CATEGORICAL_FIELDS = Object.keys(categoricalColumns);
export const NUMERIC_FIELDS = Object.keys(numericColumns);

function percentile(sorted: number[], fraction: number): number {
  const position = (sorted.length - 1) * fraction;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  return sorted[lower]! + (sorted[upper]! - sorted[lower]!) * (position - lower);
}

@Injectable()
export class AnalyticsService {
  constructor(private readonly db: DatabaseService, private readonly insights: InsightsService) {}

  private sql(filters: InsightFilters, fields: string, suffix = ''): { sql: string; params: unknown[] } {
    const parts = this.insights.baseQuery(filters);
    return { sql: `${parts.sql.replace('%FIELDS%', fields)} ${suffix}`, params: parts.params };
  }

  async categorical(field: string, filters: InsightFilters): Promise<Row> {
    const column = categoricalColumns[field];
    const query = this.sql(filters,
      `${column} AS category_value, AVG(ci.churn_probability) AS churn_rate, COUNT(*) AS count`,
      `GROUP BY ${column} ORDER BY churn_rate DESC`);
    const rows = await this.db.query<Row>(query.sql, query.params);
    return { field, items: rows.map(row => ({
      group: String(row.category_value), churn_rate: numeric(row.churn_rate), count: numeric(row.count),
    })) };
  }

  async numericDistribution(field: string, filters: InsightFilters): Promise<Row> {
    const query = this.sql(filters, `ci.risk_level, ${numericColumns[field]} AS value`);
    const rows = await this.db.query<Row>(query.sql, query.params);
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
    const features = Object.entries(numericColumns);
    const query = this.sql(filters,
      `ci.churn_probability, ${features.map(([key, column]) => `${column} AS ${key}`).join(', ')}`);
    const rows = await this.db.query<Row>(query.sql, query.params);
    if (!rows.length) return { items: [] };
    const churn = rows.map(row => numeric(row.churn_probability));
    const meanY = churn.reduce((sum, value) => sum + value, 0) / churn.length;
    const varianceY = churn.reduce((sum, value) => sum + (value - meanY) ** 2, 0);
    if (varianceY === 0) return { items: [] };
    const items: Row[] = [];
    for (const [feature] of features) {
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
    const query = this.sql(filters,
      `ci.cluster_name, COUNT(*) AS count,
       AVG(ci.churn_probability) AS avg_churn_probability,
       AVG(ci.activity_gap) AS avg_activity_gap,
       AVG(c.total_trans_amt) AS avg_total_trans_amt`,
      'GROUP BY ci.cluster_name ORDER BY count DESC');
    const rows = await this.db.query<Row>(query.sql, query.params);
    return { items: rows.map(row => ({
      cluster_name: String(row.cluster_name), count: numeric(row.count),
      avg_churn_probability: numeric(row.avg_churn_probability),
      avg_activity_gap: numeric(row.avg_activity_gap),
      avg_total_trans_amt: numeric(row.avg_total_trans_amt),
    })) };
  }

  async riskClusterCrosstab(filters: InsightFilters): Promise<Row> {
    const query = this.sql(filters,
      'ci.risk_level, ci.cluster_name, COUNT(*) AS count',
      'GROUP BY ci.risk_level, ci.cluster_name');
    const rows = await this.db.query<Row>(query.sql, query.params);
    const riskLevels = ['high', 'medium', 'low'].filter(risk => rows.some(row => row.risk_level === risk));
    const clusters = [...new Set(rows.map(row => String(row.cluster_name)))].sort();
    const counts = new Map<string, number>(rows.map(row => [`${row.risk_level}\u0000${row.cluster_name}`, numeric(row.count)] as const));
    const cells = riskLevels.flatMap(risk => clusters.map(cluster => ({
      risk_level: risk, cluster_name: cluster, count: counts.get(`${risk}\u0000${cluster}`) ?? 0,
    })));
    return { risk_levels: riskLevels, clusters, cells };
  }

  async reasonCodeCooccurrence(filters: InsightFilters): Promise<Row> {
    const query = this.sql(filters, 'ci.reason_codes');
    const rows = await this.db.query<Row>(query.sql, query.params);
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

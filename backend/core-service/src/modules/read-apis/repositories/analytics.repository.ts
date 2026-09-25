import { Injectable } from '@nestjs/common';
import { DatabaseService } from '../../../infrastructure/database/database.service';
import { InsightsRepository } from './insights.repository';
import type { InsightFilters, Row } from '../read-apis.util';
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


@Injectable()
export class AnalyticsRepository {
  constructor(private readonly db: DatabaseService, private readonly insights: InsightsRepository) {}
  private sql(filters: InsightFilters, fields: string, suffix = ''): { sql: string; params: unknown[] } {
    const parts = this.insights.baseQuery(filters);
    return { sql: `${parts.sql.replace('%FIELDS%', fields)} ${suffix}`, params: parts.params };
  }

  async categorical(field: string, filters: InsightFilters): Promise<Row[]> {
    const column = categoricalColumns[field];
    const query = this.sql(filters,
      `${column} AS category_value, AVG(ci.churn_probability) AS churn_rate, COUNT(*) AS count`,
      `GROUP BY ${column} ORDER BY churn_rate DESC`);
    const rows = await this.db.query<Row>(query.sql, query.params);
    return rows;
  }

  async numericDistribution(field: string, filters: InsightFilters): Promise<Row[]> {
    const query = this.sql(filters, `ci.risk_level, ${numericColumns[field]} AS value`);
    const rows = await this.db.query<Row>(query.sql, query.params);
    return rows;
  }

  async featureCorrelation(filters: InsightFilters): Promise<Row[]> {
    const features = Object.entries(numericColumns);
    const query = this.sql(filters,
      `ci.churn_probability, ${features.map(([key, column]) => `${column} AS ${key}`).join(', ')}`);
    const rows = await this.db.query<Row>(query.sql, query.params);
    return rows;
  }

  async clusterProfile(filters: InsightFilters): Promise<Row[]> {
    const query = this.sql(filters,
      `ci.cluster_name, COUNT(*) AS count,
       AVG(ci.churn_probability) AS avg_churn_probability,
       AVG(ci.activity_gap) AS avg_activity_gap,
       AVG(c.total_trans_amt) AS avg_total_trans_amt`,
      'GROUP BY ci.cluster_name ORDER BY count DESC');
    const rows = await this.db.query<Row>(query.sql, query.params);
    return rows;
  }

  async riskClusterCrosstab(filters: InsightFilters): Promise<Row[]> {
    const query = this.sql(filters,
      'ci.risk_level, ci.cluster_name, COUNT(*) AS count',
      'GROUP BY ci.risk_level, ci.cluster_name');
    const rows = await this.db.query<Row>(query.sql, query.params);
    return rows;
  }

  async reasonCodeCooccurrence(filters: InsightFilters): Promise<Row[]> {
    const query = this.sql(filters, 'ci.reason_codes');
    const rows = await this.db.query<Row>(query.sql, query.params);
    return rows;
  }

}

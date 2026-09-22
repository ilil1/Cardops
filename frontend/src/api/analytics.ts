// EDA 원천 데이터셋 기반 분석 통계(차트용) API 클라이언트입니다.

import { request } from "./client";

export type CategoricalField =
  | "Gender"
  | "Card_Category"
  | "Income_Category"
  | "Education_Level"
  | "Marital_Status";

export type NumericDistributionField =
  | "Total_Trans_Ct"
  | "Total_Trans_Amt"
  | "Avg_Utilization_Ratio"
  | "Months_Inactive_12_mon"
  | "Contacts_Count_12_mon"
  | "Total_Relationship_Count";

export type CategoricalChurnRateItem = {
  group: string;
  churn_rate: number;
  count: number;
};

export type CategoricalChurnRateResponse = {
  field: string;
  items: CategoricalChurnRateItem[];
};

export type NumericDistributionBucket = {
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
  count: number;
};

export type NumericDistributionResponse = {
  field: string;
  by_target: Record<string, NumericDistributionBucket>;
};

export type FeatureCorrelationItem = {
  feature: string;
  correlation: number;
};

export type FeatureCorrelationResponse = {
  items: FeatureCorrelationItem[];
};

// 대시보드 상단 필터(위험도·군집·고객 ID)와 동일한 조건을 분석 엔드포인트에도 전달합니다.
export type AnalyticsFilters = {
  riskLevel?: "low" | "medium" | "high" | "";
  clusterName?: string;
  customerId?: number;
};

function buildFilterParams(filters?: AnalyticsFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters?.riskLevel) {
    params.set("risk_level", filters.riskLevel);
  }
  if (filters?.clusterName) {
    params.set("cluster_name", filters.clusterName);
  }
  if (filters?.customerId !== undefined) {
    params.set("customer_id", String(filters.customerId));
  }
  return params;
}

export function getCategoricalChurnRate(
  field: CategoricalField,
  filters?: AnalyticsFilters,
): Promise<CategoricalChurnRateResponse> {
  const params = buildFilterParams(filters);
  params.set("field", field);
  return request<CategoricalChurnRateResponse>(
    `/api/v1/analytics/categorical-churn-rate?${params.toString()}`,
  );
}

export function getNumericDistribution(
  field: NumericDistributionField,
  filters?: AnalyticsFilters,
): Promise<NumericDistributionResponse> {
  const params = buildFilterParams(filters);
  params.set("field", field);
  return request<NumericDistributionResponse>(
    `/api/v1/analytics/numeric-distribution?${params.toString()}`,
  );
}

export function getFeatureCorrelation(
  filters?: AnalyticsFilters,
): Promise<FeatureCorrelationResponse> {
  const params = buildFilterParams(filters);
  const query = params.toString();
  return request<FeatureCorrelationResponse>(
    `/api/v1/analytics/feature-correlation${query ? `?${query}` : ""}`,
  );
}

export type ClusterProfileItem = {
  cluster_name: string;
  count: number;
  avg_churn_probability: number;
  avg_activity_gap: number;
  avg_total_trans_amt: number;
};

export type ClusterProfileResponse = {
  items: ClusterProfileItem[];
};

export function getClusterProfile(
  filters?: AnalyticsFilters,
): Promise<ClusterProfileResponse> {
  const params = buildFilterParams(filters);
  const query = params.toString();
  return request<ClusterProfileResponse>(
    `/api/v1/analytics/cluster-profile${query ? `?${query}` : ""}`,
  );
}

export type RiskClusterCell = {
  risk_level: string;
  cluster_name: string;
  count: number;
};

export type RiskClusterCrosstabResponse = {
  risk_levels: string[];
  clusters: string[];
  cells: RiskClusterCell[];
};

export function getRiskClusterCrosstab(
  filters?: AnalyticsFilters,
): Promise<RiskClusterCrosstabResponse> {
  const params = buildFilterParams(filters);
  const query = params.toString();
  return request<RiskClusterCrosstabResponse>(
    `/api/v1/analytics/risk-cluster-crosstab${query ? `?${query}` : ""}`,
  );
}

export type ReasonCodePair = {
  code_a: string;
  code_b: string;
  count: number;
};

export type ReasonCodeCooccurrenceResponse = {
  codes: string[];
  single_counts: Record<string, number>;
  pairs: ReasonCodePair[];
};

export function getReasonCodeCooccurrence(
  filters?: AnalyticsFilters,
): Promise<ReasonCodeCooccurrenceResponse> {
  const params = buildFilterParams(filters);
  const query = params.toString();
  return request<ReasonCodeCooccurrenceResponse>(
    `/api/v1/analytics/reason-code-cooccurrence${query ? `?${query}` : ""}`,
  );
}
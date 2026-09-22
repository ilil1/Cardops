import { Fragment, useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  LabelList,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { AuthUser } from "../../api/auth";
import {
  createCampaignTarget,
  getCampaignPerformance,
  listCampaignTargets,
  updateCampaignTarget,
  type CampaignStatus,
  type CampaignTarget,
  type CampaignPerformance,
} from "../../api/campaigns";
import {
  getCustomerInsight,
  getCustomerInsightHistory,
  getReasonCodeDistribution,
  listCustomerInsights,
  type CustomerInsight,
  type CustomerInsightDetail,
  type CustomerInsightHistory,
  type CustomerInsightList,
  type InsightQuery,
  type ReasonCodeDistribution,
} from "../../api/insights";
import { getLatestBatch, type LatestBatch } from "../../api/modelRuns";
import {
  getCategoricalChurnRate,
  getClusterProfile,
  getFeatureCorrelation,
  getNumericDistribution,
  getReasonCodeCooccurrence,
  getRiskClusterCrosstab,
  type AnalyticsFilters,
  type CategoricalChurnRateItem,
  type CategoricalField,
  type ClusterProfileItem,
  type FeatureCorrelationItem,
  type NumericDistributionField,
  type ReasonCodeCooccurrenceResponse,
  type RiskClusterCrosstabResponse,
} from "../../api/analytics";

const CATEGORICAL_FIELD_OPTIONS: { value: CategoricalField; label: string }[] = [
  { value: "Gender", label: "성별" },
  { value: "Card_Category", label: "카드 등급" },
  { value: "Income_Category", label: "소득 구간" },
  { value: "Education_Level", label: "학력" },
  { value: "Marital_Status", label: "결혼 상태" },
];

const CATEGORICAL_GROUP_LABELS: Record<CategoricalField, Record<string, string>> = {
  Gender: {
    F: "여성",
    M: "남성",
  },
  Card_Category: {
    Blue: "블루",
    Silver: "실버",
    Gold: "골드",
    Platinum: "플래티넘",
  },
  Income_Category: {
    "Less than $40K": "5,600만원 미만",
    "$40K - $60K": "5,600만원~8,400만원",
    "$60K - $80K": "8,400만원~1억 1,200만원",
    "$80K - $120K": "1억 1,200만원~1억 6,800만원",
    "$120K +": "1억 6,800만원 이상",
    Unknown: "확인 불가",
  },
  Education_Level: {
    Uneducated: "무학",
    "High School": "고등학교 졸업",
    College: "대학 재학",
    Graduate: "대학교 졸업",
    "Post-Graduate": "대학원 졸업",
    Doctorate: "박사",
    Unknown: "확인 불가",
  },
  Marital_Status: {
    Married: "기혼",
    Single: "미혼",
    Divorced: "이혼",
    Unknown: "확인 불가",
  },
};

function getCategoricalGroupLabel(field: CategoricalField, group: string): string {
  return CATEGORICAL_GROUP_LABELS[field]?.[group] ?? group;
}

const CATEGORICAL_GROUP_ORDER: Partial<Record<CategoricalField, string[]>> = {
  Card_Category: ["Blue", "Silver", "Gold", "Platinum"],
  Income_Category: [
    "Less than $40K",
    "$40K - $60K",
    "$60K - $80K",
    "$80K - $120K",
    "$120K +",
    "Unknown",
  ],
  Education_Level: [
    "Uneducated",
    "High School",
    "College",
    "Graduate",
    "Post-Graduate",
    "Doctorate",
    "Unknown",
  ],
};

function isOrdinalCategoricalField(field: CategoricalField): boolean {
  return field in CATEGORICAL_GROUP_ORDER;
}

function sortByGroupOrder(
  items: CategoricalChurnRateItem[],
  field: CategoricalField,
): CategoricalChurnRateItem[] {
  const order = CATEGORICAL_GROUP_ORDER[field];
  if (order === undefined) {
    return items;
  }
  return [...items].sort((a, b) => {
    const indexA = order.indexOf(a.group);
    const indexB = order.indexOf(b.group);
    return (indexA === -1 ? order.length : indexA) - (indexB === -1 ? order.length : indexB);
  });
}

const NUMERIC_FIELD_OPTIONS: { value: NumericDistributionField; label: string }[] = [
  { value: "Total_Trans_Ct", label: "거래 건수" },
  { value: "Total_Trans_Amt", label: "거래 금액" },
  { value: "Avg_Utilization_Ratio", label: "한도소진율" },
  { value: "Months_Inactive_12_mon", label: "비활성 개월수" },
  { value: "Contacts_Count_12_mon", label: "문의 횟수" },
  { value: "Total_Relationship_Count", label: "보유 상품 수" },
];

const NUMERIC_FIELD_LABELS: Record<string, string> = Object.fromEntries(
  NUMERIC_FIELD_OPTIONS.map((option) => [option.value, option.label]),
);

function getNumericFieldLabel(field: string): string {
  return NUMERIC_FIELD_LABELS[field] ?? field;
}

const CHART_BAR_COLOR = "#1d4ed8";
const CHART_LINE_COLOR = "#1d4ed8";

function formatEdaPercent(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`;
}

function formatCompactNumber(value: number): string {
  return new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 }).format(value);
}

function toNumber(value: unknown): number {
  return typeof value === "number" ? value : Number(value ?? 0);
}

function ChartCard({
  title,
  action,
  wide = false,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  wide?: boolean;
  children: React.ReactNode;
}) {
  return (
    <article className={`eda-chart-card${wide ? " eda-chart-card--wide" : ""}`}>
      <div className="table-card__header eda-chart-card__header">
        <div>
          <h3>{title}</h3>
        </div>
        {action}
      </div>
      {children}
    </article>
  );
}

function weightedAverage(items: CategoricalChurnRateItem[]): number {
  const totalCount = items.reduce((sum, item) => sum + item.count, 0);
  if (totalCount === 0) {
    return 0;
  }
  return items.reduce((sum, item) => sum + item.churn_rate * item.count, 0) / totalCount;
}

function CategoricalChurnRateChart({ filters }: { filters: AnalyticsFilters }) {
  const [field, setField] = useState<CategoricalField>("Gender");
  const [result, setResult] = useState<{
    field: CategoricalField;
    items: CategoricalChurnRateItem[];
  } | null>(null);
  const [error, setError] = useState("");
  const items = result?.field === field ? result.items : null;

  useEffect(() => {
    let isActive = true;
    getCategoricalChurnRate(field, filters)
      .then((response) => {
        if (isActive) {
          setResult({ field, items: response.items });
          setError("");
        }
      })
      .catch((requestError) => {
        if (isActive) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : "이탈률 데이터를 불러오지 못했습니다.",
          );
        }
      });
    return () => {
      isActive = false;
    };
  }, [field, filters]);

  const average = useMemo(() => (items === null ? 0 : weightedAverage(items)), [items]);
  const isOrdinal = isOrdinalCategoricalField(field);
  const orderedItems = useMemo(
    () => (items === null ? null : sortByGroupOrder(items, field)),
    [items, field],
  );

  return (
    <ChartCard
      title="범주형 변수별 평균 이탈 확률"
      action={
        <select
          aria-label="범주형 변수 선택"
          value={field}
          onChange={(event) => setField(event.target.value as CategoricalField)}
        >
          {CATEGORICAL_FIELD_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      }
    >
      {error !== "" ? (
        <p className="empty-copy">{error}</p>
      ) : orderedItems === null ? (
        <p className="empty-copy">불러오는 중입니다.</p>
      ) : isOrdinal ? (
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={orderedItems} margin={{ left: 4, right: 16, top: 20, bottom: 0 }}>
            <XAxis
              dataKey="group"
              stroke="#94a3b8"
              tick={{ fontSize: 10.5 }}
              tickFormatter={(value: string) => getCategoricalGroupLabel(field, value)}
              interval={0}
            />
            <YAxis
              stroke="#94a3b8"
              tick={{ fontSize: 11 }}
              tickFormatter={(value: number) => formatEdaPercent(value)}
              width={40}
            />
            <Tooltip
              formatter={(value: unknown, _name: unknown, entry: unknown) => {
                const payload = (entry as { payload?: CategoricalChurnRateItem } | undefined)
                  ?.payload;
                return [
                  `${formatEdaPercent(toNumber(value), 1)} (${formatCompactNumber(payload?.count ?? 0)}명)`,
                  "평균 이탈 확률",
                ];
              }}
              labelFormatter={(label: unknown) => getCategoricalGroupLabel(field, String(label))}
            />
            <ReferenceLine
              y={average}
              stroke="#64748b"
              strokeDasharray="4 4"
              label={{ value: `평균 ${formatEdaPercent(average, 1)}`, position: "right", fontSize: 11, fill: "#64748b" }}
            />
            <Line
              type="monotone"
              dataKey="churn_rate"
              stroke={CHART_LINE_COLOR}
              strokeWidth={2}
              dot={{ r: 4, fill: CHART_LINE_COLOR }}
              activeDot={{ r: 6 }}
            >
              <LabelList
                dataKey="churn_rate"
                position="top"
                formatter={(value: unknown) => formatEdaPercent(toNumber(value), 1)}
                fontSize={10.5}
                fill="#2c2c2e"
              />
            </Line>
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={orderedItems} layout="vertical" margin={{ left: 12, right: 24 }}>
            <XAxis
              type="number"
              tickFormatter={(value: number) => formatEdaPercent(value)}
              stroke="#94a3b8"
              tick={{ fontSize: 11 }}
            />
            <YAxis
              type="category"
              dataKey="group"
              width={90}
              stroke="#94a3b8"
              tick={{ fontSize: 11 }}
              tickFormatter={(value: string) => getCategoricalGroupLabel(field, value)}
            />
            <Tooltip
              formatter={(value: unknown, _name: unknown, entry: unknown) => {
                const payload = (entry as { payload?: CategoricalChurnRateItem } | undefined)
                  ?.payload;
                return [
                  `${formatEdaPercent(toNumber(value), 1)} (${formatCompactNumber(payload?.count ?? 0)}명)`,
                  "평균 이탈 확률",
                ];
              }}
              labelFormatter={(label: unknown) => getCategoricalGroupLabel(field, String(label))}
            />
            <ReferenceLine
              x={average}
              stroke="#64748b"
              strokeDasharray="4 4"
              label={{ value: `평균 ${formatEdaPercent(average, 1)}`, position: "top", fontSize: 11, fill: "#64748b" }}
            />
            <Bar dataKey="churn_rate" radius={[0, 4, 4, 0]} maxBarSize={22} fill={CHART_BAR_COLOR}>
              <LabelList
                dataKey="churn_rate"
                position="right"
                formatter={(value: unknown) => formatEdaPercent(toNumber(value), 1)}
                fontSize={11}
                fill="#2c2c2e"
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </ChartCard>
  );
}

const BOX_GROUP_LABELS: Record<string, string> = {
  low: "낮음",
  medium: "주의",
  high: "높음",
};

const BOX_GROUP_ORDER = ["low", "medium", "high"];

type NumericDistributionBuckets = Record<
  string,
  { min: number; q1: number; median: number; q3: number; max: number; count: number }
>;

function NumericDistributionChart({ filters }: { filters: AnalyticsFilters }) {
  const [field, setField] = useState<NumericDistributionField>("Total_Trans_Ct");
  const [result, setResult] = useState<{
    field: NumericDistributionField;
    byTarget: NumericDistributionBuckets;
  } | null>(null);
  const [error, setError] = useState("");
  const byTarget = result?.field === field ? result.byTarget : null;

  useEffect(() => {
    let isActive = true;
    getNumericDistribution(field, filters)
      .then((response) => {
        if (isActive) {
          setResult({ field, byTarget: response.by_target });
          setError("");
        }
      })
      .catch((requestError) => {
        if (isActive) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : "수치형 분포 데이터를 불러오지 못했습니다.",
          );
        }
      });
    return () => {
      isActive = false;
    };
  }, [field, filters]);

  const chartData = useMemo(() => {
    if (byTarget === null) {
      return [];
    }
    return Object.entries(byTarget)
      .sort(([a], [b]) => BOX_GROUP_ORDER.indexOf(a) - BOX_GROUP_ORDER.indexOf(b))
      .map(([target, bucket]) => ({
        name: BOX_GROUP_LABELS[target] ?? target,
        median: bucket.median,
        raw: bucket,
      }));
  }, [byTarget]);

  return (
    <ChartCard
      title="위험도별 중앙값 비교"
      action={
        <select
          aria-label="수치형 변수 선택"
          value={field}
          onChange={(event) => setField(event.target.value as NumericDistributionField)}
        >
          {NUMERIC_FIELD_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      }
    >
      {error !== "" ? (
        <p className="empty-copy">{error}</p>
      ) : byTarget === null ? (
        <p className="empty-copy">불러오는 중입니다.</p>
      ) : (
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={chartData} margin={{ left: 12, right: 12, top: 20 }}>
            <XAxis dataKey="name" stroke="#94a3b8" tick={{ fontSize: 11 }} />
            <YAxis stroke="#94a3b8" tick={{ fontSize: 11 }} tickFormatter={formatCompactNumber} />
            <Tooltip
              content={({ payload }) => {
                const entry = payload?.[0]?.payload as (typeof chartData)[number] | undefined;
                if (entry === undefined) {
                  return null;
                }
                return (
                  <div className="eda-boxplot-tooltip">
                    <strong>{entry.name}</strong>
                    <span>최대 {formatCompactNumber(entry.raw.max)}</span>
                    <span>Q3 {formatCompactNumber(entry.raw.q3)}</span>
                    <span>중앙값 {formatCompactNumber(entry.raw.median)}</span>
                    <span>Q1 {formatCompactNumber(entry.raw.q1)}</span>
                    <span>최소 {formatCompactNumber(entry.raw.min)}</span>
                  </div>
                );
              }}
            />
            <Bar dataKey="median" radius={[4, 4, 0, 0]} maxBarSize={64} fill={CHART_BAR_COLOR}>
              <LabelList
                dataKey="median"
                position="top"
                formatter={(value: unknown) => formatCompactNumber(toNumber(value))}
                fontSize={11}
                fill="#2c2c2e"
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </ChartCard>
  );
}

function FeatureCorrelationChart({ filters }: { filters: AnalyticsFilters }) {
  const [items, setItems] = useState<FeatureCorrelationItem[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let isActive = true;
    getFeatureCorrelation(filters)
      .then((response) => {
        if (isActive) {
          setItems(response.items);
        }
      })
      .catch((requestError) => {
        if (isActive) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : "상관관계 데이터를 불러오지 못했습니다.",
          );
        }
      });
    return () => {
      isActive = false;
    };
  }, [filters]);

  return (
    <ChartCard title="변수-예측 이탈 확률 상관관계" wide>
      {error !== "" ? (
        <p className="empty-copy">{error}</p>
      ) : items === null ? (
        <p className="empty-copy">불러오는 중입니다.</p>
      ) : (
        <ResponsiveContainer width="100%" height={280}>
          <BarChart
            data={items}
            layout="vertical"
            margin={{ left: 12, right: 24 }}
          >
            <XAxis
              type="number"
              domain={[-0.5, 0.5]}
              tickFormatter={(value: number) => value.toFixed(1)}
              stroke="#94a3b8"
              tick={{ fontSize: 11 }}
            />
            <YAxis
              type="category"
              dataKey="feature"
              width={140}
              stroke="#94a3b8"
              tick={{ fontSize: 10 }}
              tickFormatter={(value: string) => getNumericFieldLabel(value)}
            />
            <Tooltip
              formatter={(value: unknown) => [toNumber(value).toFixed(3), "상관계수"]}
              labelFormatter={(label: unknown) => getNumericFieldLabel(String(label))}
            />
            <ReferenceLine x={0} stroke="#64748b" />
            <Bar dataKey="correlation" maxBarSize={16} fill={CHART_BAR_COLOR}>
              <LabelList
                dataKey="correlation"
                position="right"
                formatter={(value: unknown) => toNumber(value).toFixed(2)}
                fontSize={10.5}
                fill="#2c2c2e"
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </ChartCard>
  );
}

const PAGE_SIZE = 8;

const riskLabels: Record<CustomerInsight["risk_level"], string> = {
  low: "낮음",
  medium: "주의",
  high: "높음",
};

const riskColors: Record<CustomerInsight["risk_level"], string> = {
  low: "#15803d",
  medium: "#f59e0b",
  high: "#dc2626",
};

const campaignStatusLabels: Record<CampaignStatus, string> = {
  pending: "대기",
  assigned: "담당 배정",
  contacted: "접촉 완료",
  completed: "처리 완료",
  cancelled: "취소",
};

const taskLabels: Record<string, string> = {
  classification: "분류모델",
  clustering: "군집모델",
  regression: "회귀모델",
};

function getTaskLabel(task: string): string {
  return taskLabels[task] ?? task;
}

function isHashLike(value: string): boolean {
  return /^[a-f0-9]{32,}$/i.test(value);
}

function isTimestampLike(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(value);
}

function isRawVersionValue(value: string): boolean {
  return isHashLike(value) || isTimestampLike(value);
}

const campaignStatusTransitions: Record<CampaignStatus, CampaignStatus[]> = {
  pending: ["pending", "assigned", "cancelled"],
  assigned: ["assigned", "contacted", "cancelled"],
  contacted: ["contacted", "completed", "cancelled"],
  completed: ["completed"],
  cancelled: ["cancelled"],
};

type RiskFilter = "" | NonNullable<InsightQuery["risk_level"]>;
type SortBy = NonNullable<InsightQuery["sort_by"]>;
type SortOrder = NonNullable<InsightQuery["sort_order"]>;

type DashboardPageProps = {
  user: AuthUser;
  showCampaignFeedback?: boolean;
};

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("ko-KR").format(value);
}

function formatDecimal(value: number): string {
  return new Intl.NumberFormat("ko-KR", {
    maximumFractionDigits: 1,
  }).format(value);
}

const USD_TO_KRW_RATE = 1400;

function formatWon(usdValue: number): string {
  return `${formatNumber(Math.round(usdValue * USD_TO_KRW_RATE))}원`;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("ko-KR", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatSignedDecimal(value: number): string {
  return `${value > 0 ? "+" : ""}${formatDecimal(value)}`;
}

function getPageNumbers(currentPage: number, totalPages: number): (number | "ellipsis")[] {
  const windowSize = 5;
  if (totalPages <= windowSize) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }

  let start = Math.max(1, currentPage - 2);
  let end = start + windowSize - 1;
  if (end > totalPages) {
    end = totalPages;
    start = end - windowSize + 1;
  }

  const result: (number | "ellipsis")[] = [];
  if (start > 1) {
    result.push(1);
    if (start > 2) result.push("ellipsis");
  }
  for (let page = start; page <= end; page += 1) {
    result.push(page);
  }
  if (end < totalPages) {
    if (end < totalPages - 1) result.push("ellipsis");
    result.push(totalPages);
  }
  return result;
}

function escapeCsv(value: unknown): string {
  const normalized = String(value ?? "").replaceAll('"', '""');
  return `"${normalized}"`;
}

function getCustomerIdFilter(value: string): number | undefined {
  const normalized = value.trim();
  if (normalized === "") {
    return undefined;
  }

  const customerId = Number(normalized);
  return Number.isInteger(customerId) && customerId > 0
    ? customerId
    : undefined;
}

function getClusterOptions(clusterCounts: Record<string, number>): [string, number][] {
  return Object.entries(clusterCounts).sort(([clusterA], [clusterB]) =>
    clusterA.localeCompare(clusterB, "ko"),
  );
}

function RiskBadge({ risk }: { risk: CustomerInsight["risk_level"] }) {
  return (
    <span className={`risk-badge risk-badge--${risk}`}>
      <span aria-hidden="true" />
      {riskLabels[risk]}
    </span>
  );
}

function SortableHeader({
  field,
  label,
  sortBy,
  sortOrder,
  onSort,
}: {
  field: SortBy;
  label: string;
  sortBy: SortBy;
  sortOrder: SortOrder;
  onSort: (field: SortBy) => void;
}) {
  const isActive = field === sortBy;
  return (
    <button
      type="button"
      className={isActive ? "insight-header-sort insight-header-sort--active" : "insight-header-sort"}
      onClick={() => onSort(field)}
      aria-label={`${label} 기준 정렬${isActive ? (sortOrder === "desc" ? " (내림차순)" : " (오름차순)") : ""}`}
    >
      {label}
      <span className="insight-header-sort__arrow" aria-hidden="true">
        {isActive ? (sortOrder === "desc" ? "▼" : "▲") : "⇅"}
      </span>
    </button>
  );
}

function DashboardSkeleton() {
  return (
    <section className="bento-grid" aria-label="고객 분석 대시보드 로딩 중">
      <div className="bento-card dashboard-skeleton dashboard-skeleton--hero" />
      <div className="bento-card dashboard-skeleton" />
      <div className="bento-card dashboard-skeleton" />
      <div className="bento-card dashboard-skeleton dashboard-skeleton--table" />
    </section>
  );
}

function RiskOverview({ data }: { data: CustomerInsightList }) {
  const riskEntries = (["high", "medium", "low"] as const).map((risk) => ({
    risk,
    count: data.stats.risk_counts[risk] ?? 0,
  }));
  const maxCount = Math.max(...riskEntries.map(({ count }) => count), 1);

  return (
    <article className="eda-chart-card">
      <div className="table-card__header eda-chart-card__header">
        <div>
          <h3>위험도별 고객 분포</h3>
        </div>
      </div>
      <div className="horiz-bar-list">
        {riskEntries.map(({ risk, count }) => (
          <div className="horiz-bar-row" key={risk}>
            <span className="horiz-bar-row__label">{riskLabels[risk]}</span>
            <div className="bar-track">
              <span
                className="bar-fill"
                style={{
                  width: `${Math.max((count / maxCount) * 100, count > 0 ? 4 : 0)}%`,
                  backgroundColor: riskColors[risk],
                }}
              />
            </div>
            <span className="horiz-bar-row__value">
              {formatNumber(count)}/{formatPercent(data.stats.total > 0 ? count / data.stats.total : 0)}
            </span>
          </div>
        ))}
      </div>
    </article>
  );
}


function InsightRow({
  insight,
  onSelect,
}: {
  insight: CustomerInsight;
  onSelect: (customerId: number) => void;
}) {
  return (
    <button
      className="insight-row"
      type="button"
      onClick={() => onSelect(insight.customer_id)}
    >
      <span className="insight-row__customer">
        <strong>{insight.customer_id}</strong>
        <small>{formatDate(insight.scored_at)}</small>
      </span>
      <span>
        <RiskBadge risk={insight.risk_level} />
      </span>
      <span className="insight-row__metric">
        <strong>{formatPercent(insight.churn_probability)}</strong>
        <small>이탈 확률</small>
      </span>
      <span className="insight-row__actual">
        {formatDecimal(insight.expected_transaction_count + insight.activity_gap)}건
        <small>실제 거래</small>
      </span>
      <span className="insight-row__expected">
        {formatDecimal(insight.expected_transaction_count)}건
        <small>예상 거래</small>
      </span>
      <span className={`insight-row__gap ${insight.activity_gap < 0 ? "insight-row__gap--negative" : ""}`}>
        {formatSignedDecimal(insight.activity_gap)}
        <small>거래 차이</small>
      </span>
      <span className="insight-row__amount">
        {formatWon(insight.total_trans_amt)}
        <small>총 거래금액</small>
      </span>
      <span className="insight-row__card">
        {insight.card_category}
        <small>카드분류</small>
      </span>
      <span className="insight-row__contacts">
        {formatNumber(insight.contacts_count_12_mon)}회
        <small>문의횟수</small>
      </span>
      <span className="insight-row__cluster">
        {insight.cluster_name}
        <small>
          신뢰도 {insight.cluster_confidence == null ? "-" : formatPercent(insight.cluster_confidence)}
        </small>
      </span>
      <span className="insight-row__action">{insight.recommended_action}</span>
      <span className="insight-row__arrow" aria-hidden="true">↗</span>
    </button>
  );
}

function BatchOverview({ batch, wide = false }: { batch: LatestBatch | null; wide?: boolean }) {
  return (
    <article className={`eda-chart-card${wide ? " eda-chart-card--wide batch-overview--wide" : ""}`}>
      <div className="table-card__header eda-chart-card__header">
        <div>
          <h3>최근 배치 상태</h3>
        </div>
        <span className="batch-status">{batch === null ? "확인 중" : "동기화 완료"}</span>
      </div>
      {batch === null ? (
        <p className="empty-copy">배치 실행 정보를 불러오는 중입니다.</p>
      ) : (
        <div className="batch-overview__body">
          <strong className="batch-time">
            {formatDate(batch.completed_at ?? batch.started_at)}
          </strong>
          <p className="batch-caption">
            {batch.processed_rows === null
              ? "처리 행 수 미상"
              : `${formatNumber(batch.processed_rows)}명 분석 완료`}
          </p>
          <div className="batch-models">
            {batch.runs.map((run) => (
              <span key={run.id}>
                {getTaskLabel(run.task)}
                {run.model_version !== null && run.model_version !== "" && !isRawVersionValue(run.model_version)
                  ? ` · ${run.model_version}`
                  : null}
              </span>
            ))}
          </div>
        </div>
      )}
    </article>
  );
}

type CampaignDraft = {
  status: CampaignStatus;
  result: string;
  result_notes: string;
  converted: boolean;
};

function CampaignFeedback({
  performance,
  isLoading,
  error,
}: {
  performance: CampaignPerformance | null;
  isLoading: boolean;
  error: string;
}) {
  const metrics = performance?.summary ?? null;
  const pendingCount = metrics === null
    ? 0
    : Math.max(metrics.target_count - metrics.contacted_count, 0);

  return (
    <article className="bento-card bento-card--campaign campaign-feedback">
      <div className="table-card__header">
        <div>
          <h2>캠페인 실행 피드백</h2>
        </div>
        <div className="campaign-feedback__header-actions">
          <span className="table-count">
            {metrics === null ? "전체 캠페인" : `${formatNumber(metrics.target_count)}명 대상`}
          </span>
          <MetricHelpButton
            dialogId="campaign-feedback-metric-help"
            title="캠페인 실행 피드백 지표 설명"
            items={CAMPAIGN_FEEDBACK_HELP_ITEMS}
            note="치료군과 대조군의 차이가 클수록 캠페인 자체의 효과가 높다고 볼 수 있지만, 충분한 대상 수와 관측 기간이 함께 확보되어야 신뢰할 수 있습니다."
          />
        </div>
      </div>
      <p className="campaign-feedback__intro">
        실행 결과를 바탕으로 타겟팅 품질과 운영 병목을 확인합니다. 개별 고객 처리는 운영팀이 담당합니다.
      </p>
      {isLoading ? (
        <p className="queue-state">캠페인 성과를 집계하는 중입니다.</p>
      ) : error !== "" ? (
        <p className="campaign-feedback__error" role="alert">{error}</p>
      ) : metrics === null || metrics.target_count === 0 ? (
        <p className="queue-state">분석할 캠페인 실행 결과가 없습니다.</p>
      ) : (
        <>
          <div className="campaign-feedback__metrics">
            <div>
              <span>접촉률</span>
              <strong>{formatPercent(metrics.contact_rate)}</strong>
              <small>{formatNumber(metrics.contacted_count)} / {formatNumber(metrics.target_count)}명 접촉</small>
            </div>
            <div>
              <span>미처리 대상</span>
              <strong>{formatNumber(pendingCount)}명</strong>
              <small>실행 병목 확인 대상</small>
            </div>
            <div>
              <span>전환율</span>
              <strong>{formatPercent(metrics.conversion_rate)}</strong>
              <small>{formatNumber(metrics.converted_count)}명 전환</small>
            </div>
            <div>
              <span>증분 전환 효과</span>
              <strong>{signedPointsFromRatio(metrics.incremental_conversion_effect)}</strong>
              <small>치료군 − 대조군</small>
            </div>
            <div>
              <span>ROI</span>
              <strong>{metrics.roi === null ? "-" : formatPercent(metrics.roi)}</strong>
              <small>증분 매출 기준</small>
            </div>
          </div>
          <div className="campaign-feedback__comparison">
            <div>
              <span>치료군 전환율</span>
              <strong>{formatPercent(metrics.treatment_conversion_rate ?? 0)}</strong>
            </div>
            <div>
              <span>대조군 전환율</span>
              <strong>{formatPercent(metrics.control_conversion_rate ?? 0)}</strong>
            </div>
            <div>
              <span>유지율</span>
              <strong>{metrics.retention_rate === null ? "관측 중" : formatPercent(metrics.retention_rate)}</strong>
            </div>
          </div>
          <p className="campaign-feedback__note">
            미처리 대상은 실행 병목, 치료군과 대조군의 차이는 타겟팅의 실제 효과를 나타냅니다.
          </p>
        </>
      )}
    </article>
  );
}

function CampaignQueue({
  targets,
  drafts,
  canManage,
  user,
  isLoading,
  onDraftChange,
  onSave,
}: {
  targets: CampaignTarget[];
  drafts: Record<number, CampaignDraft>;
  canManage: boolean;
  user: AuthUser;
  isLoading: boolean;
  onDraftChange: (targetId: number, draft: CampaignDraft) => void;
  onSave: (targetId: number) => void;
}) {
  return (
    <article className="bento-card bento-card--campaign">
      <div className="table-card__header">
        <div>
          <h2>캠페인 처리 현황</h2>
        </div>
        <span className="table-count">{formatNumber(targets.length)}건</span>
      </div>
      {isLoading ? (
        <p className="queue-state">처리 현황을 불러오는 중입니다.</p>
      ) : targets.length === 0 ? (
        <p className="queue-state">등록된 캠페인 대상이 없습니다.</p>
      ) : (
        <div className="campaign-list">
          {targets.map((target) => {
            const draft = drafts[target.id] ?? {
              status: target.status,
              result: target.result ?? "",
              result_notes: target.result_notes ?? "",
              converted: target.converted,
            };
            const canEditTarget = canManage
              && target.experiment_group === "treatment"
              && target.campaign_status === "active"
              && (user.role === "admin" || target.assigned_to_user_id === user.id);
            const availableStatuses = campaignStatusTransitions[target.status].filter(
              (value) => value !== "assigned" || target.assigned_to_user_id !== null,
            );
            return (
              <div className="campaign-row" key={target.id}>
                <div className="campaign-row__customer">
                  <strong>{target.customer_id}</strong>
                  <span>{target.campaign_name}</span>
                </div>
                <span className={`campaign-status campaign-status--${target.status}`}>
                  {campaignStatusLabels[target.status]}
                </span>
                <span className="campaign-assignee">
                  {target.assigned_to_display_name ?? "미배정"}
                </span>
                {canEditTarget ? (
                  <div className="campaign-row__controls">
                    <select
                      value={draft.status}
                      aria-label={`${target.customer_id} 처리 상태`}
                      onChange={(event) =>
                        onDraftChange(target.id, {
                          ...draft,
                          status: event.target.value as CampaignStatus,
                        })
                      }
                    >
                      {availableStatuses.map((value) => (
                        <option value={value} key={value}>
                          {campaignStatusLabels[value]}
                        </option>
                      ))}
                    </select>
                    <input
                      value={draft.result}
                      placeholder="처리 결과"
                      aria-label={`${target.customer_id} 처리 결과`}
                      onChange={(event) =>
                        onDraftChange(target.id, { ...draft, result: event.target.value })
                      }
                    />
                    <label className="campaign-conversion">
                      <input
                        type="checkbox"
                        checked={draft.converted}
                        disabled={draft.status !== "completed"}
                        onChange={(event) =>
                          onDraftChange(target.id, {
                            ...draft,
                            converted: event.target.checked,
                          })
                        }
                      />
                      전환
                    </label>
                    <button type="button" onClick={() => onSave(target.id)}>저장</button>
                  </div>
                ) : (
                  <span className="campaign-result">{target.result ?? "-"}</span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </article>
  );
}

function CustomerDetailPanel({
  detail,
  history,
  historyLoading,
  campaigns,
  canManageCampaigns,
  campaignName,
  campaignSubmitting,
  campaignMessage,
  onCampaignNameChange,
  onCreateCampaign,
  isLoading,
  error,
  onClose,
}: {
  detail: CustomerInsightDetail | null;
  history: CustomerInsightHistory | null;
  historyLoading: boolean;
  campaigns: CampaignTarget[];
  canManageCampaigns: boolean;
  campaignName: string;
  campaignSubmitting: boolean;
  campaignMessage: string;
  onCampaignNameChange: (value: string) => void;
  onCreateCampaign: () => void;
  isLoading: boolean;
  error: string;
  onClose: () => void;
}) {
  return (
    <aside className="insight-drawer" role="dialog" aria-modal="true" aria-labelledby="detail-title">
      <div className="insight-drawer__header">
        <div>
          <h2 id="detail-title">
            {detail === null ? "고객 상세 정보" : `고객 ${detail.customer_id}`}
          </h2>
        </div>
        <button className="drawer-close" type="button" aria-label="고객 상세 닫기" onClick={onClose}>
          ×
        </button>
      </div>

      {isLoading && <p className="drawer-state">상세 정보를 불러오는 중입니다.</p>}
      {!isLoading && error !== "" && <p className="drawer-state drawer-state--error">{error}</p>}
      {!isLoading && error === "" && detail !== null && (
        <div className="drawer-content">
          <div className="drawer-risk-summary">
            <RiskBadge risk={detail.risk_level} />
            <strong>{formatPercent(detail.churn_probability)}</strong>
            <span>예상 이탈 확률</span>
          </div>
          <p className="drawer-recommendation">{detail.recommended_action}</p>

          <dl className="customer-facts">
            <div><dt>고객 연령</dt><dd>{detail.customer.customer_age}세</dd></div>
            <div><dt>카드 등급</dt><dd>{detail.customer.card_category}</dd></div>
            <div><dt>소득 구간</dt><dd>{getCategoricalGroupLabel("Income_Category", detail.customer.income_category)}</dd></div>
            <div><dt>최근 거래 건수</dt><dd>{formatNumber(detail.customer.total_trans_ct)}건</dd></div>
            <div><dt>거래 금액</dt><dd>{formatWon(detail.customer.total_trans_amt)}</dd></div>
            <div><dt>비활성 개월</dt><dd>{detail.customer.months_inactive_12_mon}개월</dd></div>
            <div><dt>예상 거래 건수</dt><dd>{formatDecimal(detail.expected_transaction_count)}건</dd></div>
            <div><dt>활동성 갭</dt><dd>{formatDecimal(detail.activity_gap)}</dd></div>
            <div><dt>고객 군집</dt><dd>{detail.cluster_name}</dd></div>
            <div><dt>군집 신뢰도</dt><dd>{detail.cluster_confidence == null ? "-" : formatPercent(detail.cluster_confidence)}</dd></div>
          </dl>

          <div className="drawer-history">
            <div className="drawer-section-heading">
              <h3>분석 이력</h3>
              <span>{history?.items.length ?? 0}회</span>
            </div>
            {historyLoading ? (
              <p className="drawer-inline-state">분석 이력을 불러오는 중입니다.</p>
            ) : history === null ? (
              <p className="drawer-inline-state">분석 이력이 없습니다.</p>
            ) : (
              <div className="history-list">
                {history.items.slice(0, 6).map((item) => (
                  <div className="history-item" key={item.id}>
                    <span>{formatDate(item.scored_at)}</span>
                    <strong>{formatPercent(item.churn_probability)}</strong>
                    <em className={item.activity_gap < 0 ? "history-gap--negative" : ""}>
                      {formatSignedDecimal(item.activity_gap)}
                    </em>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="drawer-reasons">
            <h3>추천 근거</h3>
            <div className="reason-list">
              {detail.reason_codes !== null && typeof detail.reason_codes === "object"
                ? Object.entries(detail.reason_codes).map(([key, value]) => (
                    <span key={key}>{getReasonCodeLabel(String(value))}</span>
                  ))
                : <span>분석 근거가 등록되지 않았습니다.</span>}
            </div>
          </div>

          <div className="drawer-campaigns">
            <div className="drawer-section-heading">
              <h3>캠페인 업무</h3>
              <span>{campaigns.length}건</span>
            </div>
            {campaigns.map((campaign) => (
              <div className="drawer-campaign-row" key={campaign.id}>
                <span>{campaign.campaign_name}</span>
                <strong>{campaignStatusLabels[campaign.status]}</strong>
              </div>
            ))}
            {canManageCampaigns && (
              <div className="campaign-create-form">
                <input
                  value={campaignName}
                  aria-label="캠페인 이름"
                  placeholder="캠페인 이름"
                  onChange={(event) => onCampaignNameChange(event.target.value)}
                />
                <button
                  type="button"
                  disabled={campaignSubmitting || campaignName.trim() === ""}
                  onClick={onCreateCampaign}
                >
                  {campaignSubmitting ? "등록 중..." : "대상 등록"}
                </button>
              </div>
            )}
            {campaignMessage !== "" && <p className="campaign-message" role="status">{campaignMessage}</p>}
          </div>
        </div>
      )}
    </aside>
  );
}

function signedPointsFromRatio(value: number | null): string {
  if (value === null) {
    return "-";
  }
  return `${value > 0 ? "+" : ""}${Math.round(value * 100)}%p`;
}

const REASON_CODE_LABELS: Record<string, string> = {
  long_inactivity: "장기 미사용",
  transaction_decline: "거래 감소",
  low_transaction_activity: "낮은 거래 횟수",
  frequent_contacts: "잦은 문의",
  low_relationship_count: "낮은 보유 상품 수",
  below_expected_activity: "예상 대비 활동 부족",
  priority_activity_gap: "우선 활동 갭",
  dormant_low_utilization: "낮은 카드 이용률(동면 추정)",
  zero_revolving_balance: "리볼빙 잔액 없음",
  stable_activity: "안정적 활동(특이사항 없음)",
};

function getReasonCodeLabel(code: string): string {
  return REASON_CODE_LABELS[code] ?? code;
}

function ClusterProfilePanel({ filters }: { filters: AnalyticsFilters }) {
  const [items, setItems] = useState<ClusterProfileItem[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let isActive = true;
    getClusterProfile(filters)
      .then((response) => {
        if (isActive) {
          setItems(response.items);
          setError("");
        }
      })
      .catch((requestError) => {
        if (isActive) {
          setError(
            requestError instanceof Error ? requestError.message : "군집 프로필을 불러오지 못했습니다.",
          );
        }
      });
    return () => {
      isActive = false;
    };
  }, [filters]);

  return (
    <article className="mini-panel">
      <h3 className="mini-panel__title">군집별 프로필</h3>
      {error !== "" ? (
        <p className="empty-copy">{error}</p>
      ) : items === null ? (
        <p className="queue-state">불러오는 중입니다.</p>
      ) : items.length === 0 ? (
        <p className="empty-copy">표시할 군집 데이터가 없습니다.</p>
      ) : (
        <div className="mini-table">
          <div className="mini-table__row mini-table__row--header">
            <span>군집</span>
            <span>인원</span>
            <span>평균 이탈확률</span>
            <span>평균 활동갭</span>
            <span>평균 거래금액</span>
          </div>
          {items.map((item) => (
            <div className="mini-table__row" key={item.cluster_name}>
              <span className="mini-table__label" title={item.cluster_name}>{item.cluster_name}</span>
              <span>{formatNumber(item.count)}</span>
              <span>{formatPercent(item.avg_churn_probability)}</span>
              <span>{formatDecimal(item.avg_activity_gap)}</span>
              <span>{formatWon(item.avg_total_trans_amt)}</span>
            </div>
          ))}
        </div>
      )}
      {items !== null && items.length > 1 && (
        <div className="mini-panel-chart">
          <div className="mini-panel-chart__header">
            <p className="mini-panel-chart__title">군집별 평균 이탈확률·활동갭 추이</p>
            <div className="mini-panel-chart__legend">
              <span><i style={{ backgroundColor: CHART_LINE_COLOR }} /> 이탈확률</span>
              <span><i style={{ backgroundColor: "#15803d" }} /> 활동갭</span>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={140}>
            <LineChart data={items} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <XAxis
                dataKey="cluster_name"
                stroke="#94a3b8"
                tick={{ fontSize: 9.5 }}
                interval={0}
                tickFormatter={(value: string) => (value.length > 6 ? `${value.slice(0, 6)}…` : value)}
              />
              <YAxis
                yAxisId="left"
                stroke="#94a3b8"
                tick={{ fontSize: 9.5 }}
                tickFormatter={(value: number) => formatPercent(value)}
                width={34}
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                stroke="#94a3b8"
                tick={{ fontSize: 9.5 }}
                tickFormatter={(value: number) => formatDecimal(value)}
                width={34}
              />
              <Tooltip
                formatter={(value: unknown, name: unknown) => {
                  if (name === "avg_activity_gap") {
                    return [formatDecimal(toNumber(value)), "평균 활동갭"];
                  }
                  return [formatPercent(toNumber(value)), "평균 이탈확률"];
                }}
                labelFormatter={(label: unknown) => String(label)}
              />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="avg_churn_probability"
                stroke={CHART_LINE_COLOR}
                strokeWidth={2}
                dot={{ r: 3, fill: CHART_LINE_COLOR }}
                activeDot={{ r: 5 }}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="avg_activity_gap"
                stroke="#15803d"
                strokeWidth={2}
                dot={{ r: 3, fill: "#15803d" }}
                activeDot={{ r: 5 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </article>
  );
}

function RiskClusterHeatmap({ filters }: { filters: AnalyticsFilters }) {
  const [data, setData] = useState<RiskClusterCrosstabResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let isActive = true;
    getRiskClusterCrosstab(filters)
      .then((response) => {
        if (isActive) {
          setData(response);
          setError("");
        }
      })
      .catch((requestError) => {
        if (isActive) {
          setError(
            requestError instanceof Error ? requestError.message : "교차표를 불러오지 못했습니다.",
          );
        }
      });
    return () => {
      isActive = false;
    };
  }, [filters]);

  return (
    <article className="mini-panel">
      <h3 className="mini-panel__title">위험도 × 군집 교차표</h3>
      {error !== "" ? (
        <p className="empty-copy">{error}</p>
      ) : data === null ? (
        <p className="queue-state">불러오는 중입니다.</p>
      ) : data.cells.length === 0 ? (
        <p className="empty-copy">표시할 데이터가 없습니다.</p>
      ) : (
        (() => {
          const maxCount = Math.max(...data.cells.map((cell) => cell.count), 1);
          const cellByKey = new Map(
            data.cells.map((cell) => [`${cell.risk_level}__${cell.cluster_name}`, cell.count]),
          );
          return (
            <div className="heatmap-wrap">
              <div
                className="heatmap"
                style={{ gridTemplateColumns: `auto repeat(${data.clusters.length}, 1fr)` }}
              >
                <span className="heatmap__corner" />
                {data.clusters.map((cluster) => (
                  <span className="heatmap__col-label" key={cluster} title={cluster}>
                    {cluster}
                  </span>
                ))}
                {data.risk_levels.map((riskLevel) => (
                  <Fragment key={riskLevel}>
                    <span className="heatmap__row-label">
                      {riskLabels[riskLevel as CustomerInsight["risk_level"]] ?? riskLevel}
                    </span>
                    {data.clusters.map((cluster) => {
                      const count = cellByKey.get(`${riskLevel}__${cluster}`) ?? 0;
                      const intensity = Math.max(count / maxCount, count > 0 ? 0.08 : 0);
                      return (
                        <span
                          className="heatmap__cell"
                          key={`${riskLevel}-${cluster}`}
                          style={{
                            backgroundColor: `rgba(29, 78, 216, ${intensity})`,
                            color: intensity > 0.55 ? "#ffffff" : "#2c2c2e",
                          }}
                        >
                          {formatNumber(count)}
                        </span>
                      );
                    })}
                  </Fragment>
                ))}
              </div>
              <div className="heatmap-legend">
                <span>적음</span>
                <span className="heatmap-legend__bar" aria-hidden="true" />
                <span>많음</span>
              </div>
            </div>
          );
        })()
      )}
    </article>
  );
}

function ReasonCodeCooccurrencePanel({ filters }: { filters: AnalyticsFilters }) {
  const [data, setData] = useState<ReasonCodeCooccurrenceResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let isActive = true;
    getReasonCodeCooccurrence(filters)
      .then((response) => {
        if (isActive) {
          setData(response);
          setError("");
        }
      })
      .catch((requestError) => {
        if (isActive) {
          setError(
            requestError instanceof Error ? requestError.message : "동시발생 분석을 불러오지 못했습니다.",
          );
        }
      });
    return () => {
      isActive = false;
    };
  }, [filters]);

  return (
    <article className="mini-panel">
      <h3 className="mini-panel__title">사유코드 동시발생 Top 10</h3>
      {error !== "" ? (
        <p className="empty-copy">{error}</p>
      ) : data === null ? (
        <p className="queue-state">불러오는 중입니다.</p>
      ) : data.pairs.length === 0 ? (
        <p className="empty-copy">표시할 조합이 없습니다.</p>
      ) : (
        <div className="cooccurrence-list">
          {data.pairs.map((pair) => (
            <div className="cooccurrence-row" key={`${pair.code_a}-${pair.code_b}`}>
              <span className="cooccurrence-row__pair">
                {getReasonCodeLabel(pair.code_a)} + {getReasonCodeLabel(pair.code_b)}
              </span>
              <strong>{formatNumber(pair.count)}명</strong>
            </div>
          ))}
        </div>
      )}
    </article>
  );
}

function ReasonCodeDistributionPanel({ filters }: { filters: AnalyticsFilters }) {
  const [data, setData] = useState<ReasonCodeDistribution | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let isActive = true;
    getReasonCodeDistribution(filters.riskLevel ? { risk_level: filters.riskLevel } : {})
      .then((response) => {
        if (isActive) {
          setData(response);
          setError("");
        }
      })
      .catch((requestError) => {
        if (isActive) {
          setError(
            requestError instanceof Error ? requestError.message : "사유코드 분포를 불러오지 못했습니다.",
          );
        }
      });
    return () => {
      isActive = false;
    };
  }, [filters]);

  return (
    <article className="mini-panel">
      <h3 className="mini-panel__title">이탈 사유코드 분포</h3>
      {error !== "" ? (
        <p className="empty-copy">{error}</p>
      ) : data === null ? (
        <p className="queue-state">불러오는 중입니다.</p>
      ) : Object.keys(data.counts).length === 0 ? (
        <p className="empty-copy">표시할 사유코드가 없습니다.</p>
      ) : (
        <>
          <div className="reason-code-bars">
            {Object.entries(data.counts)
              .sort(([, countA], [, countB]) => countB - countA)
              .map(([code, count]) => {
                const maxCount = Math.max(...Object.values(data.counts), 1);
                return (
                  <div className="reason-code-bars__row" key={code}>
                    <div className="reason-code-bars__head">
                      <span>{getReasonCodeLabel(code)}</span>
                      <strong>{formatNumber(count)}명 · {formatPercent(count / data.total_customers)}</strong>
                    </div>
                    <div className="reason-code-bars__track">
                      <span style={{ width: `${(count / maxCount) * 100}%` }} />
                    </div>
                  </div>
                );
              })}
          </div>
          <p className="mini-panel__caption">전체 {formatNumber(data.total_customers)}명 기준 · 한 고객이 여러 사유코드에 동시에 해당할 수 있습니다.</p>
        </>
      )}
    </article>
  );
}

type MetricHelpItem = {
  label: string;
  description: string;
};

const CAMPAIGN_FEEDBACK_HELP_ITEMS: MetricHelpItem[] = [
  {
    label: "접촉률",
    description: "전체 대상 중 실제로 전화·문자·이메일 등 연락이 완료된 고객의 비율입니다. 100명 중 70명에게 연락했다면 70%입니다.",
  },
  {
    label: "미처리 대상",
    description: "아직 연락이 완료되지 않은 고객 수입니다. 숫자가 많으면 분석보다 운영팀의 실행이 지연되고 있을 수 있습니다.",
  },
  {
    label: "전환율",
    description: "캠페인 대상 중 신청·재이용·추가 거래 등 캠페인이 목표로 한 행동을 한 고객의 비율입니다.",
  },
  {
    label: "치료군 전환율",
    description: "캠페인 메시지·혜택·상담을 실제로 받은 그룹의 전환율입니다. 이 수치만으로는 캠페인 효과를 확정하지 않고 대조군과 비교합니다.",
  },
  {
    label: "대조군 전환율",
    description: "비슷한 고객 중 일부러 캠페인을 받지 않도록 남겨둔 비교 그룹의 전환율입니다. 캠페인이 없어도 자연스럽게 전환하는 비율을 보여줍니다.",
  },
  {
    label: "증분 전환 효과",
    description: "치료군 전환율에서 대조군 전환율을 뺀 값입니다. 예를 들어 치료군이 30%, 대조군이 10%이면 캠페인의 추가 효과는 +20%p로 해석합니다.",
  },
  {
    label: "ROI",
    description: "캠페인에 쓴 비용 대비 추가로 얻은 매출입니다. 0%보다 크면 비용보다 많은 추가 매출을 만들었다는 뜻입니다.",
  },
  {
    label: "유지율",
    description: "전환 후 설정된 관측 기간(예: 30일)이 지나도 계속 활동하거나 거래한 고객의 비율입니다. 아직 기간이 지나지 않은 고객은 계산에서 제외합니다.",
  },
];

const EXPERIMENT_TABLE_HELP_ITEMS: MetricHelpItem[] = [
  {
    label: "캠페인",
    description: "비교 대상 캠페인입니다. 여러 캠페인을 함께 실행 중이면 캠페인별로 행이 나뉘어 표시됩니다.",
  },
  {
    label: "개입군 전환",
    description: "캠페인 메시지·혜택·상담을 실제로 받은 치료군의 전환율입니다.",
  },
  {
    label: "비개입군 전환",
    description: "캠페인을 받지 않도록 남겨둔 대조군의 전환율입니다. 캠페인이 없어도 자연스럽게 전환하는 비율을 보여줍니다.",
  },
  {
    label: "증분효과",
    description: "개입군 전환율에서 비개입군 전환율을 뺀 값으로, 캠페인 자체가 만들어낸 추가 효과입니다.",
  },
  {
    label: "ROI",
    description: "캠페인에 쓴 비용 대비 증분 매출(추가로 얻은 매출)의 비율입니다.",
  },
  {
    label: "방어매출",
    description: "증분 전환 효과로 추가 확보한 것으로 추정되는 매출 금액입니다.",
  },
];

function MetricHelpButton({
  dialogId,
  title,
  items,
  note,
}: {
  dialogId: string;
  title: string;
  items: MetricHelpItem[];
  note?: string;
}) {
  const [showMetricHelp, setShowMetricHelp] = useState(false);
  const titleId = `${dialogId}-title`;

  useEffect(() => {
    if (!showMetricHelp) {
      return;
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setShowMetricHelp(false);
      }
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [showMetricHelp]);

  return (
    <>
      <button
        className="campaign-feedback-help"
        type="button"
        aria-expanded={showMetricHelp}
        aria-controls={dialogId}
        onClick={() => setShowMetricHelp((current) => !current)}
      >
        <span aria-hidden="true">?</span>
        지표 설명
      </button>
      {showMetricHelp && (
        <div className="campaign-feedback-help-backdrop">
          <section
            className="campaign-feedback-help-dialog"
            id={dialogId}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
          >
            <div className="campaign-feedback-help-dialog__header">
              <div>
                <h3 id={titleId}>{title}</h3>
              </div>
              <button
                className="campaign-feedback-help-close"
                type="button"
                aria-label="지표 설명 닫기"
                onClick={() => setShowMetricHelp(false)}
              >
                ×
              </button>
            </div>
            <div className="campaign-feedback__help">
              {items.map((item) => (
                <div key={item.label}>
                  <strong>{item.label}</strong>
                  <span>{item.description}</span>
                </div>
              ))}
            </div>
            {note !== undefined && (
              <p className="campaign-feedback__help-note">{note}</p>
            )}
          </section>
        </div>
      )}
    </>
  );
}

function InsightsTab({
  performance,
  isLoading,
  error,
  filters,
}: {
  performance: CampaignPerformance | null;
  isLoading: boolean;
  error: string;
  filters: AnalyticsFilters;
}) {
  const summary = performance?.summary ?? null;
  const byCampaign = performance?.by_campaign ?? [];

  return (
    <section className="insights-tab" aria-label="분석팀 인사이트">
      <div className="insights-header">
        <div className="insights-header__title">
        </div>
      </div>

      <div className="insights-section">
        <h2 className="insights-section__title">모델 3종 참조</h2>
        <div className="model-ref-grid">
          <article className="model-ref-card model-ref-card--classification">
            <span className="model-ref-badge">분류 모델</span>
            <p className="model-ref-quote">"지금 누가 위험한가"</p>
            <p className="model-ref-desc">
              여러 특성을 종합한 판단. "누구부터 상담해야 하는가"의 1차 신호입니다.
            </p>
            <div className="model-ref-kpi">
              <span className="model-ref-kpi__label">대시보드 연결 KPI</span>
              <div className="model-ref-kpi__pills">
                <span className="model-ref-pill">위험도별 SLA</span>
                <span className="model-ref-pill">고위험 커버리지</span>
              </div>
            </div>
          </article>

          <article className="model-ref-card model-ref-card--regression">
            <span className="model-ref-badge model-ref-badge--regression">회귀 모델</span>
            <p className="model-ref-quote">"평소와 다르게 행동하는가"</p>
            <p className="model-ref-desc">
              실제 거래 활동이 예상치에서 벗어난 정도를 포착해 조기 이상 신호로 씁니다.
            </p>
            <div className="model-ref-kpi">
              <span className="model-ref-kpi__label">대시보드 연결 KPI</span>
              <div className="model-ref-kpi__pills">
                <span className="model-ref-pill">조기경보 겹침 고객 (이중신호)</span>
              </div>
            </div>
          </article>

          <article className="model-ref-card model-ref-card--clustering">
            <span className="model-ref-badge model-ref-badge--clustering">군집 모델</span>
            <p className="model-ref-quote">"어떤 유형의 고객인가"</p>
            <p className="model-ref-desc">
              지금은 표시만 됩니다. 군집별 증분 유지효과 KPI가 처음으로 실제 예산 배분
              판단에 연결됩니다.
            </p>
            <div className="model-ref-kpi">
              <span className="model-ref-kpi__label">대시보드 연결 KPI</span>
              <div className="model-ref-kpi__pills">
                <span className="model-ref-pill">군집별 증분 유지효과</span>
              </div>
            </div>
          </article>
        </div>
      </div>

      <div className="insights-section">
        <h2 className="insights-section__title">통계 분석</h2>
        <div className="eda-charts-grid">
          <CategoricalChurnRateChart filters={filters} />
          <NumericDistributionChart filters={filters} />
          <FeatureCorrelationChart filters={filters} />
        </div>
      </div>

      <div className="insights-section">
        <div className="insights-section__header">
          <span className="insights-status-badge">이미 완성</span>
          <h2 className="insights-section__title">캠페인 실험효과성 분석</h2>
          <span className="insights-file-ref">performance_service.py</span>
          <MetricHelpButton
            dialogId="experiment-table-metric-help"
            title="캠페인 실험효과성 분석 지표 설명"
            items={EXPERIMENT_TABLE_HELP_ITEMS}
            note="증분효과가 클수록 캠페인 자체의 효과가 높다고 볼 수 있지만, 충분한 대상 수와 관측 기간이 함께 확보되어야 신뢰할 수 있습니다."
          />
        </div>
        {isLoading ? (
          <p className="queue-state">캠페인 실험 효과를 집계하는 중입니다.</p>
        ) : error !== "" ? (
          <p className="campaign-feedback__error" role="alert">{error}</p>
        ) : summary === null || summary.target_count === 0 ? (
          <p className="queue-state">분석할 캠페인 실행 결과가 없습니다.</p>
        ) : (
          <>
            <div className="experiment-table">
              <div className="experiment-table__header">
                <span>캠페인</span>
                <span>개입군 전환</span>
                <span>비개입군 전환</span>
                <span>증분효과</span>
                <span>ROI</span>
                <span>방어매출</span>
              </div>
              {(byCampaign.length > 0 ? byCampaign : [
                {
                  key: "all",
                  label: "전체 캠페인",
                  treatment_conversion_rate: summary.treatment_conversion_rate,
                  control_conversion_rate: summary.control_conversion_rate,
                  incremental_conversion_effect: summary.incremental_conversion_effect,
                  roi: summary.roi,
                  incremental_revenue: summary.incremental_revenue,
                },
              ]).map((row) => (
                <div className="experiment-table__row" key={row.key}>
                  <span className="experiment-table__name">{row.label}</span>
                  <strong>{formatPercent(row.treatment_conversion_rate ?? 0)}</strong>
                  <strong>{formatPercent(row.control_conversion_rate ?? 0)}</strong>
                  <strong className="experiment-table__positive">
                    {signedPointsFromRatio(row.incremental_conversion_effect)}
                  </strong>
                  <strong className="experiment-table__roi">
                    {row.roi === null ? "-" : `${row.roi.toFixed(1)}×`}
                  </strong>
                  <span>{formatNumber(Math.round(row.incremental_revenue ?? 0))}원</span>
                </div>
              ))}
            </div>
            <p className="experiment-table__note">
              {formatNumber(summary.target_count)}명 대상 · 접촉률 {formatPercent(summary.contact_rate)}
            </p>
          </>
        )}
      </div>

      <div className="insights-section">
        <div className="insights-section__header">
          <span className="insights-status-badge insights-status-badge--new">신규·낮음</span>
          <h2 className="insights-section__title">세그먼트 심화 분석</h2>
          <span className="insights-file-ref">customer_insights</span>
        </div>
        <div className="mini-panel-grid">
          <ClusterProfilePanel filters={filters} />
          <RiskClusterHeatmap filters={filters} />
          <ReasonCodeDistributionPanel filters={filters} />
          <ReasonCodeCooccurrencePanel filters={filters} />
        </div>
      </div>
    </section>
  );
}

export function DashboardPage({ user, showCampaignFeedback = false }: DashboardPageProps) {
  const [data, setData] = useState<CustomerInsightList | null>(null);
  const [error, setError] = useState("");
  const [riskFilter, setRiskFilter] = useState<RiskFilter>("");
  const [clusterFilter, setClusterFilter] = useState("");
  const [customerIdFilter, setCustomerIdFilter] = useState("");
  const [sortBy, setSortBy] = useState<SortBy>("churn_probability");
  const [sortOrder, setSortOrder] = useState<SortOrder>("desc");
  const [page, setPage] = useState(1);
  const [selectedCustomerId, setSelectedCustomerId] = useState<number | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<CustomerInsightDetail | null>(null);
  const [selectedHistory, setSelectedHistory] = useState<CustomerInsightHistory | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [batch, setBatch] = useState<LatestBatch | null>(null);
  const [campaignTargets, setCampaignTargets] = useState<CampaignTarget[]>([]);
  const [campaignDrafts, setCampaignDrafts] = useState<Record<number, CampaignDraft>>({});
  const [campaignLoading, setCampaignLoading] = useState(true);
  const [campaignError, setCampaignError] = useState("");
  const [campaignPerformance, setCampaignPerformance] = useState<CampaignPerformance | null>(null);
  const shouldShowCampaignFeedback = user.role === "analyst" || showCampaignFeedback;
  const [campaignPerformanceLoading, setCampaignPerformanceLoading] = useState(shouldShowCampaignFeedback);
  const [campaignPerformanceError, setCampaignPerformanceError] = useState("");
  const [campaignName, setCampaignName] = useState("이탈 위험 리텐션");
  const [campaignSubmitting, setCampaignSubmitting] = useState(false);
  const [campaignMessage, setCampaignMessage] = useState("");
  const [activeView, setActiveView] = useState<"dashboard" | "insights">(
    user.role === "analyst" ? "insights" : "dashboard",
  );

  const canCreateCampaignTargets = user.role === "admin" || user.role === "marketing";
  const canProcessCampaignTargets = user.role === "admin" || user.role === "operations";

  useEffect(() => {
    let isActive = true;
    const query: InsightQuery = {
      risk_level: riskFilter || undefined,
      cluster_name: clusterFilter.trim() || undefined,
      customer_id: getCustomerIdFilter(customerIdFilter),
      sort_by: sortBy,
      sort_order: sortOrder,
      page,
      page_size: PAGE_SIZE,
    };

    const loadInsights = async () => {
      try {
        const response = await listCustomerInsights(query);
        if (isActive) {
          setData(response);
          setError("");
        }
      } catch (requestError) {
        if (isActive) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : "고객 분석 결과를 불러오지 못했습니다.",
          );
        }
      }
    };

    void loadInsights();
    return () => {
      isActive = false;
    };
  }, [clusterFilter, customerIdFilter, page, riskFilter, sortBy, sortOrder]);

  useEffect(() => {
    let isActive = true;
    const loadBatch = async () => {
      try {
        const response = await getLatestBatch();
        if (isActive) {
          setBatch(response);
        }
      } catch {
        if (isActive) {
          setBatch(null);
        }
      }
    };
    void loadBatch();
    return () => {
      isActive = false;
    };
  }, []);

  useEffect(() => {
    if (!shouldShowCampaignFeedback && activeView !== "insights") {
      return;
    }

    let isActive = true;
    void getCampaignPerformance()
      .then((response) => {
        if (isActive) {
          setCampaignPerformance(response);
          setCampaignPerformanceError("");
        }
      })
      .catch((requestError) => {
        if (isActive) {
          setCampaignPerformanceError(
            requestError instanceof Error
              ? requestError.message
              : "캠페인 성과를 불러오지 못했습니다.",
          );
        }
      })
      .finally(() => {
        if (isActive) {
          setCampaignPerformanceLoading(false);
        }
      });

    return () => {
      isActive = false;
    };
  }, [activeView, shouldShowCampaignFeedback]);

  useEffect(() => {
    let isActive = true;
    const loadCampaigns = async () => {
      try {
        const response = await listCampaignTargets({ page: 1, page_size: 20 });
        if (isActive) {
          setCampaignTargets(response.items);
          setCampaignError("");
          setCampaignLoading(false);
        }
      } catch (requestError) {
        if (isActive) {
          setCampaignLoading(false);
          setCampaignError(
            requestError instanceof Error
              ? requestError.message
              : "캠페인 처리 현황을 불러오지 못했습니다.",
          );
        }
      }
    };
    void loadCampaigns();
    return () => {
      isActive = false;
    };
  }, []);

  const handleSelectCustomer = async (customerId: number) => {
    setSelectedCustomerId(customerId);
    setSelectedDetail(null);
    setSelectedHistory(null);
    setDetailError("");
    setDetailLoading(true);
    setHistoryLoading(true);
    setCampaignMessage("");
    setCampaignName("이탈 위험 리텐션");
    try {
      const [detail, history] = await Promise.all([
        getCustomerInsight(customerId),
        getCustomerInsightHistory(customerId),
      ]);
      setSelectedDetail(detail);
      setSelectedHistory(history);
    } catch (requestError) {
      setDetailError(
        requestError instanceof Error
          ? requestError.message
          : "고객 상세 정보를 불러오지 못했습니다.",
      );
    } finally {
      setDetailLoading(false);
      setHistoryLoading(false);
    }
  };

  const handleCreateCampaign = async () => {
    if (selectedDetail === null || campaignName.trim() === "") {
      return;
    }
    setCampaignSubmitting(true);
    setCampaignMessage("");
    try {
      const target = await createCampaignTarget({
        customer_insight_id: selectedDetail.id,
        campaign_name: campaignName.trim(),
      });
      setCampaignTargets((current) => [target, ...current]);
      setCampaignMessage("캠페인 대상에 등록했습니다.");
      setCampaignName("이탈 위험 리텐션");
    } catch (requestError) {
      setCampaignMessage(
        requestError instanceof Error ? requestError.message : "캠페인 등록에 실패했습니다.",
      );
    } finally {
      setCampaignSubmitting(false);
    }
  };

  const handleCampaignDraftChange = (targetId: number, draft: CampaignDraft) => {
    setCampaignDrafts((current) => ({ ...current, [targetId]: draft }));
  };

  const handleSaveCampaign = async (targetId: number) => {
    const target = campaignTargets.find((item) => item.id === targetId);
    if (target === undefined) {
      return;
    }
    const draft = campaignDrafts[targetId] ?? {
      status: target.status,
      result: target.result ?? "",
      result_notes: target.result_notes ?? "",
      converted: target.converted,
    };
    try {
      const updated = await updateCampaignTarget(targetId, {
        status: draft.status,
        result: draft.result || undefined,
        result_notes: draft.result_notes || undefined,
        result_code: draft.status === "completed"
          ? (draft.converted ? "converted" : "not_converted")
          : draft.status === "contacted" ? "contacted" : undefined,
        converted: draft.converted,
      });
      setCampaignTargets((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setCampaignMessage("캠페인 처리 결과를 저장했습니다.");
    } catch (requestError) {
      setCampaignError(
        requestError instanceof Error ? requestError.message : "캠페인 처리 결과 저장에 실패했습니다.",
      );
    }
  };

  const downloadCsv = () => {
    if (data === null) {
      return;
    }
    const header = ["customer_id", "risk_level", "churn_probability", "expected_transaction_count", "activity_gap", "cluster_name", "cluster_confidence", "recommended_action", "scored_at"];
    const rows = data.items.map((item) => [
      item.customer_id,
      item.risk_level,
      item.churn_probability,
      item.expected_transaction_count,
      item.activity_gap,
      item.cluster_name,
      item.cluster_confidence ?? "",
      item.recommended_action,
      item.scored_at,
    ]);
    const csv = [header, ...rows].map((row) => row.map(escapeCsv).join(",")).join("\n");
    const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "customer-insights.csv";
    link.click();
    URL.revokeObjectURL(url);
  };

  const focusHighRisk = () => {
    setRiskFilter("high");
    setPage(1);
  };

  const resetFilters = () => {
    setRiskFilter("");
    setClusterFilter("");
    setCustomerIdFilter("");
    setSortBy("churn_probability");
    setSortOrder("desc");
    setPage(1);
  };

  const handleHeaderSort = (field: SortBy) => {
    if (field === sortBy) {
      setSortOrder((current) => (current === "desc" ? "asc" : "desc"));
    } else {
      setSortBy(field);
      setSortOrder("desc");
    }
    setPage(1);
  };


  const isInitialLoading = data === null && error === "";
  const clusterOptions = data === null ? [] : getClusterOptions(data.stats.cluster_options);
  const highRiskCount = data?.stats.risk_counts.high ?? 0;
  const analyticsFilters = useMemo<AnalyticsFilters>(() => ({
    riskLevel: riskFilter,
    clusterName: clusterFilter.trim() || undefined,
    customerId: getCustomerIdFilter(customerIdFilter),
  }), [clusterFilter, customerIdFilter, riskFilter]);

  return (
    <>
      <nav className="dashboard-tabs" aria-label="대시보드 탭">
        {(user.role === "analyst"
          ? (["insights", "dashboard"] as const)
          : (["dashboard", "insights"] as const)
        ).map((view) => (
          <button
            key={view}
            type="button"
            className={`dashboard-tab${activeView === view ? " dashboard-tab--active" : ""}`}
            onClick={() => setActiveView(view)}
          >
            {view === "dashboard" ? "대시보드" : "인사이트"}
          </button>
        ))}
      </nav>

      {activeView === "insights" && (
        <InsightsTab
          performance={campaignPerformance}
          isLoading={campaignPerformanceLoading}
          error={campaignPerformanceError}
          filters={analyticsFilters}
        />
      )}

      {activeView === "dashboard" && isInitialLoading && <DashboardSkeleton />}

      {activeView === "dashboard" && error !== "" && (
        <section className="dashboard-error" role="alert">
          <strong>분석 결과를 불러오지 못했습니다.</strong>
          <span>{error}</span>
          <button type="button" onClick={() => window.location.reload()}>새로고침</button>
        </section>
      )}

      {activeView === "dashboard" && data !== null && error === "" && (
        <section className="bento-grid" aria-label="고객 분석 대시보드">
          <div className="kpi-and-risk-row">
            <div className="kpi-row kpi-row--inline">
              <div className="kpi-item">
                <strong>{formatNumber(data.stats.total)}</strong>
                <span>분석 대상 고객</span>
              </div>
              <div className="kpi-item">
                <strong>{formatNumber(data.stats.total - highRiskCount)}</strong>
                <span>정상 관리 고객</span>
              </div>
              <button className="kpi-item kpi-item--danger" type="button" onClick={focusHighRisk}>
                <strong>{formatNumber(highRiskCount)}</strong>
                <span>고위험 고객</span>
              </button>
              <div className="kpi-item">
                <strong>{formatPercent(data.stats.average_churn_probability)}</strong>
                <span>평균 이탈 확률</span>
              </div>
            </div>

            <RiskOverview data={data} />
          </div>

          <div className="eda-charts-grid">
            <BatchOverview batch={batch} wide />
          </div>

          <article className="bento-card bento-card--table">
            <div className="filter-bar filter-bar--embedded" aria-label="고객 분석 결과 필터">
              <label className="filter-bar__field filter-bar__field--search">
                <span>고객 ID</span>
                <input
                  type="search"
                  inputMode="numeric"
                  value={customerIdFilter}
                  placeholder="전체"
                  onChange={(event) => {
                    setCustomerIdFilter(event.target.value);
                    setPage(1);
                  }}
                />
              </label>
              <label className="filter-bar__field">
                <span>위험도</span>
                <select
                  value={riskFilter}
                  onChange={(event) => {
                    setRiskFilter(event.target.value as RiskFilter);
                    setPage(1);
                  }}
                >
                  <option value="">전체</option>
                  <option value="high">높음</option>
                  <option value="medium">주의</option>
                  <option value="low">낮음</option>
                </select>
              </label>
              <label className="filter-bar__field filter-bar__field--cluster">
                <span>군집</span>
                <select
                  aria-label="군집"
                  value={clusterFilter}
                  onChange={(event) => {
                    setClusterFilter(event.target.value);
                    setPage(1);
                  }}
                >
                  <option value="">전체 군집</option>
                  {clusterOptions.map(([cluster, count]) => (
                    <option key={cluster} value={cluster}>
                      {cluster} ({formatNumber(count)}명)
                    </option>
                  ))}
                </select>
              </label>
              <span className="filter-bar__spacer" aria-hidden="true" />
              <button className="filter-bar__reset" type="button" onClick={resetFilters}>초기화</button>
            </div>

            <div className="table-card__header">
              <div>
                <h2>고객별 분석 결과</h2>
              </div>
              <div className="table-card__actions">
                <button className="export-button" type="button" onClick={downloadCsv}>
                  CSV 다운로드
                </button>
                <span className="table-count">총 {formatNumber(data.total)}명</span>
              </div>
            </div>

            {data.items.length === 0 ? (
              <div className="empty-state">
                <span aria-hidden="true">⌁</span>
                <strong>조건에 맞는 고객이 없습니다.</strong>
                <p>필터를 초기화하거나 다른 조건으로 검색해 보세요.</p>
              </div>
            ) : (
              <div className="insight-list" role="list" aria-label="고객 분석 결과 목록">
                <div className="insight-list__header">
                  <span>고객</span><span>위험도</span>
                  <SortableHeader field="churn_probability" label="이탈 확률" sortBy={sortBy} sortOrder={sortOrder} onSort={handleHeaderSort} />
                  <SortableHeader field="actual_transaction_count" label="실제 거래" sortBy={sortBy} sortOrder={sortOrder} onSort={handleHeaderSort} />
                  <SortableHeader field="expected_transaction_count" label="예상 거래" sortBy={sortBy} sortOrder={sortOrder} onSort={handleHeaderSort} />
                  <SortableHeader field="activity_gap" label="거래 차이" sortBy={sortBy} sortOrder={sortOrder} onSort={handleHeaderSort} />
                  <SortableHeader field="total_trans_amt" label="총 거래금액" sortBy={sortBy} sortOrder={sortOrder} onSort={handleHeaderSort} />
                  <SortableHeader field="card_category" label="카드분류" sortBy={sortBy} sortOrder={sortOrder} onSort={handleHeaderSort} />
                  <SortableHeader field="contacts_count_12_mon" label="문의횟수" sortBy={sortBy} sortOrder={sortOrder} onSort={handleHeaderSort} />
                  <span>군집</span><span>추천 액션</span><span />
                </div>
                {data.items.map((insight) => (
                  <InsightRow key={insight.id} insight={insight} onSelect={(id) => void handleSelectCustomer(id)} />
                ))}
              </div>
            )}

            <div className="pagination">
              <span className="pagination__summary">{data.total === 0 ? "0" : `${(data.page - 1) * data.page_size + 1}–${Math.min(data.page * data.page_size, data.total)}`} / {formatNumber(data.total)}명</span>
              <div className="pagination__pages">
                <button
                  type="button"
                  className="pagination__arrow"
                  disabled={data.page <= 1}
                  onClick={() => setPage((current) => current - 1)}
                  aria-label="이전 페이지"
                >
                  ←
                </button>
                {getPageNumbers(data.page, data.total_pages).map((pageNumber, index) =>
                  pageNumber === "ellipsis" ? (
                    <span key={`ellipsis-${index}`} className="pagination__ellipsis">…</span>
                  ) : (
                    <button
                      key={pageNumber}
                      type="button"
                      className={pageNumber === data.page ? "pagination__page pagination__page--active" : "pagination__page"}
                      aria-current={pageNumber === data.page ? "page" : undefined}
                      aria-label={`${pageNumber} 페이지`}
                      onClick={() => setPage(pageNumber)}
                    >
                      {pageNumber}
                    </button>
                  ),
                )}
                <button
                  type="button"
                  className="pagination__arrow"
                  disabled={data.page >= data.total_pages}
                  onClick={() => setPage((current) => current + 1)}
                  aria-label="다음 페이지"
                >
                  →
                </button>
              </div>
              <span className="pagination__spacer" aria-hidden="true" />
            </div>
          </article>

          {campaignError !== "" && <p className="campaign-error" role="alert">{campaignError}</p>}
          {shouldShowCampaignFeedback ? (
            <CampaignFeedback
              performance={campaignPerformance}
              isLoading={campaignPerformanceLoading}
              error={campaignPerformanceError}
            />
          ) : (
            <CampaignQueue
              targets={campaignTargets}
              drafts={campaignDrafts}
              canManage={canProcessCampaignTargets}
              user={user}
              isLoading={campaignLoading}
              onDraftChange={handleCampaignDraftChange}
              onSave={(targetId) => void handleSaveCampaign(targetId)}
            />
          )}
        </section>
      )}

      {selectedCustomerId !== null && (
        <>
          <button className="drawer-backdrop" type="button" aria-label="상세 패널 닫기" onClick={() => setSelectedCustomerId(null)} />
          <CustomerDetailPanel
            detail={selectedDetail}
            history={selectedHistory}
            historyLoading={historyLoading}
            campaigns={campaignTargets.filter((target) => target.customer_id === selectedCustomerId)}
            canManageCampaigns={canCreateCampaignTargets}
            campaignName={campaignName}
            campaignSubmitting={campaignSubmitting}
            campaignMessage={campaignMessage}
            onCampaignNameChange={setCampaignName}
            onCreateCampaign={() => void handleCreateCampaign()}
            isLoading={detailLoading}
            error={detailError}
            onClose={() => setSelectedCustomerId(null)}
          />
        </>
      )}
    </>
  );
}

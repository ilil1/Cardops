import { createContext, Fragment, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { listTeamMembers, updateTeamMember, type TeamMember } from "../../api/team";
import type { ApiError } from "../../api/client";
import type { AuthUser } from "../../api/auth";
import {
  createCampaignTarget,
  listCampaigns,
  listCampaignTargets,
  updateCampaignTarget,
  type Campaign,
  type CampaignLifecycleStatus,
  type CampaignStatus,
  type CampaignTarget,
  type CampaignTargetList,
  type CampaignResultCode,
} from "../../api/campaigns";

import {
  getCampaignPerformance,
  type CampaignPerformance,
} from "../../api/campaigns";
import {
  listCustomerInsights,
  getHighRiskCoverage,
  getDualSignalCount,
  getReasonCodeDistribution,
  type CustomerInsight,
  type CustomerInsightList,
  type DualSignalSummary,
  type HighRiskCoverage,
  type InsightQuery,
  type ReasonCodeDistribution,
} from "../../api/insights";


const roleLabels: Record<AuthUser["role"], string> = {
  admin: "관리자",
  analyst: "분석 담당자",
  operations: "운영 담당자",
  marketing: "마케팅 담당자",
};

const riskLabels: Record<CustomerInsight["risk_level"], string> = {
  low: "낮음",
  medium: "주의",
  high: "높음",
};

const campaignStatusLabels: Record<CampaignStatus, string> = {
  pending: "대기",
  assigned: "담당 배정",
  contacted: "접촉 완료",
  completed: "처리 완료",
  cancelled: "취소",
};

const lifecycleLabels: Record<CampaignLifecycleStatus, string> = {
  draft: "초안",
  scheduled: "예약",
  active: "진행 중",
  paused: "일시 중지",
  completed: "완료",
  cancelled: "취소",
};

const REASON_CODE_LABELS: Record<string, string> = {
  low_transaction_activity: "낮은 거래 활동",
  transaction_decline: "거래 감소",
  long_inactivity: "장기 미사용",
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

const campaignStatusTransitions: Record<CampaignStatus, CampaignStatus[]> = {
  pending: ["pending", "assigned", "cancelled"],
  assigned: ["pending", "assigned", "contacted", "cancelled"],
  contacted: ["contacted", "completed", "cancelled"],
  completed: ["completed"],
  cancelled: ["cancelled"],
};

const campaignResultLabels: Record<CampaignResultCode, string> = {
  contacted: "접촉",
  converted: "전환",
  not_converted: "미전환",
  no_response: "응답 없음",
  declined: "거절",
  opted_out: "수신 거부",
  invalid_contact: "연락처 오류",
};

const finalCampaignResultCodes: CampaignResultCode[] = [
  "converted",
  "not_converted",
  "no_response",
  "declined",
  "opted_out",
  "invalid_contact",
];

const roleDescriptions: Record<AuthUser["role"], string> = {
  admin: "팀 계정과 업무 권한을 관리합니다.",
  analyst: "고객 분석 결과와 모델 배치 상태를 확인합니다.",
  operations: "고위험 고객의 상담과 후속 처리를 관리합니다.",
  marketing: "고객 세그먼트와 캠페인 실행 결과를 관리합니다.",
};

type GuideEntry = { desc: string };

const GUIDE_CONTENT: Record<string, GuideEntry> = {
  "이중 신호 고객": {
    desc: "분류모델 고위험(risk_level=high)과 회귀모델 활동성 갭 하위 20%에 동시 해당하는 고객입니다. 한쪽 모델만 볼 때보다 놓치는 고객이 줄어들어 최우선 상담 대상이 됩니다.",
  },
  "미처리 대기열": {
    desc: "전체 백로그 크기와 처리 상태별 건수입니다.",
  },
  "접촉률 / 전환율": {
    desc: "접촉률은 개입군(캠페인을 받은 고객) 기준으로만 집계합니다. 비개입군을 포함하면 수치가 왜곡됩니다. 전환율은 담당자가 화면에서 직접 입력한 값입니다.",
  },
  "담당자별 처리 현황": {
    desc: "팀원별 배정·접촉률·전환율을 비교합니다.",
  },
  "방어한 매출": {
    desc: "비개입군의 자연 전환을 제외하고, 캠페인 덕분에 순수하게 늘어난 매출입니다. 개입군과 대조군의 전환·유지 차이를 매출로 환산해 계산합니다.",
  },
  "ROI": {
    desc: "캠페인에 쓴 비용 대비 추가로 얻은 매출(방어한 매출)의 비율입니다. 100%보다 크면 비용보다 많은 추가 매출을 만들었다는 뜻입니다.",
  },
  "군집별 증분 유지효과": {
    desc: "군집별로 캠페인 개입군과 대조군의 유지율 차이를 비교합니다. 어떤 고객 유형에 캠페인이 더 잘 먹히는지 확인해 다음 캠페인의 타겟팅 예산을 배분하는 근거로 씁니다.",
  },
  "캠페인 상태 퍼널": {
    desc: "등록된 캠페인 대상이 대기 → 담당 배정 → 접촉 완료 → 처리 완료 단계 중 어디에 몰려 있는지 보여줍니다.",
  },
  "고위험 커버리지": {
    desc: "고위험(risk_level=high) 고객 중 캠페인에 등록된 비율입니다. 목표 수준(80%) 미달 시 신규 캠페인 등록 대상 확대가 필요합니다.",
  },
  "위험도별 방어매출 · ROI": {
    desc: "고객의 위험도(risk_level: 높음/주의/낮음)별로 방어매출과 ROI를 비교합니다. 어느 위험군에 캠페인 예산을 더 쓸지 판단하는 근거입니다.",
  },
};

const GuideContext = createContext<(key: string | null) => void>(() => {});

function InfoBtn({ guideKey }: { guideKey: string }) {
  const open = useContext(GuideContext);
  if (!GUIDE_CONTENT[guideKey]) {
    return null;
  }
  return (
    <button
      type="button"
      className="department-guide-btn"
      aria-label={`${guideKey} 설명 보기`}
      onClick={(event) => {
        event.stopPropagation();
        open(guideKey);
      }}
    >
      ?
    </button>
  );
}

function GuideDialog({ guideKey, onClose }: { guideKey: string | null; onClose: () => void }) {
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  if (guideKey === null) {
    return null;
  }
  const entry = GUIDE_CONTENT[guideKey];
  if (!entry) {
    return null;
  }
  return (
    <div className="campaign-feedback-help-backdrop">
      <section
        className="campaign-feedback-help-dialog campaign-conflict-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="guide-dialog-title"
      >
        <div className="campaign-feedback-help-dialog__header">
          <div>
            <p className="card-kicker">구현 가이드</p>
            <h3 id="guide-dialog-title">{guideKey}</h3>
          </div>
          <button
            className="campaign-feedback-help-close"
            type="button"
            aria-label="설명 닫기"
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <p className="campaign-conflict-dialog__message">{entry.desc}</p>
        <button className="department-action-button campaign-conflict-dialog__confirm" type="button" onClick={onClose}>
          확인
        </button>
      </section>
    </div>
  );
}

const MARKETING_INSIGHT_PAGE_SIZE = 8;
const OPERATIONS_INSIGHT_PAGE_SIZE = 8;
// 서버가 허용하는 page_size 최대값(100)에 맞춰 이중신호 후보를 2페이지(최대 200명)로 나눠 조회합니다.
const DUAL_SIGNAL_PAGE_SIZE = 100;
const DUAL_SIGNAL_FETCH_PAGES = 2;
const CAMPAIGN_QUEUE_PAGE_SIZE = 8;
// 캠페인 필터 선택지 상한입니다. 서버가 허용하는 page_size 최대값이기도 합니다.
const CAMPAIGN_FILTER_PAGE_SIZE = 100;
const PAGE_GROUP_SIZE = 10;

type DepartmentDashboardPageProps = {
  user: AuthUser;
};

type CampaignDraft = {
  status: CampaignStatus;
  result: string;
  result_code: CampaignResultCode | "";
  assigned_to_user_id: number | null;
  converted: boolean;
  retained: boolean | null;
  retainedDirty: boolean;
  outcome_revenue: string;
};

type MarketingRiskFilter = "" | NonNullable<InsightQuery["risk_level"]>;
type MarketingSortBy = NonNullable<InsightQuery["sort_by"]>;
type MarketingSortOrder = NonNullable<InsightQuery["sort_order"]>;
type CampaignTargetStats = NonNullable<CampaignTargetList["stats"]>;

function formatNumber(value: number): string {
  return new Intl.NumberFormat("ko-KR").format(value);
}

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function formatDecimal(value: number): string {
  return new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 1 }).format(value);
}

const USD_TO_KRW_RATE = 1400;

function formatCurrency(value: number): string {
  return new Intl.NumberFormat("ko-KR", {
    style: "currency",
    currency: "KRW",
    maximumFractionDigits: 0,
  }).format(value);
}

// Total_Trans_Amt는 원본 Kaggle 데이터셋 기준 달러(USD) 값이라 원화 환산이 필요합니다.
function formatUsdAsKrw(value: number): string {
  return formatCurrency(value * USD_TO_KRW_RATE);
}

function formatSignedPercent(value: number | null): string {
  if (value === null) {
    return "—";
  }
  return `${Math.round(value * 100)}%`;
}

function formatDate(value: string | null): string {
  if (value === null) {
    return "-";
  }
  return new Intl.DateTimeFormat("ko-KR", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function campaignQueueErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : "";
  const translations: Record<string, string> = {
    "Retention cannot be recorded before retention_window_days has elapsed.": "처리 완료와 전환은 저장할 수 있지만, 유지 결과는 유지 관측 기간(기본 30일)이 지난 후에 입력할 수 있습니다. 유지 여부를 '유지 미관측'으로 두고 먼저 저장한 뒤, 30일이 지나면 유지 또는 미유지를 입력해 주세요.",
    "A treatment target must be completed before retention is recorded.": "유지 결과를 입력하려면 먼저 대상을 처리 완료 상태로 저장해야 합니다.",
    "Retention cannot be recorded before the observation period starts.": "유지 관측 시작일이 아직 도래하지 않아 유지 결과를 입력할 수 없습니다.",
    "A treatment result code requires a completed target.": "전환·미전환과 같은 최종 결과 코드는 대상을 처리 완료 상태로 저장한 후 입력할 수 있습니다.",
    "A completed treatment target requires a final structured result code.": "처리 완료로 저장하려면 전환, 미전환, 응답 없음, 거절, 수신 거부 또는 연락처 오류 중 하나를 선택해야 합니다.",
    "Outcome revenue can only be recorded for a converted target.": "성과 매출은 전환으로 처리된 고객에게만 입력할 수 있습니다.",
  };
  return translations[message] ?? (message || "캠페인 처리 결과를 저장하지 못했습니다. 입력값을 확인한 후 다시 시도해 주세요.");
}

function DepartmentRiskBadge({ risk }: { risk: CustomerInsight["risk_level"] }) {
  return (
    <span className={`risk-badge risk-badge--${risk}`}>
      <span aria-hidden="true" />
      {riskLabels[risk]}
    </span>
  );
}

function StatCard({ label, value, caption, tone = "purple", guideKey }: {
  label: string;
  value: string;
  caption: string;
  tone?: "purple" | "orange" | "green" | "pink" | "gold";
  guideKey?: string;
}) {
  return (
    <article className={`department-stat department-stat--${tone}`}>
      <span>{label}{guideKey && <InfoBtn guideKey={guideKey} />}</span>
      <strong>{value}</strong>
      <small>{caption}</small>
    </article>
  );
}

function SectionHeader({ children }: { children: ReactNode }) {
  return (
    <div className="department-section-header">
      <span className="department-section-header__bar" aria-hidden="true" />
      <span className="department-section-header__label">{children}</span>
      <span className="department-section-header__line" aria-hidden="true" />
    </div>
  );
}

const OPERATIONS_TOC = [
  { id: "operations-verdict", label: "핵심 결론" },
  { id: "operations-priority", label: "우선 관리 고객" },
  { id: "operations-queue", label: "캠페인 처리 현황" },
];

function OperationsTopNav() {
  const [activeId, setActiveId] = useState(OPERATIONS_TOC[0].id);

  useEffect(() => {
    const sections = OPERATIONS_TOC
      .map((item) => document.getElementById(item.id))
      .filter((el): el is HTMLElement => el !== null);
    if (sections.length === 0) return;
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) setActiveId(entry.target.id);
        });
      },
      { rootMargin: "-20% 0px -70% 0px" },
    );
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, []);

  return (
    <nav className="department-toc">
      {OPERATIONS_TOC.map((item, index) => (
        <a
          key={item.id}
          href={`#${item.id}`}
          className={item.id === activeId ? "is-active" : undefined}
          onClick={(event) => {
            event.preventDefault();
            document.getElementById(item.id)?.scrollIntoView({ behavior: "smooth" });
          }}
        >
          <span className="department-toc__n">{index + 1}</span>
          {item.label}
        </a>
      ))}
    </nav>
  );
}

function MarketingRoiPanel({ performance }: { performance: CampaignPerformance | null }) {
  if (performance === null) {
    return null;
  }
  const metrics = performance.summary;
  const netResult = metrics.incremental_revenue - metrics.total_cost;
  const isLoss = netResult < 0;
  return (
    <section className="department-panel department-panel--sidebar" aria-label="캠페인 방어 매출 요약">
      <div className="department-panel__heading-with-guide">
        <p className="card-kicker">근거 — 방어매출 · ROI</p>
        <InfoBtn guideKey="방어한 매출" />
      </div>
      <div className="department-sidebar-metrics">
        <div>
          <p>방어매출</p>
          <strong>{formatCurrency(metrics.incremental_revenue)}</strong>
        </div>
        <div>
          <p>ROI</p>
          <strong>{formatSignedPercent(metrics.roi)}</strong>
        </div>
        <div>
          <p>증분 전환효과</p>
          <strong>{formatSignedPercent(metrics.incremental_conversion_effect)}</strong>
        </div>
        <div>
          <p>증분 유지효과</p>
          <strong>{formatSignedPercent(metrics.incremental_retention_effect)}</strong>
        </div>
      </div>
      <p className="department-panel__caption">
        {isLoss ? "손실비용" : "순이익"} {formatCurrency(Math.abs(netResult))} · 비개입군의 자연 전환을 제외한 순수 증분입니다.
      </p>
    </section>
  );
}

function findWeakestRiskLevel(
  performance: CampaignPerformance | null,
): CampaignPerformance["by_risk_level"][number] | null {
  if (performance === null || performance.by_risk_level.length === 0) {
    return null;
  }
  return performance.by_risk_level.reduce((min, item) =>
    (item.roi ?? Infinity) < (min.roi ?? Infinity) ? item : min
  );
}

type AdminVerdict = {
  severity: "danger" | "warn" | "good";
  headline: string;
  body: string;
  action: string;
};

const COVERAGE_TARGET = 0.8;

function buildAdminVerdict(
  coverage: HighRiskCoverage | null,
  performance: CampaignPerformance | null,
): AdminVerdict | null {
  if (coverage === null || coverage.coverage_rate === null) {
    return null;
  }
  const percent = Math.round(coverage.coverage_rate * 100);
  const uncovered = coverage.total_high_risk - coverage.enrolled_high_risk;
  const weakest = findWeakestRiskLevel(performance);
  const weakestClause = weakest === null
    ? ""
    : weakest.roi === null
      ? `\n${weakest.label} 세그먼트는 아직 비용 집행이 없어 ROI를 계산할 수 없습니다.`
      : `\n동시에 ${weakest.label} 세그먼트는 ROI ${formatSignedPercent(weakest.roi)}로 위험도별 비교 중 가장 낮아, 예산 재배분을 검토할 여지가 있습니다.`;

  if (coverage.coverage_rate >= COVERAGE_TARGET) {
    return {
      severity: "good",
      headline: `고위험 커버리지 ${percent}% — 목표 수준을 충족하고 있습니다`,
      body: `고위험 고객 등록은 목표(${Math.round(COVERAGE_TARGET * 100)}%) 수준입니다.${weakestClause}`,
      action: weakest === null
        ? "→ 현재 운영 체계를 유지하세요."
        : `→ 현재 운영 체계 유지 · ${weakest.label} 세그먼트 예산 배분 재검토`,
    };
  }
  const severity = coverage.coverage_rate < 0.5 ? "danger" : "warn";
  const gapWord = severity === "danger" ? "크게 부족합니다" : "다소 부족합니다";
  return {
    severity,
    headline: `고위험 커버리지 ${percent}% — 목표(${Math.round(COVERAGE_TARGET * 100)}%) 대비 ${gapWord}`,
    body: `고위험 고객 ${formatNumber(coverage.total_high_risk)}명 중 ${formatNumber(uncovered)}명이 아직 캠페인 대상에 등록되지 않았습니다.${weakestClause}`,
    action: weakest === null
      ? `→ 미등록 고위험 ${formatNumber(uncovered)}명 캠페인 등록 확대`
      : `→ 미등록 고위험 ${formatNumber(uncovered)}명 캠페인 등록 확대 · ${weakest.label} 세그먼트 예산 재검토`,
  };
}

const VERDICT_SEVERITY_LABEL: Record<AdminVerdict["severity"], string> = {
  danger: "조치 필요",
  warn: "주의 필요",
  good: "양호",
};

const RISK_TERM_PATTERN = /(고위험|저위험|주의\(중위험\)|중위험|\d+(?:\.\d+)?%)/g;

function highlightRiskTerms(text: string): ReactNode[] {
  return text.split(RISK_TERM_PATTERN).map((part, index) => (
    RISK_TERM_PATTERN.test(part) && part !== ""
      ? <span key={index} style={{ color: "#dc2626" }}>{part}</span>
      : part
  ));
}

function VerdictHero({
  verdict,
  emphasize = false,
  labelPill = false,
  highlightHeadline = false,
  anchor,
}: {
  verdict: AdminVerdict | null;
  emphasize?: boolean;
  labelPill?: boolean;
  highlightHeadline?: boolean;
  anchor?: ReactNode;
}) {
  const shouldHighlight = emphasize || highlightHeadline;
  const labelClassName = emphasize
    ? "department-verdict__severity"
    : labelPill
    ? "department-verdict__label department-verdict__label--pill"
    : "department-verdict__label";
  const body = (
    <div className={anchor ? "department-verdict__body" : undefined}>
      <div className="department-verdict__eyebrow">
        {verdict !== null && (
          <span className="department-verdict__severity">
            <i aria-hidden="true" />
            {VERDICT_SEVERITY_LABEL[verdict.severity]}
          </span>
        )}
        <span className={labelClassName}>핵심 결론</span>
        {emphasize && verdict !== null && (
          <span className="department-verdict__label" style={{ marginLeft: 8 }}>CRITICAL DIRECTIVE</span>
        )}
      </div>
      {verdict === null ? (
        <p className="department-verdict__loading">데이터를 불러오는 중입니다.</p>
      ) : (
        <>
          <h2>{shouldHighlight ? highlightRiskTerms(verdict.headline) : verdict.headline}</h2>
          <p style={{ whiteSpace: "pre-line" }}>{verdict.body}</p>
          {!emphasize && <div className="department-verdict__action">{verdict.action}</div>}
        </>
      )}
    </div>
  );
  return (
    <section className={`department-verdict department-verdict--${verdict === null ? "loading" : verdict.severity}`} aria-label="핵심 결론">
      {body}
      {anchor}
    </section>
  );
}

function AdminVerdictHero({
  coverage,
  performance,
}: {
  coverage: HighRiskCoverage | null;
  performance: CampaignPerformance | null;
}) {
  return (
    <VerdictHero
      verdict={buildAdminVerdict(coverage, performance)}
      emphasize
      anchor={
        <div className="department-verdict__anchor">
          <CoverageGauge rate={coverage === null ? null : coverage.coverage_rate} valueColor="#1e293b" />
          <span className="department-verdict__anchor-target">목표 {Math.round(COVERAGE_TARGET * 100)}% 대비</span>
        </div>
      }
    />
  );
}

function buildOperationsVerdict(
  dualSignal: DualSignalSummary | null,
  pendingCount: number,
): AdminVerdict | null {
  if (dualSignal === null) {
    return null;
  }
  if (dualSignal.count === 0) {
    return {
      severity: "good",
      headline: "이중신호 해당 고객이 없습니다",
      body: `고위험(risk_level) + 활동성 갭 하위 20%에 동시 해당하는 고객이 현재 없습니다. 미처리 대기열은 ${formatNumber(pendingCount)}건입니다.`,
      action: `→ 대기열 ${formatNumber(pendingCount)}건 순차 처리`,
    };
  }
  return {
    severity: "danger",
    headline: `이중신호 고위험 고객 ${formatNumber(dualSignal.count)}명 — 즉시 관리가 필요합니다`,
    body: `고위험(risk_level) 판정과 활동성 갭 하위 20%에 동시에 해당하는 ${formatNumber(dualSignal.count)}명은 두 모델이 함께 위험 신호를 보내는 최우선 관리 대상입니다.\n미처리 대기열 처리도 함께 서둘러야 합니다.`,
    action: `→ 이중신호 고객 우선 배정 · 미처리 대기열 처리 가속화`,
  };
}

function OperationsVerdictHero({
  dualSignal,
  pendingCount,
}: {
  dualSignal: DualSignalSummary | null;
  pendingCount: number;
}) {
  return (
    <VerdictHero
      verdict={buildOperationsVerdict(dualSignal, pendingCount)}
      labelPill
      highlightHeadline
    />
  );
}

function findClusterExtremes(
  performance: CampaignPerformance | null,
): { best: CampaignPerformance["by_cluster"][number]; worst: CampaignPerformance["by_cluster"][number] } | null {
  if (performance === null) {
    return null;
  }
  const withRoi = performance.by_cluster.filter((item) => item.roi !== null);
  if (withRoi.length === 0) {
    return null;
  }
  const best = withRoi.reduce((max, item) => (item.roi! > max.roi! ? item : max));
  const worst = withRoi.reduce((min, item) => (item.roi! < min.roi! ? item : min));
  return best.key === worst.key ? null : { best, worst };
}

function buildMarketingVerdict(performance: CampaignPerformance | null): AdminVerdict | null {
  if (performance === null) {
    return null;
  }
  const { roi, incremental_revenue: incrementalRevenue } = performance.summary;
  const extremes = findClusterExtremes(performance);
  const clusterClause = extremes === null
    ? ""
    : `\n군집별로는 "${extremes.best.label}" 그룹이 ROI ${formatSignedPercent(extremes.best.roi)}로 가장 효율이 높고, "${extremes.worst.label}" 그룹은 ${formatSignedPercent(extremes.worst.roi)}로 상대적으로 낮습니다.`;

  if (roi === null) {
    return {
      severity: "warn",
      headline: "아직 ROI를 계산할 수 있는 캠페인 실적이 없습니다",
      body: "캠페인 비용·전환 데이터가 쌓이면 방어매출과 ROI가 표시됩니다.",
      action: "→ 캠페인 등록 및 처리 현황을 확인하세요.",
    };
  }
  if (roi < 0) {
    return {
      severity: "danger",
      headline: `캠페인 ROI ${formatSignedPercent(roi)} — 비용 대비 방어매출이 부족합니다`,
      body: `대조군 대비 증분매출이 ${formatCurrency(incrementalRevenue)}로, 캠페인 비용을 회수하지 못하고 있습니다.${clusterClause}`,
      action: extremes === null
        ? "→ 캠페인 타겟팅과 비용 구조를 재검토하세요."
        : `→ "${extremes.worst.label}" 그룹 캠페인 재검토 · "${extremes.best.label}" 그룹 위주로 재배분`,
    };
  }
  return {
    severity: "good",
    headline: `이번 캠페인으로 ${formatCurrency(incrementalRevenue)}의 매출을 방어했습니다 (ROI ${formatSignedPercent(roi)})`,
    body: `대조군 대비 순수하게 늘어난 매출이 ${formatCurrency(incrementalRevenue)}, 캠페인 비용 대비 회수율은 ${formatSignedPercent(roi)}입니다.${clusterClause}`,
    action: extremes === null
      ? "→ 현재 캠페인 운영을 유지하세요."
      : `→ 다음 캠페인 예산은 "${extremes.best.label}" 그룹에 우선 배분 검토`,
  };
}

function MarketingVerdictHero({ performance }: { performance: CampaignPerformance | null }) {
  return (
    <VerdictHero
      verdict={buildMarketingVerdict(performance)}
      labelPill
      highlightHeadline
    />
  );
}

function ReasonCodePanel({ data }: { data: ReasonCodeDistribution | null }) {
  if (data === null) {
    return <p className="department-empty">사유코드 데이터가 없습니다.</p>;
  }
  const entries = Object.entries(data.counts).sort(([, a], [, b]) => b - a).slice(0, 4);
  const maxCount = Math.max(...entries.map(([, count]) => count), 1);
  return (
    <>
      <div className="reason-code-bars">
        {entries.map(([code, count]) => (
          <div className="reason-code-bars__row" key={code}>
            <div className="reason-code-bars__head">
              <span>{getReasonCodeLabel(code)}</span>
              <strong>{formatNumber(count)}명 · {formatPercent(count / data.total_customers)}</strong>
            </div>
            <div className="reason-code-bars__track">
              <span style={{ width: `${(count / maxCount) * 100}%` }} />
            </div>
          </div>
        ))}
      </div>
      <p className="department-panel__caption">고위험 {formatNumber(data.total_customers)}명 기준 · 한 고객이 여러 사유에 동시 해당 가능 · 상담 전 참고용</p>
    </>
  );
}

function CoverageGauge({ rate, valueColor }: { rate: number | null; valueColor?: string }) {
  const percent = rate === null ? 0 : Math.round(rate * 100);
  const size = 110;
  const strokeWidth = 16;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const filled = (percent / 100) * circumference;
  const color = rate === null ? "#9CA3AF" : "#1d4ed8";
  return (
    <div className="department-coverage-gauge">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="#e5e5ea" strokeWidth={strokeWidth} />
        {rate !== null && (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeDasharray={`${filled} ${circumference}`}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          />
        )}
      </svg>
      <span className="department-coverage-gauge__value" style={valueColor ? { color: valueColor } : undefined}>
        {rate === null ? "—" : `${percent}%`}
      </span>
    </div>
  );
}

const RISK_LEVEL_ORDER = ["high", "medium", "low"] as const;

function formatCompactCurrency(value: number): string {
  return `₩${((value * USD_TO_KRW_RATE) / 1_000_000).toFixed(2)}M`;
}

function RiskLevelBarChart({ items }: { items: CampaignPerformance["by_risk_level"] }) {
  if (items.length === 0) {
    return <p className="department-empty">위험도별 데이터가 없습니다.</p>;
  }
  const sorted = [...items].sort(
    (a, b) => RISK_LEVEL_ORDER.indexOf(a.key as typeof RISK_LEVEL_ORDER[number]) - RISK_LEVEL_ORDER.indexOf(b.key as typeof RISK_LEVEL_ORDER[number]),
  );
  const W = 320;
  const H = 160;
  const PAD = { top: 16, right: 16, bottom: 40, left: 16 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const n = sorted.length;
  const slot = plotW / n;
  const barWidth = Math.min(40, slot * 0.35);
  const maxRevenue = Math.max(...sorted.map((item) => item.incremental_revenue), 1);
  const baselineY = PAD.top + plotH;
  const xOf = (index: number) => PAD.left + slot * index + slot / 2;

  return (
    <div className="department-combo-chart">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label="위험도별 방어매출 막대차트">
        <line x1={PAD.left} x2={W - PAD.right} y1={baselineY} y2={baselineY} stroke="#e5e5ea" strokeWidth={1} />
        {sorted.map((item, index) => {
          const x = xOf(index);
          const barHeight = (item.incremental_revenue / maxRevenue) * plotH;
          const topY = baselineY - barHeight;
          return (
            <g key={item.key}>
              <rect x={x - barWidth / 2} y={topY} width={barWidth} height={barHeight} rx={3} fill="#8b95a1" />
              <text x={x} y={topY - 6} textAnchor="middle" fontSize={10} fontWeight={700} fill="#2c2c2e">
                {formatCompactCurrency(item.incremental_revenue)}
              </text>
              <text x={x} y={baselineY + 15} textAnchor="middle" fontSize={11} fontWeight={700} fill="#2c2c2e">{item.label}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function RiskLevelLineChart({ items }: { items: CampaignPerformance["by_risk_level"] }) {
  if (items.length === 0) {
    return <p className="department-empty">위험도별 데이터가 없습니다.</p>;
  }
  const sorted = [...items].sort(
    (a, b) => RISK_LEVEL_ORDER.indexOf(a.key as typeof RISK_LEVEL_ORDER[number]) - RISK_LEVEL_ORDER.indexOf(b.key as typeof RISK_LEVEL_ORDER[number]),
  );
  const W = 320;
  const H = 160;
  const PAD = { top: 16, right: 16, bottom: 40, left: 16 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const n = sorted.length;
  const slot = plotW / n;
  const maxRoi = Math.max(...sorted.map((item) => item.roi ?? 0), 0.1);
  const baselineY = PAD.top + plotH;
  const xOf = (index: number) => PAD.left + slot * index + slot / 2;
  const yOf = (roi: number) => baselineY - (Math.max(roi, 0) / maxRoi) * plotH;
  const linePoints = sorted.map((item, index) => `${xOf(index)},${yOf(item.roi ?? 0)}`).join(" ");

  return (
    <div className="department-combo-chart">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label="위험도별 ROI 선그래프">
        <line x1={PAD.left} x2={W - PAD.right} y1={baselineY} y2={baselineY} stroke="#e5e5ea" strokeWidth={1} />
        <polyline points={linePoints} fill="none" stroke="#1d4ed8" strokeWidth={2} strokeLinejoin="round" />
        {sorted.map((item, index) => {
          const roi = item.roi ?? 0;
          const y = yOf(roi);
          const isLocalMin = index > 0 && index < sorted.length - 1
            && roi < (sorted[index - 1].roi ?? 0)
            && roi < (sorted[index + 1].roi ?? 0);
          const labelY = isLocalMin ? y + 20 : y - 8;
          return (
            <g key={item.key}>
              <circle cx={xOf(index)} cy={y} r={4} fill="#1d4ed8" />
              <text x={xOf(index)} y={labelY} textAnchor="middle" fontSize={11} fontWeight={700} fill="#1d4ed8">
                {item.roi === null ? "—" : formatSignedPercent(item.roi)}
              </text>
              <text x={xOf(index)} y={baselineY + 15} textAnchor="middle" fontSize={11} fontWeight={700} fill="#2c2c2e">{item.label}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function AdminDecisionPanel({ performance }: { performance: CampaignPerformance | null }) {
  return (
    <div className="department-hero-grid" aria-label="위험도별 방어매출 및 ROI">
      <div className="department-panel">
        <div className="department-panel__heading-with-guide">
          <p className="card-kicker">위험도별 방어매출</p>
          <InfoBtn guideKey="위험도별 방어매출 · ROI" />
        </div>
        <RiskLevelBarChart items={performance === null ? [] : performance.by_risk_level} />
      </div>
      <div className="department-panel">
        <div className="department-panel__heading-with-guide">
          <p className="card-kicker">위험도별 ROI</p>
          <InfoBtn guideKey="위험도별 방어매출 · ROI" />
        </div>
        <RiskLevelLineChart items={performance === null ? [] : performance.by_risk_level} />
      </div>
    </div>
  );
}

function ClusterUpliftPanel({
  performance,
  compact = false,
}: {
  performance: CampaignPerformance | null;
  compact?: boolean;
}) {
  if (performance === null || performance.by_cluster.length === 0) {
    return null;
  }
  const extremes = findClusterExtremes(performance);
  if (compact) {
    return (
      <section className="department-panel department-panel--sidebar" aria-label="군집별 증분 유지효과">
        <div className="department-panel__heading-with-guide">
          <p className="card-kicker">근거 — 군집별 증분 효과</p>
          <InfoBtn guideKey="군집별 증분 유지효과" />
        </div>
        <div className="campaign-performance-table-wrap">
          <table className="campaign-performance-table campaign-performance-table--sidebar">
            <thead>
              <tr>
                <th scope="col">군집</th>
                <th scope="col">증분유지</th>
                <th scope="col">ROI</th>
              </tr>
            </thead>
            <tbody>
              {performance.by_cluster.map((item) => (
                <tr key={item.key} className={extremes !== null && item.key === extremes.best.key ? "campaign-performance-row--best" : undefined}>
                  <th scope="row">{item.label}</th>
                  <td>{formatSignedPercent(item.incremental_retention_effect)}</td>
                  <td>{formatSignedPercent(item.roi)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="department-panel__caption">
          어떤 고객 유형에 캠페인이 더 잘 먹히는지 확인해 다음 예산 배분의 근거로 씁니다.
        </p>
      </section>
    );
  }
  return (
    <section className="department-panel department-panel--wide" aria-label="군집별 증분 유지효과">
      <div className="department-panel__heading">
        <div>
          <p className="card-kicker">CLUSTER UPLIFT</p>
          <h2>군집별 증분 유지·전환 효과 <InfoBtn guideKey="군집별 증분 유지효과" /></h2>
        </div>
        <span className="table-count">{formatNumber(performance.by_cluster.length)}개 군집</span>
      </div>
      <div className="campaign-performance-table-wrap">
        <table className="campaign-performance-table">
          <thead>
            <tr>
              <th scope="col">군집</th>
              <th scope="col">대상군 유지율</th>
              <th scope="col">대조군 유지율</th>
              <th scope="col">증분 유지효과</th>
              <th scope="col">방어매출</th>
              <th scope="col">ROI</th>
            </tr>
          </thead>
          <tbody>
            {performance.by_cluster.map((item) => (
              <tr key={item.key}>
                <th scope="row">{item.label}</th>
                <td>{formatSignedPercent(item.treatment_retention_rate)}</td>
                <td>{formatSignedPercent(item.control_retention_rate)}</td>
                <td>{formatSignedPercent(item.incremental_retention_effect)}</td>
                <td>{formatCurrency(item.incremental_revenue)}</td>
                <td>{formatSignedPercent(item.roi)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="department-panel__caption">
        어떤 고객 유형에 캠페인이 더 잘 먹히는지 확인해, 다음 캠페인 타겟팅 예산을 배분하는 근거로 활용합니다.
      </p>
    </section>
  );
}

function DualSignalHero({
  dualSignal,
  onClick,
  active,
}: {
  dualSignal: DualSignalSummary | null;
  onClick?: () => void;
  active?: boolean;
}) {
  const Wrapper = onClick ? "button" : "section";
  return (
    <Wrapper
      type={onClick ? "button" : undefined}
      className={`department-hero-metric department-hero-metric--danger${onClick ? " department-hero-metric--clickable" : ""}${active ? " is-active" : ""}`}
      aria-label="이중 신호 고위험 고객"
      onClick={onClick}
    >
      <div className="department-hero-metric__body">
        <div className="department-panel__heading-with-guide">
          <span className="department-hero-metric__badge">우선순위</span>
          <p className="card-kicker">이중 신호 고위험 고객</p>
          <InfoBtn guideKey="이중 신호 고객" />
        </div>
        <strong>{dualSignal === null ? "—" : `${formatNumber(dualSignal.count)}명`}</strong>
        <small>고위험(risk_level) + 활동성 갭 하위 20% 동시 해당</small>
      </div>
      {onClick && <span className="department-hero-metric__cta">우선 관리 고객 목록에서 확인 →</span>}
    </Wrapper>
  );
}

function OperationsInsightDetail({ insight }: { insight: CustomerInsight | null }) {
  if (insight === null) {
    return (
      <section className="department-panel">
        <p className="card-kicker">선택 고객 상세</p>
        <p className="department-empty">위 목록에서 고객을 클릭하면 상세 정보가 표시됩니다.</p>
      </section>
    );
  }
  const reasonCodes = Array.isArray(insight.reason_codes) ? insight.reason_codes : [];
  return (
    <section className="department-panel" aria-label="선택 고객 상세">
      <p className="card-kicker">선택 고객 상세</p>
      <h2>
        {insight.customer_id} 상세{" "}
        <span className="department-insight-detail__hint">— 위 리스트에서 다른 고객을 클릭해 전환해보세요</span>
      </h2>
      <div className="department-insight-detail__head">
        <div className="department-insight-detail__id">
          <strong>{insight.customer_id}</strong>
          <DepartmentRiskBadge risk={insight.risk_level} />
        </div>
        <div className="department-insight-detail__metrics">
          <div>
            <p>이탈확률</p>
            <strong>{formatPercent(insight.churn_probability)}</strong>
          </div>
          <div>
            <p>활동성 갭</p>
            <strong>{insight.activity_gap > 0 ? "+" : ""}{formatDecimal(insight.activity_gap)}</strong>
          </div>
          <div>
            <p>총 거래액</p>
            <strong>{formatUsdAsKrw(insight.total_trans_amt)}</strong>
          </div>
        </div>
      </div>
      <div className="department-insight-detail__cols">
        <div>
          <p className="department-insight-detail__title">이탈 위험 신호</p>
          {reasonCodes.length === 0 ? (
            <p className="department-empty">감지된 위험 신호 없음</p>
          ) : (
            <ul>
              {reasonCodes.map((code) => (
                <li key={code}>{getReasonCodeLabel(code)}</li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <p className="department-insight-detail__title">추천 방어 전략</p>
          <p className="department-insight-detail__action">{insight.recommended_action}</p>
        </div>
      </div>
      <div className="department-quick-actions">
        <button
          type="button"
          className="department-quick-actions__btn"
          onClick={() => document.getElementById("operations-queue")?.scrollIntoView({ behavior: "smooth" })}
        >
          ✓ 처리 완료 표시
        </button>
      </div>
    </section>
  );
}

function DetailAccordionRow({
  title, source, guideKey, isOpen, onToggle, children,
}: {
  title: string; source: string; guideKey?: string; isOpen: boolean; onToggle: () => void; children: ReactNode;
}) {
  return (
    <div className="department-accordion-row">
      <button type="button" className="department-accordion-row__header" onClick={onToggle}>
        <span className="department-accordion-row__title">
          <i className={`department-accordion-row__chevron${isOpen ? " is-open" : ""}`} aria-hidden="true" />
          {title}
          {guideKey && <InfoBtn guideKey={guideKey} />}
        </span>
        <span className="department-accordion-row__source">{source}</span>
      </button>
      {isOpen && <div className="department-accordion-row__panel">{children}</div>}
    </div>
  );
}

function MarketingCandidateFilters({
  riskLevel,
  clusterName,
  sortBy,
  sortOrder,
  clusterOptions,
  onRiskLevelChange,
  onClusterNameChange,
  onSortByChange,
  onSortOrderChange,
  onReset,
}: {
  riskLevel: MarketingRiskFilter;
  clusterName: string;
  sortBy: MarketingSortBy;
  sortOrder: MarketingSortOrder;
  clusterOptions: Record<string, number>;
  onRiskLevelChange: (value: MarketingRiskFilter) => void;
  onClusterNameChange: (value: string) => void;
  onSortByChange: (value: MarketingSortBy) => void;
  onSortOrderChange: (value: MarketingSortOrder) => void;
  onReset: () => void;
}) {
  const sortedClusterOptions = Object.entries(clusterOptions).sort(
    ([firstName, firstCount], [secondName, secondCount]) => secondCount - firstCount
      || firstName.localeCompare(secondName),
  );

  return (
    <>
      <div className="filter-bar">
        <label className="filter-bar__field">
          <span>위험도</span>
          <select
            aria-label="캠페인 후보 위험도"
            value={riskLevel}
            onChange={(event) => onRiskLevelChange(event.target.value as MarketingRiskFilter)}
          >
            <option value="">전체 위험도</option>
            <option value="high">높음</option>
            <option value="medium">주의</option>
            <option value="low">낮음</option>
          </select>
        </label>
        <label className="filter-bar__field filter-bar__field--cluster">
          <span>군집</span>
          <select
            aria-label="캠페인 후보 군집"
            value={clusterName}
            onChange={(event) => onClusterNameChange(event.target.value)}
          >
            <option value="">전체 군집</option>
            {sortedClusterOptions.map(([name, count]) => (
              <option key={name} value={name}>
                {name} ({formatNumber(count)}명)
              </option>
            ))}
          </select>
        </label>
        <label className="filter-bar__field">
          <span>정렬 기준</span>
          <select
            aria-label="캠페인 후보 정렬 기준"
            value={sortBy}
            onChange={(event) => onSortByChange(event.target.value as MarketingSortBy)}
          >
            <option value="churn_probability">이탈 확률</option>
            <option value="activity_gap">활동성 갭</option>
            <option value="expected_transaction_count">예상 거래 건수</option>
            <option value="scored_at">최근 분석 시각</option>
          </select>
        </label>
        <label className="filter-bar__field">
          <span>정렬 순서</span>
          <select
            aria-label="캠페인 후보 정렬 순서"
            value={sortOrder}
            onChange={(event) => onSortOrderChange(event.target.value as MarketingSortOrder)}
          >
            <option value="desc">높은 값부터</option>
            <option value="asc">낮은 값부터</option>
          </select>
        </label>
        <span className="filter-bar__spacer" aria-hidden="true" />
        <button className="filter-bar__reset" type="button" onClick={onReset}>초기화</button>
      </div>
      <p className="department-panel__caption">
        분석 결과를 기준으로 후보를 좁힌 뒤, 정렬된 고객부터 캠페인에 등록할 수 있습니다.
      </p>
    </>
  );
}

function CampaignConflictDialog({
  message,
  onClose,
}: {
  message: string;
  onClose: () => void;
}) {
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return (
    <div className="campaign-feedback-help-backdrop">
      <section
        className="campaign-feedback-help-dialog campaign-conflict-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="campaign-conflict-title"
      >
        <div className="campaign-feedback-help-dialog__header">
          <div>
            <p className="card-kicker">CAMPAIGN GUARD</p>
            <h3 id="campaign-conflict-title">캠페인 등록 불가</h3>
          </div>
          <button
            className="campaign-feedback-help-close"
            type="button"
            aria-label="캠페인 등록 안내 닫기"
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <p className="campaign-conflict-dialog__message">{message}</p>
        <p className="campaign-conflict-dialog__message">
          중복 접촉을 막기 위해 이미 처리 중인 캠페인, 최근 접촉 고객, 수신 거부 고객은 후보 목록에서 자동으로 제외됩니다.
        </p>
        <button
          className="department-action-button campaign-conflict-dialog__confirm"
          type="button"
          onClick={onClose}
        >
          확인
        </button>
      </section>
    </div>
  );
}

function CampaignQueueFeedbackDialog({
  message,
  onClose,
  variant,
}: {
  message: string;
  onClose: () => void;
  variant: "error" | "success";
}) {
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  const title = variant === "success" ? "저장 완료" : "캠페인 처리 저장 안내";

  return (
    <div className="campaign-feedback-help-backdrop">
      <section
        className={`campaign-feedback-help-dialog campaign-conflict-dialog campaign-action-dialog campaign-action-dialog--${variant}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="campaign-queue-feedback-title"
      >
        <div className="campaign-feedback-help-dialog__header">
          <div>
            <p className="card-kicker">{variant === "success" ? "CAMPAIGN SAVED" : "CAMPAIGN UPDATE"}</p>
            <h3 id="campaign-queue-feedback-title">{title}</h3>
          </div>
          <button
            className="campaign-feedback-help-close"
            type="button"
            aria-label={`${title} 닫기`}
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <p className="campaign-conflict-dialog__message">{message}</p>
        <button className="department-action-button campaign-conflict-dialog__confirm" type="button" onClick={onClose}>
          확인
        </button>
      </section>
    </div>
  );
}

function DepartmentPagination({
  label,
  currentStart,
  currentEnd,
  total,
  page,
  totalPages,
  onPageChange,
}: {
  label: string;
  currentStart: number;
  currentEnd: number;
  total: number;
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}) {
  if (totalPages <= 1) {
    return null;
  }
  const groupStart = Math.floor((page - 1) / PAGE_GROUP_SIZE) * PAGE_GROUP_SIZE + 1;
  const groupEnd = Math.min(groupStart + PAGE_GROUP_SIZE - 1, totalPages);
  const pages = Array.from({ length: groupEnd - groupStart + 1 }, (_, index) => groupStart + index);
  return (
    <div className="department-insight-pagination">
      <span>{formatNumber(currentStart)}–{formatNumber(currentEnd)} / {formatNumber(total)}명</span>
      <div className="department-insight-pagination__pages">
        <button
          type="button"
          aria-label={`이전 ${label} 페이지 묶음`}
          disabled={groupStart === 1}
          onClick={() => onPageChange(groupStart - 1)}
        >
          ‹
        </button>
        {pages.map((pageNumber) => (
          <button
            type="button"
            key={pageNumber}
            className={pageNumber === page ? "department-insight-pagination__page department-insight-pagination__page--active" : "department-insight-pagination__page"}
            aria-label={`${label} ${pageNumber}페이지`}
            aria-current={pageNumber === page ? "page" : undefined}
            onClick={() => onPageChange(pageNumber)}
          >
            {pageNumber}
          </button>
        ))}
        <button
          type="button"
          aria-label={`다음 ${label} 페이지 묶음`}
          disabled={groupEnd === totalPages}
          onClick={() => onPageChange(groupEnd + 1)}
        >
          ›
        </button>
      </div>
    </div>
  );
}

function InsightPriorityTable({
  kicker,
  heading,
  toolbar,
  insights,
  targets,
  campaignName,
  onCreate,
  isCreating,
  total,
  page,
  pageSize,
  totalPages,
  onPageChange,
  compact = false,
  allowCustomName = false,
  onSelectInsight,
  selectedInsightId,
}: {
  kicker: string;
  heading: string;
  toolbar?: ReactNode;
  insights: CustomerInsight[];
  targets: CampaignTarget[];
  campaignName: string;
  onCreate?: (insight: CustomerInsight, campaignNameOverride?: string) => void;
  isCreating: number | null;
  total: number;
  page?: number;
  pageSize?: number;
  totalPages?: number;
  onPageChange?: (page: number) => void;
  compact?: boolean;
  allowCustomName?: boolean;
  onSelectInsight?: (insight: CustomerInsight) => void;
  selectedInsightId?: number | null;
}) {
  const [nameDrafts, setNameDrafts] = useState<Record<number, string>>({});
  const targetInsightIds = new Set(targets.map((target) => target.customer_insight_id));
  const currentPage = page ?? 1;
  const currentPageSize = pageSize ?? insights.length;
  const currentStart = total === 0 ? 0 : (currentPage - 1) * currentPageSize + 1;
  const currentEnd = total === 0 ? 0 : Math.min(currentPage * currentPageSize, total);
  const hasPagination = onPageChange !== undefined && totalPages !== undefined && totalPages > 1;
  return (
    <section className="department-panel department-panel--wide">
      <div className="department-panel__heading">
        <div>
          <p className="card-kicker">{kicker}</p>
          <h2>{heading}</h2>
        </div>
        <span className="table-count">{formatNumber(total)}명</span>
      </div>
      {toolbar}
      {insights.length === 0 ? (
        <p className="department-empty">현재 조건에 맞는 고객이 없습니다.</p>
      ) : (
        <div className={`department-insight-list${compact ? " department-insight-list--compact" : ""}`} role="list" aria-label={`${heading} 목록`}>
          <div className="department-insight-list__header" aria-hidden="true">
            <span>고객</span>
            <span>위험도</span>
            <span>이탈 확률</span>
            <span>활동성 갭</span>
            {!compact && <span>예상 거래</span>}
            {compact ? <span>사유코드</span> : <span>군집</span>}
            {!compact && <span>추천 액션</span>}
            {!compact && <span>캠페인</span>}
          </div>
          {insights.map((insight) => {
            const isRegistered = targetInsightIds.has(insight.id);
            const nameDraft = nameDrafts[insight.id] ?? "";
            const isSelected = onSelectInsight !== undefined && selectedInsightId === insight.id;
            return (
              <div
                className={`department-insight-row${onSelectInsight ? " department-insight-row--clickable" : ""}${isSelected ? " is-selected" : ""}`}
                key={insight.id}
                role="listitem"
                onClick={onSelectInsight ? () => onSelectInsight(insight) : undefined}
              >
                <span className="department-insight-row__customer">
                  <strong>{insight.customer_id}</strong>
                  <small>{formatDate(insight.scored_at)}</small>
                </span>
                <span className="department-insight-row__risk">
                  <DepartmentRiskBadge risk={insight.risk_level} />
                </span>
                <span className="department-insight-row__metric">
                  <strong>{formatPercent(insight.churn_probability)}</strong>
                  <small>이탈 확률</small>
                </span>
                <span className={`department-insight-row__gap ${insight.activity_gap < 0 ? "department-gap--negative" : ""}`}>
                  {insight.activity_gap > 0 ? "+" : ""}{formatDecimal(insight.activity_gap)}
                  <small>활동성 갭</small>
                </span>
                {!compact && (
                  <span className="department-insight-row__expected">
                    {formatDecimal(insight.expected_transaction_count)}건
                    <small>예상 거래</small>
                  </span>
                )}
                {compact ? (
                  <span className="department-insight-row__reason">
                    {Array.isArray(insight.reason_codes) && insight.reason_codes.length > 0
                      ? getReasonCodeLabel(insight.reason_codes[0])
                      : "—"}
                  </span>
                ) : (
                  <span className="department-insight-row__cluster">
                    {insight.cluster_name}
                    <small>
                      신뢰도 {insight.cluster_confidence == null ? "-" : formatPercent(insight.cluster_confidence)}
                    </small>
                  </span>
                )}
                {!compact && <span className="department-insight-row__action">{insight.recommended_action}</span>}
                {!compact && (onCreate ? (
                  allowCustomName ? (
                    <span className="department-register-inline">
                      <input
                        type="text"
                        aria-label={`${insight.customer_id} 캠페인명`}
                        placeholder="캠페인명 입력"
                        value={nameDraft}
                        disabled={isRegistered || isCreating === insight.id}
                        onChange={(event) => setNameDrafts((current) => ({ ...current, [insight.id]: event.target.value }))}
                      />
                      <button
                        type="button"
                        className="department-action-button"
                        disabled={isRegistered || isCreating === insight.id}
                        onClick={() => onCreate(insight, nameDraft.trim() || undefined)}
                      >
                        {isRegistered ? "등록됨" : isCreating === insight.id ? "등록 중..." : "등록"}
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="department-action-button"
                      disabled={isRegistered || isCreating === insight.id}
                      onClick={() => onCreate(insight)}
                    >
                      {isRegistered ? "등록됨" : isCreating === insight.id ? "등록 중..." : campaignName}
                    </button>
                  )
                ) : (
                  <span className="department-campaign-result">마케팅팀 등록</span>
                ))}
              </div>
            );
          })}
        </div>
      )}
      {hasPagination && (
        <DepartmentPagination
          label="우선 고객"
          currentStart={currentStart}
          currentEnd={currentEnd}
          total={total}
          page={currentPage}
          totalPages={totalPages ?? 0}
          onPageChange={onPageChange!}
        />
      )}
    </section>
  );
}

function defaultCampaignDraft(target: CampaignTarget): CampaignDraft {
  return {
    status: target.status,
    result: target.result ?? "",
    result_code: target.result_code ?? "",
    assigned_to_user_id: target.assigned_to_user_id,
    converted: target.converted,
    retained: target.retained ?? null,
    retainedDirty: false,
    outcome_revenue: target.outcome_revenue == null ? "" : String(target.outcome_revenue),
  };
}

type TargetEditState = {
  canEditTarget: boolean;
  availableStatuses: CampaignStatus[];
  finalCodeRequired: boolean;
  availableResultCodes: [CampaignResultCode, string][];
  retentionDisabled: boolean;
};

function computeTargetEditState(target: CampaignTarget, draft: CampaignDraft, user: AuthUser, canManage: boolean): TargetEditState {
  const canEditTarget = canManage && (
    user.role === "admin"
    || (
      target.experiment_group === "treatment"
      && (target.assigned_to_user_id === null || target.assigned_to_user_id === user.id)
    )
  );
  const availableStatuses = campaignStatusTransitions[target.status].filter((status) => {
    if (target.experiment_group === "control") {
      return status === "pending" || status === "cancelled";
    }
    if (target.campaign_status !== "active") {
      return !["contacted", "completed"].includes(status);
    }
    return true;
  });
  const finalCodeRequired = draft.status === "completed"
    && !finalCampaignResultCodes.includes(draft.result_code as CampaignResultCode);
  const availableResultCodes = (Object.entries(campaignResultLabels) as [CampaignResultCode, string][]).filter(([code]) => {
    if (target.experiment_group === "control") {
      return code !== "contacted";
    }
    if (code === "contacted") {
      return draft.status === "contacted" || draft.status === "completed";
    }
    return draft.status === "completed";
  });
  const retentionDisabled = target.experiment_group === "treatment" && draft.status !== "completed";
  return { canEditTarget, availableStatuses, finalCodeRequired, availableResultCodes, retentionDisabled };
}

function CampaignTargetEditForm({
  target,
  draft,
  editState,
  assignees,
  saving,
  onDraftChange,
  onSave,
}: {
  target: CampaignTarget;
  draft: CampaignDraft;
  editState: TargetEditState;
  assignees: TeamMember[];
  saving: boolean;
  onDraftChange: (updater: (current: CampaignDraft) => CampaignDraft) => void;
  onSave: () => void;
}) {
  const { availableStatuses, finalCodeRequired, availableResultCodes, retentionDisabled } = editState;
  return (
    <div className="department-campaign-controls">
      <select
        aria-label={`${target.customer_id} 처리 상태`}
        value={draft.status}
        onChange={(event) => onDraftChange((current) => {
          const status = event.target.value as CampaignStatus;
          const isCompleted = status === "completed";
          const isFinalCode = finalCampaignResultCodes.includes(current.result_code as CampaignResultCode);
          return {
            ...current,
            status,
            result_code: !isCompleted && isFinalCode ? "" : current.result_code,
            converted: isCompleted ? current.converted : false,
            retained: retentionDisabled || !isCompleted ? null : current.retained,
            outcome_revenue: isCompleted && current.converted ? current.outcome_revenue : "",
          };
        })}
      >
        {availableStatuses.map((value) => (
          <option value={value} key={value}>
            {campaignStatusLabels[value]}
          </option>
        ))}
      </select>
      <div className="department-campaign-performance">
        <select
          aria-label={`${target.customer_id} 유지 여부`}
          value={draft.retained === null ? "" : String(draft.retained)}
          disabled={retentionDisabled}
          onChange={(event) => onDraftChange((current) => ({
            ...current,
            retained: event.target.value === "" ? null : event.target.value === "true",
            retainedDirty: true,
          }))}
        >
          <option value="">유지 미관측</option>
          <option value="true">유지</option>
          <option value="false">미유지</option>
        </select>
        <input
          type="number"
          min={0}
          step={1000}
          aria-label={`${target.customer_id} 성과 매출`}
          value={draft.outcome_revenue}
          placeholder="성과 매출"
          disabled={!draft.converted}
          onChange={(event) => onDraftChange((current) => ({ ...current, outcome_revenue: event.target.value }))}
        />
      </div>
      <select
        aria-label={`${target.customer_id} 결과 코드`}
        value={draft.result_code}
        onChange={(event) => onDraftChange((current) => ({
          ...current,
          result_code: event.target.value as CampaignResultCode | "",
          converted: event.target.value === "converted",
          outcome_revenue: event.target.value === "converted" ? current.outcome_revenue : "",
        }))}
      >
        <option value="">결과 코드</option>
        {availableResultCodes.map(([code, label]) => <option value={code} key={code}>{label}</option>)}
      </select>
      <select
        aria-label={`${target.customer_id} 담당자`}
        value={draft.assigned_to_user_id === null ? "" : String(draft.assigned_to_user_id)}
        onChange={(event) => onDraftChange((current) => ({
          ...current,
          assigned_to_user_id: event.target.value === "" ? null : Number(event.target.value),
        }))}
      >
        <option value="">담당자 선택</option>
        {assignees.map((assignee) => (
          <option value={assignee.id} key={assignee.id}>
            {assignee.display_name} · {roleLabels[assignee.role]}
          </option>
        ))}
      </select>
      <input
        aria-label={`${target.customer_id} 처리 결과`}
        value={draft.result}
        placeholder="처리 결과"
        onChange={(event) => onDraftChange((current) => ({ ...current, result: event.target.value }))}
      />
      <button type="button" disabled={saving || finalCodeRequired} onClick={onSave}>
        {saving ? "저장 중..." : "저장"}
      </button>
    </div>
  );
}

function CampaignQueue({
  targets,
  total,
  page,
  pageSize,
  totalPages,
  onPageChange,
  canManage,
  assignees,
  user,
  onUpdated,
  campaignFilter,
  campaignOptions,
  onCampaignFilterChange,
  useDrawerEditing = false,
  statusFilter,
  onStatusFilterChange,
}: {
  targets: CampaignTarget[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  canManage: boolean;
  assignees: TeamMember[];
  user: AuthUser;
  onUpdated: (target: CampaignTarget) => void;
  campaignFilter: number | "";
  campaignOptions: Campaign[];
  onCampaignFilterChange: (value: number | "") => void;
  useDrawerEditing?: boolean;
  statusFilter?: CampaignStatus | "";
  onStatusFilterChange?: (value: CampaignStatus | "") => void;
}) {
  const [drafts, setDrafts] = useState<Record<number, CampaignDraft>>({});
  const [savingId, setSavingId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [drawerTargetId, setDrawerTargetId] = useState<number | null>(null);
  const currentStart = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const currentEnd = total === 0 ? 0 : Math.min(page * pageSize, total);
  const hasPagination = totalPages > 1;

  const getDraft = (target: CampaignTarget): CampaignDraft => drafts[target.id] ?? defaultCampaignDraft(target);

  const save = async (target: CampaignTarget) => {
    const draft = getDraft(target);
    setSavingId(target.id);
    setError("");
    setSuccess("");
    try {
      const updated = await updateCampaignTarget(target.id, {
        status: draft.status,
        ...(draft.assigned_to_user_id !== target.assigned_to_user_id
          ? { assigned_to_user_id: draft.assigned_to_user_id }
          : {}),
        result: draft.result || undefined,
        result_code: draft.result_code || undefined,
        converted: draft.converted,
        ...(draft.retainedDirty ? { retained: draft.retained } : {}),
        outcome_revenue: draft.outcome_revenue === "" ? null : Number(draft.outcome_revenue),
      });
      onUpdated(updated);
      setSuccess("캠페인 처리 결과를 저장했습니다.");
      if (useDrawerEditing) {
        setDrawerTargetId(null);
      }
    } catch (requestError) {
      setError(campaignQueueErrorMessage(requestError));
    } finally {
      setSavingId(null);
    }
  };

  const drawerTarget = targets.find((item) => item.id === drawerTargetId) ?? null;

  return (
    <section className="department-panel department-panel--wide">
      <div className="department-panel__heading">
        <div>
          <p className="card-kicker">CAMPAIGN QUEUE</p>
          <h2>캠페인 처리 현황</h2>
        </div>
        <span className="table-count">{formatNumber(total)}건</span>
      </div>
      {onStatusFilterChange && (
        <div className="department-risk-tabs">
          {(["", "pending", "assigned", "contacted", "completed"] as const).map((status) => (
            <button
              key={status || "all"}
              type="button"
              className={`department-risk-tab${(statusFilter ?? "") === status ? " is-active" : ""}`}
              onClick={() => onStatusFilterChange(status)}
            >
              {status === "" ? "전체" : campaignStatusLabels[status]}
            </button>
          ))}
        </div>
      )}
      <div className="insight-filters department-insight-filters">
        <label className="filter-field filter-field--cluster">
          <span>캠페인</span>
          <select
            aria-label="캠페인 처리 현황 캠페인"
            value={campaignFilter === "" ? "" : String(campaignFilter)}
            onChange={(event) => onCampaignFilterChange(
              event.target.value === "" ? "" : Number(event.target.value),
            )}
          >
            <option value="">전체 캠페인</option>
            {campaignOptions.map((campaign) => (
              <option key={campaign.id} value={campaign.id}>
                {campaign.name}
              </option>
            ))}
          </select>
        </label>
        {campaignFilter !== "" && (
          <button className="reset-filter-button" type="button" onClick={() => onCampaignFilterChange("")}>
            초기화
          </button>
        )}
      </div>
      {error !== "" && <CampaignQueueFeedbackDialog message={error} variant="error" onClose={() => setError("")} />}
      {success !== "" && <CampaignQueueFeedbackDialog message={success} variant="success" onClose={() => setSuccess("")} />}
      {targets.length === 0 ? (
        <p className="department-empty">
          {campaignFilter === ""
            ? "등록된 캠페인 대상이 없습니다."
            : "선택한 캠페인에 등록된 대상이 없습니다."}
        </p>
      ) : (
        <div className="department-campaign-list">
          {targets.map((target) => {
            const draft = getDraft(target);
            const editState = computeTargetEditState(target, draft, user, canManage);
            const { canEditTarget } = editState;
            const lifecycleLabel = target.campaign_status ? lifecycleLabels[target.campaign_status] : null;

            if (useDrawerEditing) {
              return (
                <button
                  type="button"
                  key={target.id}
                  className="department-campaign-row department-campaign-row--clickable"
                  onClick={() => canEditTarget && setDrawerTargetId(target.id)}
                  disabled={!canEditTarget}
                >
                  <div>
                    <strong>{target.customer_id}</strong>
                    <small className="department-campaign-row__campaign">
                      {target.campaign_name}
                      {lifecycleLabel && <span className="department-lifecycle-badge">{lifecycleLabel}</span>}
                      <span className="department-campaign-row__date">등록 {formatDate(target.created_at)}</span>
                    </small>
                  </div>
                  <span className={`campaign-status campaign-status--${target.status}`}>
                    {campaignStatusLabels[target.status]}
                  </span>
                  {!canEditTarget && <span className="department-campaign-result">{target.result ?? "결과 대기"}</span>}
                </button>
              );
            }

            return (
              <div className="department-campaign-row" key={target.id}>
                <div>
                  <strong>{target.customer_id}</strong>
                  <small>{target.campaign_name} · {target.assigned_to_display_name ?? "미배정"}</small>
                </div>
                <span className={`campaign-status campaign-status--${target.status}`}>
                  {campaignStatusLabels[target.status]}
                </span>
                {canEditTarget ? (
                  <CampaignTargetEditForm
                    target={target}
                    draft={draft}
                    editState={editState}
                    assignees={assignees}
                    saving={savingId === target.id}
                    onDraftChange={(updater) => setDrafts((current) => ({
                      ...current,
                      [target.id]: updater(current[target.id] ?? draft),
                    }))}
                    onSave={() => void save(target)}
                  />
                ) : (
                  <span className="department-campaign-result">{target.result ?? "결과 대기"}</span>
                )}
              </div>
            );
          })}
        </div>
      )}
      {hasPagination && (
        <DepartmentPagination
          label="캠페인 처리"
          currentStart={currentStart}
          currentEnd={currentEnd}
          total={total}
          page={page}
          totalPages={totalPages}
          onPageChange={onPageChange}
        />
      )}
      {useDrawerEditing && drawerTarget !== null && (
        <>
          <div className="department-drawer-backdrop" onClick={() => setDrawerTargetId(null)} />
          <aside className="department-drawer" role="dialog" aria-modal="true" aria-labelledby="campaign-drawer-title">
            <div className="department-drawer__head">
              <div>
                <p className="department-drawer__kicker">캠페인 처리</p>
                <h3 id="campaign-drawer-title">#{drawerTarget.customer_id}</h3>
              </div>
              <button type="button" className="department-drawer__close" aria-label="닫기" onClick={() => setDrawerTargetId(null)}>×</button>
            </div>
            <p className="department-drawer__campaign">{drawerTarget.campaign_name}</p>
            <CampaignTargetEditForm
              target={drawerTarget}
              draft={getDraft(drawerTarget)}
              editState={computeTargetEditState(drawerTarget, getDraft(drawerTarget), user, canManage)}
              assignees={assignees}
              saving={savingId === drawerTarget.id}
              onDraftChange={(updater) => setDrafts((current) => ({
                ...current,
                [drawerTarget.id]: updater(current[drawerTarget.id] ?? getDraft(drawerTarget)),
              }))}
              onSave={() => void save(drawerTarget)}
            />
          </aside>
        </>
      )}
    </section>
  );
}

function RoleSummary({ user }: { user: AuthUser }) {
  return (
    <aside className="department-panel department-panel--role">
      <p className="card-kicker">YOUR WORKSPACE</p>
      <h2>{roleLabels[user.role]}</h2>
      <p>{roleDescriptions[user.role]}</p>
      <div className="department-role-pill">{user.username}</div>
    </aside>
  );
}

function TeamRoster({
  members,
  onUpdated,
}: {
  members: TeamMember[];
  onUpdated: (member: TeamMember) => void;
}) {
  const [drafts, setDrafts] = useState<Record<number, { role: TeamMember["role"]; is_active: boolean }>>({});
  const [savingId, setSavingId] = useState<number | null>(null);
  const [error, setError] = useState("");

  const save = async (member: TeamMember) => {
    const draft = drafts[member.id] ?? { role: member.role, is_active: member.is_active };
    setSavingId(member.id);
    setError("");
    try {
      const updated = await updateTeamMember(member.id, draft);
      onUpdated(updated);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "팀 계정 변경에 실패했습니다.");
    } finally {
      setSavingId(null);
    }
  };

  return (
    <>
      {error !== "" && <p className="department-inline-error" role="alert">{error}</p>}
      <div className="department-team-list">
        {members.map((member) => {
          const draft = drafts[member.id] ?? { role: member.role, is_active: member.is_active };
          return (
            <div className="department-team-row" key={member.id}>
              <div>
                <strong>{member.display_name}</strong>
                <small>{member.username} · {member.is_active ? "활성" : "비활성"}</small>
              </div>
              <select
                aria-label={`${member.display_name} 역할`}
                className={member.role === "admin" ? "department-team-select department-team-select--locked" : "department-team-select"}
                value={draft.role}
                disabled={member.role === "admin"}
                onChange={(event) => setDrafts((current) => ({
                  ...current,
                  [member.id]: { ...draft, role: event.target.value as TeamMember["role"] },
                }))}
              >
                <option value="admin">관리자</option>
                <option value="analyst">분석 담당자</option>
                <option value="operations">운영 담당자</option>
                <option value="marketing">마케팅 담당자</option>
              </select>
              <select
                aria-label={`${member.display_name} 계정 상태`}
                className="department-team-select"
                value={draft.is_active ? "active" : "inactive"}
                onChange={(event) => setDrafts((current) => ({
                  ...current,
                  [member.id]: { ...draft, is_active: event.target.value === "active" },
                }))}
              >
                <option value="active">활성</option>
                <option value="inactive">비활성</option>
              </select>
              <button type="button" disabled={savingId === member.id} onClick={() => void save(member)}>
                {savingId === member.id ? "저장 중..." : "저장"}
              </button>
            </div>
          );
        })}
      </div>
    </>
  );
}

export function DepartmentDashboardPage({ user }: DepartmentDashboardPageProps) {
  const [insights, setInsights] = useState<CustomerInsightList | null>(null);
  const [targets, setTargets] = useState<CampaignTarget[]>([]);
  const [campaignTargetTotal, setCampaignTargetTotal] = useState(0);
  const [campaignQueuePage, setCampaignQueuePage] = useState(1);
  const [campaignQueueTotalPages, setCampaignQueueTotalPages] = useState(0);
  const [campaignQueueStats, setCampaignQueueStats] = useState<CampaignTargetStats | null>(null);
  const [campaignQueueFilter, setCampaignQueueFilter] = useState<number | "">("");
  const [campaignQueueOptions, setCampaignQueueOptions] = useState<Campaign[]>([]);
  const [performance, setPerformance] = useState<CampaignPerformance | null>(null);
  const [coverage, setCoverage] = useState<HighRiskCoverage | null>(null);
  const [dualSignal, setDualSignal] = useState<DualSignalSummary | null>(null);
  const [dualSignalFilterActive, setDualSignalFilterActive] = useState(false);
  const [dualSignalPage, setDualSignalPage] = useState(1);
  const [reasonCodes, setReasonCodes] = useState<ReasonCodeDistribution | null>(null);
  const [highRiskTotal, setHighRiskTotal] = useState<number | null>(null);
  const [activeCampaignCount, setActiveCampaignCount] = useState<number | null>(null);
  const [adminDetailOpen, setAdminDetailOpen] = useState(false);
  const [activeGuideKey, setActiveGuideKey] = useState<string | null>(null);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState<number | null>(null);
  const [operationsInsightPage, setOperationsInsightPage] = useState(1);
  const [operationsRiskFilter, setOperationsRiskFilter] = useState<"" | "high" | "medium" | "low">("high");
  const [campaignQueueStatusFilter, setCampaignQueueStatusFilter] = useState<CampaignStatus | "">("");
  const [selectedInsightId, setSelectedInsightId] = useState<number | null>(null);
  const [insightPage, setInsightPage] = useState(1);
  const [marketingRiskFilter, setMarketingRiskFilter] = useState<MarketingRiskFilter>("");
  const [marketingClusterFilter, setMarketingClusterFilter] = useState("");
  const [marketingSortBy, setMarketingSortBy] = useState<MarketingSortBy>("churn_probability");
  const [marketingSortOrder, setMarketingSortOrder] = useState<MarketingSortOrder>("desc");
  const [createMessage, setCreateMessage] = useState("");
  const [campaignConflictMessage, setCampaignConflictMessage] = useState("");
  const [insightRefreshKey, setInsightRefreshKey] = useState(0);

  const canProcessTargets = user.role === "admin" || user.role === "operations";
  const showsCampaignQueue = user.role === "operations" || user.role === "marketing";
  const canCreateCampaignTargets = user.role === "admin" || user.role === "marketing";
  const insightQuery = useMemo(() => {
    if (user.role === "operations") {
      if (dualSignalFilterActive) {
        return {
          risk_level: "high" as const,
          sort_by: "activity_gap" as const,
          sort_order: "asc" as const,
          page: 1,
          page_size: DUAL_SIGNAL_PAGE_SIZE,
        };
      }
      return {
        risk_level: operationsRiskFilter || undefined,
        sort_by: "churn_probability" as const,
        sort_order: "desc" as const,
        page: operationsInsightPage,
        page_size: OPERATIONS_INSIGHT_PAGE_SIZE,
      };
    }
    if (user.role === "marketing") {
      return {
        risk_level: marketingRiskFilter || undefined,
        cluster_name: marketingClusterFilter || undefined,
        sort_by: marketingSortBy,
        sort_order: marketingSortOrder,
        campaign_candidates_only: true,
        page: insightPage,
        page_size: MARKETING_INSIGHT_PAGE_SIZE,
      };
    }
    return {
      sort_by: "churn_probability" as const,
      sort_order: "desc" as const,
      page: 1,
      page_size: 100,
    };
  }, [dualSignalFilterActive, insightPage, marketingClusterFilter, marketingRiskFilter, marketingSortBy, marketingSortOrder, operationsInsightPage, operationsRiskFilter, user.role]);

  useEffect(() => {
    let isActive = true;
    const fetchDualSignalExtraPages = dualSignalFilterActive && user.role === "operations";
    const load = async () => {
    const [
      insightResult, insightExtraPagesResult, campaignResult, performanceResult, coverageResult,
      dualSignalResult, activeCampaignResult, reasonCodeResult, highRiskTotalResult,
    ] = await Promise.allSettled([
        listCustomerInsights(insightQuery),
        fetchDualSignalExtraPages
          ? Promise.all(
              Array.from({ length: DUAL_SIGNAL_FETCH_PAGES - 1 }, (_, i) =>
                listCustomerInsights({ ...insightQuery, page: i + 2 }),
              ),
            )
          : Promise.resolve([]),
        listCampaignTargets({
    page: campaignQueuePage,
    page_size: CAMPAIGN_QUEUE_PAGE_SIZE,
    ...(user.role === "operations" ? { sort_by_priority: true } : {}),
    ...(campaignQueueFilter === "" ? {} : { campaign_id: campaignQueueFilter }),
    ...(campaignQueueStatusFilter === "" ? {} : { status: campaignQueueStatusFilter }),
  }),
  user.role === "marketing" || user.role === "admin" || user.role === "operations" ? getCampaignPerformance() : Promise.resolve(null),
  user.role === "admin" ? getHighRiskCoverage() : Promise.resolve(null),
  user.role === "operations" ? getDualSignalCount() : Promise.resolve(null),
  user.role === "admin" ? listCampaigns({ status: "active", page_size: 1 }) : Promise.resolve(null),
  user.role === "operations" ? getReasonCodeDistribution({ risk_level: "high" }) : Promise.resolve(null),
  user.role === "operations" ? listCustomerInsights({ risk_level: "high", page: 1, page_size: 1 }) : Promise.resolve(null),
]);
      if (!isActive) {
        return;
      }
      if (insightResult.status === "fulfilled") {
        const extraItems = insightExtraPagesResult.status === "fulfilled"
          ? insightExtraPagesResult.value.flatMap((page) => page.items)
          : [];
        setInsights(extraItems.length === 0
          ? insightResult.value
          : { ...insightResult.value, items: [...insightResult.value.items, ...extraItems] });
      } else {
        setError(insightResult.reason instanceof Error ? insightResult.reason.message : "분석 결과를 불러오지 못했습니다.");
      }
      if (campaignResult.status === "fulfilled") {
        setTargets(campaignResult.value.items);
        setCampaignTargetTotal(campaignResult.value.total);
        setCampaignQueueTotalPages(campaignResult.value.total_pages);
        setCampaignQueueStats(campaignResult.value.stats ?? null);
      }
      if (performanceResult.status === "fulfilled" && performanceResult.value !== null) {
        setPerformance(performanceResult.value);
      }
      if (coverageResult.status === "fulfilled" && coverageResult.value !== null) {
        setCoverage(coverageResult.value);
      }
      if (dualSignalResult.status === "fulfilled" && dualSignalResult.value !== null) {
        setDualSignal(dualSignalResult.value);
      }
      if (activeCampaignResult.status === "fulfilled" && activeCampaignResult.value !== null) {
        setActiveCampaignCount(activeCampaignResult.value.total);
      }
      if (reasonCodeResult.status === "fulfilled" && reasonCodeResult.value !== null) {
        setReasonCodes(reasonCodeResult.value);
      }
      if (highRiskTotalResult.status === "fulfilled" && highRiskTotalResult.value !== null) {
        setHighRiskTotal(highRiskTotalResult.value.total);
      }
      setIsLoading(false);
    };
    void load();
    return () => {
      isActive = false;
    };
  }, [campaignQueueFilter, campaignQueuePage, campaignQueueStatusFilter, insightQuery, insightRefreshKey, user.role]);

  // 처리 현황 필터의 선택지입니다. 대상 목록은 페이지 단위로 잘려 오므로,
  // 목록에 보이는 캠페인만 모아 만들면 다른 페이지의 캠페인이 빠집니다.
  useEffect(() => {
    if (!showsCampaignQueue) {
      return;
    }
    let isActive = true;
    void listCampaigns({ page: 1, page_size: CAMPAIGN_FILTER_PAGE_SIZE })
      .then((response) => {
        if (isActive) {
          setCampaignQueueOptions(response.items);
        }
      })
      .catch(() => {
        if (isActive) {
          setCampaignQueueOptions([]);
        }
      });
    return () => {
      isActive = false;
    };
  }, [showsCampaignQueue]);

  const updateCampaignQueueFilter = (value: number | "") => {
    setCampaignQueueFilter(value);
    setCampaignQueuePage(1);
  };

  useEffect(() => {
    let isActive = true;
    void listTeamMembers(user.role === "admin")
      .then((response) => {
        if (isActive) {
          const operationsMembers = response.filter(
            (member) => member.role === "operations" && member.is_active,
          );
          setMembers(
            user.role === "admin"
              ? response
              : user.role === "operations"
              ? operationsMembers.filter((member) => member.id === user.id)
              : operationsMembers,
          );
        }
      })
      .catch(() => {
        if (isActive) {
          setMembers([]);
        }
      });
    return () => {
      isActive = false;
    };
  }, [user.id, user.role]);

  const createCampaign = async (insight: CustomerInsight, campaignNameOverride?: string) => {
    if (!canCreateCampaignTargets) {
      return;
    }
    setIsCreating(insight.id);
    setCreateMessage("");
    try {
      const target = await createCampaignTarget({
        customer_insight_id: insight.id,
        campaign_name: campaignNameOverride
          ?? (user.role === "marketing" ? "세그먼트 리텐션 캠페인" : "고위험 고객 리텐션"),
      });
      setTargets((current) => [target, ...current]);
      setCampaignTargetTotal((current) => current + 1);
      setCreateMessage("캠페인 대상에 미배정 상태로 등록했습니다.");
      setCampaignQueuePage(1);
      setInsightPage(1);
      setInsightRefreshKey((current) => current + 1);
    } catch (requestError) {
      const apiError = requestError as ApiError;
      if (apiError.status === 409) {
        setCreateMessage("");
        setCampaignConflictMessage(
          "다른 사용자가 먼저 등록했거나 이 고객이 최근 접촉·수신 거부 상태로 변경되어 등록할 수 없습니다.",
        );
        setCampaignQueuePage(1);
        setInsightPage(1);
        setInsightRefreshKey((current) => current + 1);
      } else {
        setCreateMessage(requestError instanceof Error ? requestError.message : "캠페인 등록에 실패했습니다.");
      }
    } finally {
      setIsCreating(null);
    }
  };

  const updateMarketingRiskFilter = (value: MarketingRiskFilter) => {
    setMarketingRiskFilter(value);
    setInsightPage(1);
  };

  const handleCampaignQueueUpdated = (updated: CampaignTarget) => {
    setTargets((current) => current.map((target) => target.id === updated.id ? updated : target));
    setInsightRefreshKey((current) => current + 1);
  };

  const updateMarketingClusterFilter = (value: string) => {
    setMarketingClusterFilter(value);
    setInsightPage(1);
  };

  const updateMarketingSortBy = (value: MarketingSortBy) => {
    setMarketingSortBy(value);
    setMarketingSortOrder(value === "activity_gap" ? "asc" : "desc");
    setInsightPage(1);
  };

  const updateMarketingSortOrder = (value: MarketingSortOrder) => {
    setMarketingSortOrder(value);
    setInsightPage(1);
  };

  const resetMarketingFilters = () => {
    setMarketingRiskFilter("");
    setMarketingClusterFilter("");
    setMarketingSortBy("churn_probability");
    setMarketingSortOrder("desc");
    setInsightPage(1);
  };

  const highRiskCount = highRiskTotal ?? insights?.stats.risk_counts.high ?? 0;
  const pendingCount = campaignQueueStats?.unprocessed_targets ?? 0;
  const completedCount = campaignQueueStats?.status_counts.completed ?? 0;
  const dualSignalInsights = dualSignal === null || dualSignal.activity_gap_threshold === null
    ? []
    : (insights?.items ?? []).filter((item) => item.activity_gap <= dualSignal.activity_gap_threshold!);
  const dualSignalTotalPages = Math.max(1, Math.ceil(dualSignalInsights.length / OPERATIONS_INSIGHT_PAGE_SIZE));
  const pagedDualSignalInsights = dualSignalInsights.slice(
    (dualSignalPage - 1) * OPERATIONS_INSIGHT_PAGE_SIZE,
    dualSignalPage * OPERATIONS_INSIGHT_PAGE_SIZE,
  );
  const priorityInsights = dualSignalFilterActive ? pagedDualSignalInsights : insights?.items ?? [];
  const priorityTotal = dualSignalFilterActive ? dualSignal?.count ?? 0 : insights?.total ?? 0;
  const priorityTotalPages = dualSignalFilterActive ? dualSignalTotalPages : insights?.total_pages ?? 0;
  const campaignStatusCounts = useMemo(() => Object.fromEntries(
    Object.keys(campaignStatusLabels).map((status) => [
      status,
      campaignQueueStats?.status_counts[status] ?? 0,
    ]),
  ) as Record<CampaignStatus, number>, [campaignQueueStats]);
  const campaignStatusTotal = Math.max(
    campaignQueueStats?.total_targets ?? campaignTargetTotal,
    1,
  );

  const operationsContactRate = performance?.summary.treatment_contact_rate ?? null;
  const operationsConversionRate = performance?.summary.conversion_rate ?? null;
  const operationsCompletedRate = campaignStatusTotal > 0
    ? campaignStatusCounts.completed / campaignStatusTotal
    : null;
  const selectedInsight = priorityInsights.find((item) => item.id === selectedInsightId)
    ?? priorityInsights[0]
    ?? null;
  const selectedMarketingInsight = (insights?.items ?? []).find((item) => item.id === selectedInsightId)
    ?? insights?.items[0]
    ?? null;

  const roleContent = user.role === "operations" ? (
    <>
      <OperationsTopNav />
      <div id="operations-verdict">
        <OperationsVerdictHero dualSignal={dualSignal} pendingCount={pendingCount} />
      </div>
      <section className="department-stats">
        <StatCard label="HIGH RISK" value={formatNumber(highRiskCount)} caption="우선 관리 대상" tone="pink" />
        <StatCard label="OPEN QUEUE" value={formatNumber(pendingCount)} caption="대기중인 캠페인 대상" tone="orange" />
        <StatCard label="COMPLETED" value={formatNumber(completedCount)} caption="처리 완료된 캠페인 대상" tone="green" />
      </section>
      <DualSignalHero
        dualSignal={dualSignal}
        active={dualSignalFilterActive}
        onClick={() => {
          setDualSignalFilterActive((current) => !current);
          setDualSignalPage(1);
          document.getElementById("operations-priority")?.scrollIntoView({ behavior: "smooth" });
        }}
      />
      <div id="operations-priority">
        <InsightPriorityTable
          kicker="PRIORITY INSIGHTS"
          heading="우선 관리 고객"
          toolbar={dualSignalFilterActive ? (
            <div className="department-filter-chip is-active">
              이중 신호 고위험 고객만 보는 중
              <button type="button" onClick={() => { setDualSignalFilterActive(false); setDualSignalPage(1); }}>✕ 해제</button>
            </div>
          ) : (
            <div className="department-risk-tabs">
              {(["", "high", "medium", "low"] as const).map((level) => (
                <button
                  key={level || "all"}
                  type="button"
                  className={`department-risk-tab${operationsRiskFilter === level ? " is-active" : ""}`}
                  onClick={() => {
                    setOperationsRiskFilter(level);
                    setOperationsInsightPage(1);
                  }}
                >
                  {level === "" ? "전체" : riskLabels[level]}
                </button>
              ))}
            </div>
          )}
          insights={priorityInsights}
          targets={targets}
          campaignName="리텐션 등록"
          onCreate={canCreateCampaignTargets ? (item, name) => void createCampaign(item, name) : undefined}
          allowCustomName
          compact
          isCreating={isCreating}
          total={priorityTotal}
          page={dualSignalFilterActive ? dualSignalPage : operationsInsightPage}
          pageSize={OPERATIONS_INSIGHT_PAGE_SIZE}
          totalPages={priorityTotalPages}
          onPageChange={dualSignalFilterActive ? setDualSignalPage : setOperationsInsightPage}
          onSelectInsight={(insight) => {
            setSelectedInsightId(insight.id);
            document.getElementById("operations-detail")?.scrollIntoView({ behavior: "smooth", block: "start" });
          }}
          selectedInsightId={selectedInsightId ?? priorityInsights[0]?.id ?? null}
        />
      </div>
      <div id="operations-detail">
        <OperationsInsightDetail insight={selectedInsight} />
      </div>
      <div id="operations-queue">
        <CampaignQueue
          targets={targets}
          total={campaignTargetTotal}
          page={campaignQueuePage}
          pageSize={CAMPAIGN_QUEUE_PAGE_SIZE}
          totalPages={campaignQueueTotalPages}
          onPageChange={setCampaignQueuePage}
          canManage={canProcessTargets}
          assignees={members.filter((member) => member.role === "operations" && member.is_active)}
          user={user}
          onUpdated={handleCampaignQueueUpdated}
          campaignFilter={campaignQueueFilter}
          campaignOptions={campaignQueueOptions}
          onCampaignFilterChange={updateCampaignQueueFilter}
          useDrawerEditing
          statusFilter={campaignQueueStatusFilter}
          onStatusFilterChange={(value) => {
            setCampaignQueueStatusFilter(value);
            setCampaignQueuePage(1);
          }}
        />
      </div>
      <section className="department-panel">
        <div className="department-panel__heading-with-guide">
          <p className="card-kicker">PROCESS FUNNEL</p>
          <InfoBtn guideKey="캠페인 상태 퍼널" />
        </div>
        <h2>캠페인 대상 처리 퍼널</h2>
        <div className="department-process-funnel">
          {(["pending", "assigned", "contacted", "completed"] as const).map((status, index) => {
            const count = campaignStatusCounts[status];
            const sharePct = campaignStatusTotal > 0
              ? Math.round((count / campaignStatusTotal) * 100)
              : null;
            return (
              <Fragment key={status}>
                {index > 0 && <div className="department-process-funnel__arrow">→</div>}
                <div className={`department-process-funnel__stage${status === "completed" ? " is-done" : ""}`}>
                  <p>{campaignStatusLabels[status]}</p>
                  <strong>{formatNumber(count)}건</strong>
                  {sharePct !== null && <small>전체의 {sharePct}%</small>}
                </div>
              </Fragment>
            );
          })}
        </div>
        <p className="department-panel__caption">
          각 단계는 현재 시점의 상태별 건수 스냅샷입니다(순차 전환율이 아닙니다) · %는 전체 대상 대비 비중 · CampaignStatus(pending→assigned→contacted→completed) 기준
        </p>
      </section>
      <div className="department-evidence-grid">
        <section className="department-panel">
          <div className="department-panel__heading-with-guide">
            <p className="card-kicker">근거 — 접촉률 / 전환율 / 완료율</p>
            <InfoBtn guideKey="접촉률 / 전환율" />
          </div>
          <div className="department-sidebar-metrics">
            <div>
              <p>접촉률<br />(개입군)</p>
              <strong>{operationsContactRate === null ? "—" : formatPercent(operationsContactRate)}</strong>
            </div>
            <div>
              <p>전환율 †</p>
              <strong>{operationsConversionRate === null ? "—" : formatPercent(operationsConversionRate)}</strong>
            </div>
            <div>
              <p>완료율</p>
              <strong>{operationsCompletedRate === null ? "—" : formatPercent(operationsCompletedRate)}</strong>
            </div>
          </div>
          <p className="department-panel__caption">† 전환율·완료율은 담당자가 화면에서 직접 입력한 값입니다.</p>
        </section>
        <section className="department-panel">
          <p className="card-kicker">이탈 사유코드 분포 (고위험 기준)</p>
          <ReasonCodePanel data={reasonCodes} />
        </section>
        <section className="department-panel">
          <div className="department-panel__heading-with-guide">
            <p className="card-kicker">담당자별 처리 현황</p>
            <InfoBtn guideKey="담당자별 처리 현황" />
          </div>
          {performance === null || performance.by_assignee.length === 0 ? (
            <p className="department-empty">담당자별 데이터가 없습니다.</p>
          ) : (
            <div className="campaign-performance-table-wrap">
              <table className="campaign-performance-table campaign-performance-table--sidebar">
                <thead>
                  <tr>
                    <th scope="col">담당자</th>
                    <th scope="col">배정</th>
                    <th scope="col">접촉률</th>
                    <th scope="col">전환율</th>
                  </tr>
                </thead>
                <tbody>
                  {performance.by_assignee.map((item) => (
                    <tr key={item.key}>
                      <th scope="row">{item.label}</th>
                      <td>{formatNumber(item.target_count)}</td>
                      <td>{item.treatment_contact_rate === null ? "—" : formatPercent(item.treatment_contact_rate)}</td>
                      <td>{item.treatment_conversion_rate === null ? "—" : formatPercent(item.treatment_conversion_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </>
  ) : user.role === "marketing" ? (
    <>
      <MarketingVerdictHero performance={performance} />
      <section className="department-stats">
        <StatCard label="TARGETS" value={formatNumber(campaignTargetTotal)} caption="등록된 캠페인 대상" tone="purple" />
        <StatCard label="OPEN QUEUE" value={formatNumber(pendingCount)} caption="실행 대기 대상" tone="orange" />
        <StatCard label="COMPLETED" value={formatNumber(completedCount)} caption="처리 완료 캠페인" tone="green" />
        <StatCard
          label="ROI"
          value={performance === null ? "—" : formatSignedPercent(performance.summary.roi)}
          caption="증분매출 대비 캠페인 비용 회수율"
          tone={performance !== null && performance.summary.roi !== null && performance.summary.roi < 0 ? "pink" : "gold"}
          guideKey="ROI"
        />
      </section>
      <div className="department-split-layout">
        <div className="department-split-main">
          <InsightPriorityTable
            kicker="CAMPAIGN CANDIDATES"
            heading="캠페인 후보 고객"
            toolbar={(
              <MarketingCandidateFilters
                riskLevel={marketingRiskFilter}
                clusterName={marketingClusterFilter}
                sortBy={marketingSortBy}
                sortOrder={marketingSortOrder}
                clusterOptions={insights?.stats.cluster_options ?? {}}
                onRiskLevelChange={updateMarketingRiskFilter}
                onClusterNameChange={updateMarketingClusterFilter}
                onSortByChange={updateMarketingSortBy}
                onSortOrderChange={updateMarketingSortOrder}
                onReset={resetMarketingFilters}
              />
            )}
            insights={insights?.items ?? []}
            targets={targets}
            campaignName="캠페인 등록"
            onCreate={undefined}
            isCreating={isCreating}
            total={insights?.total ?? 0}
            page={insightPage}
            pageSize={MARKETING_INSIGHT_PAGE_SIZE}
            totalPages={insights?.total_pages ?? 0}
            onPageChange={setInsightPage}
            onSelectInsight={(insight) => {
              setSelectedInsightId(insight.id);
              document.getElementById("marketing-detail")?.scrollIntoView({ behavior: "smooth", block: "start" });
            }}
            selectedInsightId={selectedInsightId ?? insights?.items[0]?.id ?? null}
          />
          <div id="marketing-detail">
            <OperationsInsightDetail insight={selectedMarketingInsight} />
          </div>
          <div id="operations-queue">
          <CampaignQueue
            targets={targets}
            total={campaignTargetTotal}
            page={campaignQueuePage}
            pageSize={CAMPAIGN_QUEUE_PAGE_SIZE}
            totalPages={campaignQueueTotalPages}
            onPageChange={setCampaignQueuePage}
            canManage={canProcessTargets}
            assignees={members.filter((member) => member.role === "operations" && member.is_active)}
            user={user}
            onUpdated={handleCampaignQueueUpdated}
            campaignFilter={campaignQueueFilter}
            campaignOptions={campaignQueueOptions}
            onCampaignFilterChange={updateCampaignQueueFilter}
            statusFilter={campaignQueueStatusFilter}
            onStatusFilterChange={(value) => {
              setCampaignQueueStatusFilter(value);
              setCampaignQueuePage(1);
            }}
          />
          </div>
        </div>
        <aside className="department-split-sidebar">
          <MarketingRoiPanel performance={performance} />
          <ClusterUpliftPanel performance={performance} compact />
        </aside>
      </div>
      <section className="department-panel">
        <div className="department-panel__heading-with-guide">
          <p className="card-kicker">PROCESS FUNNEL</p>
          <InfoBtn guideKey="캠페인 상태 퍼널" />
        </div>
        <h2>캠페인 대상 처리 퍼널</h2>
        <div className="department-process-funnel">
          {(["pending", "assigned", "contacted", "completed"] as const).map((status, index) => {
            const count = campaignStatusCounts[status];
            const sharePct = campaignStatusTotal > 0
              ? Math.round((count / campaignStatusTotal) * 100)
              : null;
            return (
              <Fragment key={status}>
                {index > 0 && <div className="department-process-funnel__arrow">→</div>}
                <div className={`department-process-funnel__stage${status === "completed" ? " is-done" : ""}`}>
                  <p>{campaignStatusLabels[status]}</p>
                  <strong>{formatNumber(count)}건</strong>
                  {sharePct !== null && <small>전체의 {sharePct}%</small>}
                </div>
              </Fragment>
            );
          })}
        </div>
        <p className="department-panel__caption">
          각 단계는 현재 시점의 상태별 건수 스냅샷입니다(순차 전환율이 아닙니다) · %는 전체 대상 대비 비중 · CampaignStatus(pending→assigned→contacted→completed) 기준
        </p>
      </section>
    </>
  ) : (
    <>
      <div className="department-admin-title-row">
        <div>
          <p className="department-admin-title-row__eyebrow">FINANCIAL CUSTOMER RISK ANALYTICS</p>
          <h1 className="department-admin-title-row__heading">고객 이탈 방어 성과</h1>
        </div>
      </div>
      <AdminVerdictHero coverage={coverage} performance={performance} />
      <section className="department-stats">
        <StatCard label="CUSTOMERS" value={formatNumber(insights?.stats.total ?? 0)} caption="분석 대상 고객" tone="purple" />
        <StatCard
          label="REVENUE DEFENDED"
          value={performance === null ? "—" : formatCurrency(performance.summary.incremental_revenue)}
          caption="전체 방어매출"
          tone="gold"
        />
        <StatCard
          label="AVERAGE ROI"
          value={performance === null ? "—" : formatSignedPercent(performance.summary.roi)}
          caption="마케팅 투입비용 대비 회수율"
          tone="green"
        />
        <StatCard
          label="ACTIVE CAMPAIGNS"
          value={activeCampaignCount === null ? "—" : formatNumber(activeCampaignCount)}
          caption="현재 진행중인 캠페인"
          tone="orange"
        />
      </section>
      <SectionHeader>근거 — 위험도별 방어매출·ROI</SectionHeader>
      <AdminDecisionPanel performance={performance} />
      <SectionHeader>상세 — 실행</SectionHeader>
      <div className="department-accordion">
        <DetailAccordionRow
          title="팀 계정 관리 · 권한 설정 · 담당자 배정"
          source={`TeamRoster · ${formatNumber(members.length)}명`}
          isOpen={adminDetailOpen}
          onToggle={() => setAdminDetailOpen((current) => !current)}
        >
          <TeamRoster
            members={members}
            onUpdated={(updated) => setMembers((current) => current.map((member) => member.id === updated.id ? updated : member))}
          />
        </DetailAccordionRow>
      </div>
    </>
  );

  return (
    <GuideContext.Provider value={setActiveGuideKey}>
      <div className={`department-layout--${user.role}`}>
        {isLoading && <section className="department-loading">부서별 업무 데이터를 불러오는 중입니다.</section>}
        {!isLoading && error !== "" && <section className="department-error" role="alert">{error}</section>}
        {!isLoading && error === "" && (
          <div className="department-content">
            <RoleSummary user={user} />
            {createMessage !== "" && <p className="department-message" role="status">{createMessage}</p>}
            {roleContent}
          </div>
        )}
        {campaignConflictMessage !== "" && (
          <CampaignConflictDialog
            message={campaignConflictMessage}
            onClose={() => setCampaignConflictMessage("")}
          />
        )}
        <GuideDialog guideKey={activeGuideKey} onClose={() => setActiveGuideKey(null)} />
      </div>
    </GuideContext.Provider>
  );
}
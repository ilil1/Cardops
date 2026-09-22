// 분석 기능에서 사용하는 공개 API입니다. 화면 컴포넌트는 이 진입점을 통해
// API 계약을 직접 구현 세부사항과 분리해 사용할 수 있습니다.

export {
  getCustomerInsight,
  getCustomerInsightHistory,
  listCustomerInsights,
} from "../../api/insights";
export type {
  CustomerInsight,
  CustomerInsightDetail,
  CustomerInsightHistory,
  CustomerInsightList,
  InsightQuery,
} from "../../api/insights";

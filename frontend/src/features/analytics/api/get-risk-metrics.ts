// src/features/analytics/api/get-risk-metrics.ts —— 持仓风险指标数据层
// 消费 GET /portfolio/analytics/risk-metrics:后端基于快照表日频市值组装日频 TWR
// 收益率,再用 QuantStats 算波动率/夏普/回撤等专业指标。参数 snake_case(与
// comparison 同款坑:后端标量 Query 没写驼峰别名,传 startDate 会 422)。
import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api-client';

/** 指标值均为百分数(两位小数);null = 该指标算不出(数据不足/基准缺失),展示层显示「—」 */
export type RiskMetrics = {
  annualVolatility: number | null;
  maxDrawdown: number | null;
  maxDrawdownStart: string | null;
  maxDrawdownValley: string | null;
  maxDrawdownEnd: string | null;
  recoveryDays: number | null;
  longestDrawdownDays: number;
  sharpe: number | null;
  sortino: number | null;
  calmar: number | null;
  downsideVolatility: number | null;
  winRate: number | null;
  var: number | null;
  cvar: number | null;
  informationRatio: number | null;
  beta: number | null;
  alpha: number | null;
  trackingError: number | null;
  /** 夏普实际用到的无风险利率(百分数):后端按评估区间取中国国债 2 年期均值,取数失败时为兜底值 */
  riskFreeRate: number;
};

export type DrawdownPoint = { date: string; dd: number };
export type DateValue = { date: string; value: number };
export type MonthlyReturnRow = {
  year: number;
  months: (number | null)[];
  yearTotal: number | null;
};

/** 滚动风险序列(60 交易日):组合/基准年化波动率(%)与组合/基准滚动夏普 */
export type RollingSeries = {
  portfolioVol: DateValue[];
  benchmarkVol: DateValue[];
  sharpe: DateValue[];
  /** 基准的滚动夏普:与组合同窗口、同无风险利率,可横向比高低 */
  benchmarkSharpe: DateValue[];
};

/** 日收益分布直方图:binEdges 为百分比刻度(N+1 条边对应 N 个 bin) */
export type ReturnHistogram = { binEdges: number[]; counts: number[] };

/** 胜/负/平交易日数:胜率环形图与胜率指标同源 */
export type ReturnStats = {
  winDays: number;
  loseDays: number;
  flatDays: number;
};

export type RiskMetricsPayload = {
  metrics: RiskMetrics | null;
  drawdownSeries: DrawdownPoint[];
  /** 与 drawdownSeries 同一日期轴、等长;喂给 QuantStats 的基准日收益序列直接换算 */
  benchmarkDrawdownSeries: DrawdownPoint[];
  /** 与 drawdownSeries 同一日期轴;取自对齐后的日收益序列复利累乘,故与 maxDrawdown 同路径 */
  returnSeries: DateValue[];
  monthlyReturns: MonthlyReturnRow[];
  annualizedSeries: DateValue[];
  /** 与 annualizedSeries 同口径、同日期轴;喂给 QuantStats 的基准日收益序列直接换算 */
  benchmarkAnnualizedSeries: DateValue[];
  rollingSeries: RollingSeries;
  returnHistogram: ReturnHistogram;
  returnStats: ReturnStats;
  dataQuality: { incompleteDates: string[]; funds: string[]; note: string };
  tradeDays: number;
  benchmark: string;
};

export const useRiskMetrics = (
  startDate: string,
  endDate: string | undefined,
  benchmark: string,
) =>
  useQuery<RiskMetricsPayload>({
    queryKey: ['risk-metrics', startDate, endDate, benchmark],
    queryFn: () =>
      api
        .get('/portfolio/analytics/risk-metrics', {
          // endDate 为 undefined 时 axios 丢弃该参数,后端缺省取今天
          params: { start_date: startDate, end_date: endDate, benchmark },
        })
        .then((res) => res as unknown as RiskMetricsPayload),
    staleTime: 5 * 60 * 1000,
  });

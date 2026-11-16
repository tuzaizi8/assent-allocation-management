// src/features/analytics/api/get-fund-risk-metrics.ts —— 基金风险指标数据层
// 消费 GET /portfolio/analytics/fund-risk-metrics:收益率序列直接取自复权净值
// 相邻相除(复权已消除分红跳变,无需快照/现金流/TWR 修正),指标内核与持仓风险
// 指标同一套 QuantStats,故 payload 类型复用 get-risk-metrics 的既有定义。
// 时间档与基金详情收益率曲线同源(后端同一档位真相源),指标区间 = 曲线展示区间。
import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api-client';

import type {
  DateValue,
  DrawdownPoint,
  MonthlyReturnRow,
  ReturnHistogram,
  ReturnStats,
  RiskMetrics,
  RollingSeries,
} from './get-risk-metrics';

export type FundRiskMetricsPayload = {
  fundCode: string;
  period: string;
  metrics: RiskMetrics | null;
  /** 货币基金标记:无净值,波动率/回撤等指标不适用,前端据此换空态文案 */
  isMoneyFund?: boolean;
  drawdownSeries: DrawdownPoint[];
  benchmarkDrawdownSeries: DrawdownPoint[];
  returnSeries: DateValue[];
  monthlyReturns: MonthlyReturnRow[];
  annualizedSeries: DateValue[];
  benchmarkAnnualizedSeries: DateValue[];
  rollingSeries: RollingSeries;
  returnHistogram: ReturnHistogram;
  returnStats: ReturnStats;
  tradeDays: number;
  benchmark: string;
};

/**
 * 单基金风险指标(基金详情页收益率曲线下的指标条数据源)。
 * 行情走三级缓存(Redis 1h),前端 5 分钟内不重取即可保持新鲜;
 * fundCode 未就绪时不发请求;基准跟随曲线卡的指数选择,保证信息比率/贝塔
 * 与图中基准线是同一个对比对象。
 */
export const useFundRiskMetrics = (
  fundCode?: string,
  period?: string,
  benchmark?: string,
) =>
  useQuery<FundRiskMetricsPayload>({
    queryKey: ['fund-risk-metrics', fundCode, period, benchmark],
    queryFn: () =>
      api
        .get('/portfolio/analytics/fund-risk-metrics', {
          params: { fund_code: fundCode, period, benchmark },
        })
        .then((res) => res as unknown as FundRiskMetricsPayload),
    staleTime: 5 * 60 * 1000,
    enabled: fundCode != null,
  });

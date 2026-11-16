// src/features/dashboard/api/get-portfolio-analytics.ts —— 持仓走势序列(总市值/累计投入/总盈亏)
// 消费 GET /portfolio/analytics/comparison:有快照走快速路径,无快照退到逐日实时计算的慢路径。
// 参数必须 snake_case:后端标量 Query 参数没写驼峰别名(与 chart_controller 同款坑),传 startDate 会 422。
import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api-client';
import { formatDate } from '@/utils/format';

export type PortfolioTrendPoint = {
  date: string;
  totalValue: number;
  totalInvested: number;
  profit: number;
  /** 累计盈亏率(%):总盈亏 ÷ 累计投入,投入为 0 时给 0,避免 Infinity */
  profitRate: number;
};

/** 只声明本页消费的三个字段:comparison 还回 twr/mwr/benchmark/年化,未消费不建模 */
type ComparisonResponse = {
  dates: string[];
  portfolioValue: number[];
  totalInvested: number[];
};

/** 本地时区拼 yyyy-MM-dd:toISOString 的 UTC 转换会让东八区日期偏移一天 → 走 utils 统一实现 */

const daysAgo = (days: number) => {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return formatDate(date);
};

/** 近 N 天日频序列:一次请求同时供卡片 mini 图与「较上周」环比消费 */
export const usePortfolioTrend = (days = 30) =>
  useQuery<PortfolioTrendPoint[]>({
    queryKey: ['portfolio-trend', days],
    queryFn: () =>
      api
        .get('/portfolio/analytics/comparison', {
          params: {
            start_date: daysAgo(days),
            end_date: formatDate(new Date()),
            interval_days: 1,
          },
        })
        .then((res) => {
          const body = res as unknown as ComparisonResponse;
          const dates = body.dates ?? [];
          return dates.map((date, i) => {
            const totalValue = body.portfolioValue?.[i] ?? 0;
            const totalInvested = body.totalInvested?.[i] ?? 0;
            const profit = totalValue - totalInvested;
            return {
              date,
              totalValue,
              totalInvested,
              profit,
              profitRate:
                totalInvested > 0 ? (profit / totalInvested) * 100 : 0,
            };
          });
        }),
    staleTime: 5 * 60 * 1000,
  });

/**
 * 较上周:序列末尾与 7 天前比较(interval_days=1,故取倒数第 8 点)。
 * 点数不足(无快照/区间太短)返回 null——宁可不显示环比,也不用短序列冒充周环比;
 * 基准为 0(一周前还没建仓)时变化率无意义,rate 返回 null 而非 0,否则三态着色会误判成"零"。
 */
export const weekOverWeek = (values: number[]) => {
  if (values.length < 8) return null;
  const latest = values[values.length - 1] ?? 0;
  const previous = values[values.length - 8] ?? 0;
  return {
    change: latest - previous,
    rate:
      previous !== 0 ? ((latest - previous) / Math.abs(previous)) * 100 : null,
  };
};

// ===== 组合时间加权收益率序列(收益率对比卡的「我的」线) =====

export type PortfolioTwrPoint = {
  date: string;
  /** 区间累计收益率(TWR,%):后端 twr 是 100 基准累积值,减 100 即与基准线同口径 */
  value: number;
};

/** 后端回报的数据质量信息:记录不完整(赎回份额 > 当日持有份额)的日期与涉及基金 */
export type DataQuality = {
  incompleteDates?: string[];
  funds?: string[];
  note?: string;
};

export type PortfolioTwrResult = {
  points: PortfolioTwrPoint[];
  /** 记录不完整的日期(收益率已按「不产生收益」处理);空数组即无缺口 */
  incompleteDates: string[];
  /** 涉及基金代码(去重);空数组即无缺口 */
  gapFunds: string[];
};

/** comparison 里本卡只消费这几个字段:mwr/benchmark/年化未消费不建模 */
type TwrResponse = {
  dates: string[];
  twr: number[];
  portfolioValue: number[];
  dataQuality?: DataQuality;
};

/**
 * 组合时间加权收益率(TWR)序列——不受加仓/减仓影响的「投资表现」口径,
 * 才有资格与指数基准同图比较(市值归一化、相对成本收益率都会被"何时投钱"带偏)。
 *
 * 必须日频(interval_days=1):后端只剥离「采样点当天」的资金进出——且是按当日的
 * 申购总额与赎回总额分别剥离(同日既有买入又有赎回时不会互相抵消);但两个采样点
 * 之间发生的买卖仍不剥离,采样间隔大于 1 天时会被当成收益(往里加钱像赚了)。
 * 日频让每个自然日都是采样点,等价于逐笔剥离资金进出。
 *
 * 同时把后端的数据质量信息一起带出来(哪些天/哪几只基金的历史记录不完整)——这些天的
 * 赎回回款大于组合实际被移走的市值(早期买入不在导出件里),收益率已按「不产生收益」处理,
 * 卡片上给一行小字说明,免得看着像"白涨/白跌"。
 */
export const usePortfolioTwr = (startDate?: string, endDate?: string) =>
  useQuery<PortfolioTwrResult>({
    queryKey: ['portfolio-twr', startDate, endDate],
    queryFn: () =>
      api
        .get('/portfolio/analytics/comparison', {
          // endDate 只在前端选了自定义区间时给:不给则后端取到今天,序列会延伸出自定义区间
          params: {
            start_date: startDate,
            end_date: endDate,
            interval_days: 1,
          },
        })
        .then((res) => {
          const body = res as unknown as TwrResponse;
          const dates = body.dates ?? [];
          const points = dates
            .map((date, i) => ({
              date,
              value: Number(((body.twr?.[i] ?? 100) - 100).toFixed(2)),
              hasHoldings: (body.portfolioValue?.[i] ?? 0) > 0,
            }))
            // 建仓前市值为 0 的那段:后端 twr 停在 100(即 0%),照着画会得到一条假的「0% 平线」,
            // 故按「有市值才算有数据」剔除,让图表在建仓前自然断线
            .filter((point) => point.hasHoldings)
            .map(({ date, value }) => ({ date, value }));
          return {
            points,
            incompleteDates: body.dataQuality?.incompleteDates ?? [],
            gapFunds: body.dataQuality?.funds ?? [],
          };
        }),
    staleTime: 5 * 60 * 1000,
    // 起点由基准序列首日给出,未就绪(含空串)时不发注定落空的请求
    enabled: Boolean(startDate),
  });

// ===== 逐基金日收益(昨日/今日双档并列) =====

export type DailyFundProfitRow = {
  fundCode: string;
  fundName: string;
  nav: number;
  prevNav: number;
  shares: number;
  dailyProfit: number;
  navDate: string;
  prevNavDate: string;
};

export type DailyFundProfit = {
  latestNavDate: string;
  prevNavDate: string;
  latest: DailyFundProfitRow[];
  prev: DailyFundProfitRow[];
};

/**
 * 逐基金日收益两档并列:latest = 最新净值日(「今日」档)、prev = 上一净值日(「昨日」档)。
 * 净值 T+1 发布后今日档滚动到新净值日,昨日档固定留在上一净值日不再被覆盖——
 * 替代旧方案(list 行 dailyProfit 滚动单值 + 前端按日历日过滤 latestNavDate,昨日档恒空)。
 * 每只基金按自身净值序列独立计算,顶层日期取各行最大值(个别基金发布不同步时以行为准)。
 */
export const useDailyFundProfit = () =>
  useQuery<DailyFundProfit>({
    queryKey: ['daily-fund-profit'],
    queryFn: async () => {
      const body = (await api.get(
        '/portfolio/analytics/daily-fund-profit',
      )) as unknown as DailyFundProfit;
      return {
        latestNavDate: body.latestNavDate ?? '',
        prevNavDate: body.prevNavDate ?? '',
        latest: body.latest ?? [],
        prev: body.prev ?? [],
      };
    },
    staleTime: 5 * 60 * 1000,
  });

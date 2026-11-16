// src/features/funds/api/get-fund-yield-chart.ts —— 基金收益率曲线数据层
// 对齐后端 module_fund:GET /fund/chart/yield-curve(复权净值视图,仅登录,限流 60/60s)
// 响应 data 内键为 snake_case(ChartService 透传缓存里的 dict,不经 CamelCaseUtil),
// 类型必须按 snake_case 声明,前端不自造中间命名
import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api-client';

// ===== 类型 =====

/** 单条复权净值记录(accum_nav 归一化 1.0 起步,与指数基准曲线同构) */
export type FundYieldPoint = {
  nav_date: string; // yyyy-MM-dd
  unit_nav: number; // 复权单位净值
  accum_nav: number; // 归一化净值(首日=1.0)
  daily_yield: number; // 日涨跌幅(%)
};

/** 货币基金单条记录:无净值,is_money_fund 时 data 换成七日年化序列 */
export type MoneyYieldPoint = {
  nav_date: string; // yyyy-MM-dd
  annualized_7d: number; // 七日年化收益率(%)
};

/** 曲线响应:{fund_code, period, data}——data 键 snake_case,外层键为手工驼峰 dict */
export type FundYieldChart = {
  fund_code: string;
  period: string;
  data: FundYieldPoint[] | MoneyYieldPoint[];
  /** 货币基金标记:收益卡据此切换为「七日年化走势」单线视图,不取基准对比 */
  is_money_fund?: boolean;
};

// ===== 查询 =====

/**
 * 基金复权收益率曲线(基金详情页收益率卡片数据源)。
 * 行情走三级缓存(Redis 1h),前端 5 分钟内不重取即可保持新鲜;
 * fundCode 未就绪(详情档案未加载)时不发请求,避免注定落空的调用。
 */
export const useFundYieldChart = (fundCode?: string, period?: string) =>
  useQuery({
    queryKey: ['fund-yield-chart', fundCode, period],
    queryFn: () =>
      api
        .get('/fund/chart/yield-curve', {
          params: { fund_code: fundCode, period },
        })
        .then((res) => res as unknown as FundYieldChart),
    staleTime: 5 * 60 * 1000,
    enabled: fundCode != null,
  });

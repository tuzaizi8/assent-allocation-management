// src/features/funds/api/get-index-yields-chart.ts —— 指数收益率曲线数据层
// 对齐后端 module_fund:GET /fund/chart/index-yields(公共数据,仅登录,限流 60/60s)
// 响应 data 内键为 snake_case(ChartService 透传缓存里的 dict,不经 CamelCaseUtil),
// 类型必须按 snake_case 声明,前端不自造中间命名
import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api-client';

// ===== 类型 =====

/** 单条行情记录(归一化净值 accum_nav 从 1.0 起步,与基金收益率曲线同构) */
export type IndexYieldPoint = {
  nav_date: string; // yyyy-MM-dd
  close: number; // 收盘点位
  accum_nav: number; // 收盘点位÷首日收盘的归一化值
  daily_yield: number; // 日涨跌幅(%)
};

/** 曲线响应:{indexName, period, data}——data 键 snake_case,外层键为手工驼峰 dict */
export type IndexYieldChart = {
  indexName: string;
  period: string;
  data: IndexYieldPoint[];
};

// ===== 查询 =====

export type IndexYieldChartParams = {
  /** 指数名称(如 沪深300),清单由 GET /index/list 提供 */
  indexName?: string;
  /** 时间档,与后端 filter_records_by_period 同源(GET /fund/periods 下发),非法值宽松处理为全量 */
  period?: string;
  /** 自定义区间起始日(yyyy-MM-dd):与 endDate 同给时后端忽略 period,按区间过滤 */
  startDate?: string;
  /** 自定义区间结束日(yyyy-MM-dd) */
  endDate?: string;
};

export const getIndexYieldChart = (params: IndexYieldChartParams) =>
  api
    .get('/fund/chart/index-yields', {
      params: {
        indexName: params.indexName,
        period: params.period,
        start_date: params.startDate,
        end_date: params.endDate,
      },
    })
    .then((res) => res as unknown as IndexYieldChart);

/**
 * 指数收益率曲线(仪表盘基准线数据源)。
 * 行情缓存 TTL 6h 且日频数据,前端 5 分钟内不重取即可保持新鲜;
 * 指数名未就绪(清单未加载)时不发请求,避免注定落空的调用。
 * 传了 startDate/endDate 即自定义区间(后端起评比 period 高,period 仅作回显)。
 */
export const useIndexYieldChart = (
  indexName?: string,
  period?: string,
  startDate?: string,
  endDate?: string,
) =>
  useQuery({
    queryKey: ['index-yield-chart', indexName, period, startDate, endDate],
    queryFn: () =>
      getIndexYieldChart({ indexName, period, startDate, endDate }),
    staleTime: 5 * 60 * 1000,
    enabled: indexName != null,
  });

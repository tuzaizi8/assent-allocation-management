// src/features/analytics/lib/period.ts —— 档位 → 起始日期
// 档位清单由 GET /fund/periods 下发(近 1 月/3 月/.../今年来/成立以来),与后端
// chart_service 的 PERIOD_DELTAS/PERIOD_YTD 同源。前端复刻换算,是因为 risk-metrics
// 接口只收日期,而 filter_records_by_period 是图表专用的内存过滤,不是日期换算接口。
import { formatDate } from '@/utils/format';

/** 全量起点:沪深300 指数与公募基金净值数据的年代下限;service 会裁剪未建仓的前导段 */
const FULL_HISTORY_START = '2004-01-01';

/** 周档 → 天数;月/年档 → 步长(与后端 relativedelta 对齐,自然月/自然年) */
const WEEK_DAYS: Record<string, number> = { '1周': 7 };
const MONTH_STEPS: Record<string, number> = { '1月': 1, '3月': 3, '6月': 6 };
const YEAR_STEPS: Record<string, number> = { '1年': 1, '3年': 3, '5年': 5 };
const PERIOD_YTD = '今年来';

/**
 * 档位 → 起始日期(yyyy-MM-dd)。
 * 「成立以来」返回数据年代下限(而非 null):后端对缺省 start_date 会默认取近一年,
 * 与"成立以来"语义相悖;多余的早期日期由后端裁剪到组合首个有市值的交易日。
 */
export const periodToStartDate = (
  period: string,
  today = new Date(),
): string => {
  const d = new Date(today);
  if (period in WEEK_DAYS) {
    d.setDate(d.getDate() - WEEK_DAYS[period]);
    return formatDate(d);
  }
  if (period in MONTH_STEPS) {
    d.setMonth(d.getMonth() - MONTH_STEPS[period]);
    return formatDate(d);
  }
  if (period in YEAR_STEPS) {
    d.setFullYear(d.getFullYear() - YEAR_STEPS[period]);
    return formatDate(d);
  }
  if (period === PERIOD_YTD) {
    d.setMonth(0, 1);
    return formatDate(d);
  }
  // 「成立以来」与未识别档位都退化为全量起点('2004-01-01',旧客户端缓存的档位值同此):
  // 与后端 filter 的同策略一致;组合未建仓的前导零段由后端裁剪,不影响指标
  return FULL_HISTORY_START;
};

/** 自定义区间的哨兵档位:只存在于本地下拉,不是后端档位(GET /fund/periods 不含它) */
export const PERIOD_CUSTOM = '自定义';

/**
 * 自定义区间的初值:与两卡的默认档位(1年)一致,选「自定义」时不必先面对两个空字段。
 */
export const defaultCustomRange = (today = new Date()) => ({
  start: periodToStartDate('1年', today),
  end: formatDate(today),
});

export type CustomRange = { start: string; end: string };

/**
 * 把可能不完整/反序的区间补成可用区间:空值(日期字段自带的清除按钮)回退默认,
 * 起晚于止则对调——空串直接请求会让后端的 date 参数 422。
 */
export const normalizeCustomRange = (
  range: CustomRange,
  today = new Date(),
): CustomRange => {
  const fallback = defaultCustomRange(today);
  let start = range.start || fallback.start;
  let end = range.end || fallback.end;
  // yyyy-MM-dd 的字典序即时间序,不用再转 Date
  if (start > end) [start, end] = [end, start];
  return { start, end };
};

// src/features/analytics/lib/metric-items.ts —— 关键指标卡配置(纯函数,可单测)
// 页顶只留 **6 张最有用的卡**(年化波动率/最大回撤/夏普/索提诺/信息比率/胜率),
// 其余指标已图表化:滚动波动率/滚动夏普/收益分布直方图(VaR·CVaR 标线);
// 被移除的卡玛/贝塔/跟踪误差并入副文本,最长回撤持续期并入最大回撤卡副文本。
import { trendClass } from '@/utils/format';

import type { RiskMetrics } from '../api/get-risk-metrics';

export type MetricItem = {
  key: string;
  label: string;
  /** 主数值(已带单位);null → 「—」 */
  value: string;
  /** 副文本(灰字);无则不渲染 */
  subtext?: string;
  /** 主数值着色:红涨绿跌走语义 token,纯风险量中性 */
  tone: string;
};

const pct = (v: number | null) => (v == null ? '—' : `${v.toFixed(2)}%`);
const num = (v: number | null) => (v == null ? '—' : v.toFixed(2));
/** 有方向的指标:正=红、负=绿、零/缺失=中性(与金额同口径) */
const directional = (v: number | null) => (v == null ? '' : trendClass(v));
/** 最大回撤卡副文本:完整起止日期 + 修复天数(只写 MM-DD 会看不出是哪一年) */
const drawdownSub = (m: RiskMetrics): string => {
  if (m.maxDrawdownStart == null) return '观察期内无回撤';
  const span = `${m.maxDrawdownStart} ~ ${m.maxDrawdownEnd ?? '至今'}`;
  const recovery =
    m.recoveryDays == null ? '回撤中' : `修复 ${m.recoveryDays} 天`;
  return `${span} · ${recovery}`;
};

export function buildRiskMetricItems(m: RiskMetrics): MetricItem[] {
  return [
    {
      key: 'annualVolatility',
      label: '年化波动率',
      value: pct(m.annualVolatility),
      subtext:
        m.downsideVolatility == null
          ? undefined
          : `下行波动率 ${pct(m.downsideVolatility)}`,
      tone: '',
    },
    {
      key: 'maxDrawdown',
      label: '最大回撤',
      value: pct(m.maxDrawdown),
      subtext: drawdownSub(m),
      tone: 'text-loss',
    },
    {
      key: 'sharpe',
      label: '夏普比率',
      value: num(m.sharpe),
      subtext: `无风险利率 ${m.riskFreeRate.toFixed(2)}%`,
      tone: directional(m.sharpe),
    },
    {
      key: 'sortino',
      label: '索提诺比率',
      value: num(m.sortino),
      subtext: m.calmar == null ? undefined : `卡玛 ${m.calmar.toFixed(2)}`,
      tone: directional(m.sortino),
    },
    {
      key: 'informationRatio',
      label: '信息比率',
      value: num(m.informationRatio),
      subtext:
        m.beta == null
          ? undefined
          : `β ${m.beta.toFixed(2)}${
              m.trackingError == null ? '' : ` · TE ${pct(m.trackingError)}`
            }`,
      tone: directional(m.informationRatio),
    },
    {
      key: 'winRate',
      label: '胜率',
      value: pct(m.winRate),
      subtext: '收益为正的交易日占比',
      tone: '',
    },
  ];
}

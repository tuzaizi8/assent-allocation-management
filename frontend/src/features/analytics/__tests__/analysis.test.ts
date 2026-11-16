// 持仓分析页纯函数单测:档位→起始日期换算、关键指标条(6 卡)。不渲染 recharts。
import { scaleThreshold } from 'd3-scale';
import { describe, expect, test } from 'vitest';

import type {
  DateValue,
  DrawdownPoint,
  RiskMetrics,
} from '@/features/analytics/api/get-risk-metrics';
import { badgeWidth } from '@/features/analytics/components/chart-badge';
import {
  buildEquitySeries,
  recoveryLabel,
} from '@/features/analytics/components/equity-return-chart';
import {
  buildHeatmapCells,
  HEATMAP_COLOR_DOMAIN,
  HEATMAP_COLOR_RANGE,
  HEATMAP_LEGEND_LABELS,
  HEATMAP_MARGIN,
  HEATMAP_NULL_COLOR_VALUE,
  HEATMAP_ROW_HEIGHT,
  HEATMAP_ZERO_BAND,
  heatmapHeight,
} from '@/features/analytics/components/monthly-heatmap';
import { METRIC_GLOSSARY } from '@/features/analytics/lib/metric-glossary';
import { buildRiskMetricItems } from '@/features/analytics/lib/metric-items';
import {
  defaultCustomRange,
  normalizeCustomRange,
  periodToStartDate,
} from '@/features/analytics/lib/period';

describe('periodToStartDate(与后端 chart_service 的档位步长同源)', () => {
  // 固定"今天",避免用例随日期漂移
  const today = new Date('2026-09-24T12:00:00');

  test('周/月/年档按自然步长回退', () => {
    expect(periodToStartDate('1周', today)).toBe('2026-09-17');
    expect(periodToStartDate('1月', today)).toBe('2026-08-24');
    expect(periodToStartDate('6月', today)).toBe('2026-03-24');
    expect(periodToStartDate('1年', today)).toBe('2025-09-24');
  });

  test('今年来 → 当年 1 月 1 日;成立以来 → 数据年代下限(后端裁剪未建仓段)', () => {
    expect(periodToStartDate('今年来', today)).toBe('2026-01-01');
    expect(periodToStartDate('成立以来', today)).toBe('2004-01-01');
  });
});

describe('defaultCustomRange / normalizeCustomRange(自定义时间档的初值与兜底)', () => {
  const today = new Date('2026-09-24T12:00:00');

  test('初值 = 近一年(与两卡默认档位一致,选中自定义不先面对空字段)', () => {
    expect(defaultCustomRange(today)).toEqual({
      start: '2025-09-24',
      end: '2026-09-24',
    });
  });

  test('空值回退默认:日期字段的清除按钮清空后,不能把空串发给后端', () => {
    const fallback = defaultCustomRange(today);
    expect(
      normalizeCustomRange({ start: '', end: '2026-03-01' }, today),
    ).toEqual({ start: fallback.start, end: '2026-03-01' });
    expect(
      normalizeCustomRange({ start: '2026-03-01', end: '' }, today),
    ).toEqual({ start: '2026-03-01', end: fallback.end });
  });

  test('反序区间对调(yyyy-MM-dd 的字典序即时间序)', () => {
    expect(
      normalizeCustomRange({ start: '2026-06-01', end: '2026-03-01' }, today),
    ).toEqual({ start: '2026-03-01', end: '2026-06-01' });
  });

  test('有序区间原样返回', () => {
    const range = { start: '2026-01-05', end: '2026-03-01' };
    expect(normalizeCustomRange(range, today)).toEqual(range);
  });
});

// 最小可用 RiskMetrics 桩:「关键指标卡」与「讲解文案覆盖」两组测试共用
const metrics: RiskMetrics = {
  annualVolatility: 12.34,
  maxDrawdown: -20.0,
  maxDrawdownStart: '2026-01-02',
  maxDrawdownValley: '2026-01-02',
  maxDrawdownEnd: '2026-01-02',
  recoveryDays: 3,
  longestDrawdownDays: 5,
  sharpe: 1.234,
  sortino: 1.8,
  calmar: 0.9,
  downsideVolatility: 8.5,
  winRate: 55.5,
  var: -1.9,
  cvar: -2.4,
  informationRatio: 0.4,
  beta: 0.8,
  alpha: 0.02,
  trackingError: 5.6,
  riskFreeRate: 1.28,
};

describe('buildRiskMetricItems(精简后的 6 张关键卡)', () => {
  test('恰好 6 项,其余指标已图表化或并入副文本', () => {
    const items = buildRiskMetricItems(metrics);
    expect(items).toHaveLength(6);
    expect(new Set(items.map((i) => i.key)).size).toBe(6);
    expect(items.map((i) => i.key)).toEqual([
      'annualVolatility',
      'maxDrawdown',
      'sharpe',
      'sortino',
      'informationRatio',
      'winRate',
    ]);
  });

  test('被移除的指标并入副文本:卡玛/贝塔·跟踪误差', () => {
    const items = buildRiskMetricItems(metrics);
    const byKey = Object.fromEntries(items.map((i) => [i.key, i]));
    // 最大回撤副文本:完整起止日期(只写 MM-DD 看不出年份),且不再带「最长持续 N 天」
    expect(byKey.maxDrawdown?.subtext).toBe(
      '2026-01-02 ~ 2026-01-02 · 修复 3 天',
    );
    expect(byKey.sortino?.subtext).toContain('卡玛 0.90');
    expect(byKey.informationRatio?.subtext).toContain('β 0.80');
    expect(byKey.informationRatio?.subtext).toContain('TE 5.60%');
    // 无风险利率来自接口(动态),不是写死的 1.5%
    expect(byKey.sharpe?.subtext).toBe('无风险利率 1.28%');
  });

  test('着色:最大回撤绿色(loss),夏普为正红色(profit),null 显示「—」', () => {
    const items = buildRiskMetricItems(metrics);
    const byKey = Object.fromEntries(items.map((i) => [i.key, i]));
    expect(byKey.maxDrawdown?.tone).toBe('text-loss');
    expect(byKey.sharpe?.tone).toBe('text-profit');
    const ir = buildRiskMetricItems({ ...metrics, trackingError: null }).find(
      (i) => i.key === 'informationRatio',
    );
    expect(ir?.subtext ?? '').not.toContain('TE');
  });
});

describe('buildHeatmapCells(年 × 13 格热力图矩阵)', () => {
  const rows = [
    {
      year: 2026,
      months: [
        1.2,
        null,
        -0.5,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
      ],
      yearTotal: 0.7,
    },
    { year: 2025, months: Array(12).fill(null), yearTotal: null },
  ];

  test('扁平化数量 = 年数 × 13(12 月 + 全年列)', () => {
    const cells = buildHeatmapCells(rows);
    expect(cells).toHaveLength(2 * 13);
  });

  test('全年列(monthIdx=12)取 yearTotal;null 月保留 null 且色阶输入走 null 哨兵', () => {
    const cells = buildHeatmapCells(rows);
    const yearTotalCell = cells.find(
      (c) => c.year === '2026' && c.monthIdx === 12,
    );
    expect(yearTotalCell).toMatchObject({ value: 0.7, colorValue: 0.7 });
    const nullMonth = cells.find((c) => c.year === '2026' && c.monthIdx === 1);
    expect(nullMonth).toMatchObject({
      value: null,
      colorValue: HEATMAP_NULL_COLOR_VALUE,
    });
  });

  test('全年为 null 的年份同样保留灰格', () => {
    const cell2025 = buildHeatmapCells(rows).find(
      (c) => c.year === '2025' && c.monthIdx === 12,
    );
    expect(cell2025).toMatchObject({
      value: null,
      colorValue: HEATMAP_NULL_COLOR_VALUE,
    });
  });

  test('色阶不变式:哨兵独占 null 桶,且档数比阈值多一', () => {
    // 这条守住「null 与 0% 分色」:调色阶下限时若哨兵不再小于下限,null 会被涂成亏损色
    expect(HEATMAP_NULL_COLOR_VALUE).toBeLessThan(HEATMAP_COLOR_DOMAIN[0] ?? 0);
    expect(HEATMAP_COLOR_RANGE).toHaveLength(HEATMAP_COLOR_DOMAIN.length + 1);
  });

  test('图例与色阶一一对应(跳过 null 桶)', () => {
    expect(HEATMAP_LEGEND_LABELS).toHaveLength(HEATMAP_COLOR_RANGE.length - 1);
  });
});

describe('热力图色阶:灰块只代表恰好 0%,涨跌两侧都有颜色', () => {
  // 用组件同款的 d3 阈值色阶直接验证落桶,而不是只断言常量
  const scale = () =>
    scaleThreshold<number, string>(HEATMAP_COLOR_DOMAIN, HEATMAP_COLOR_RANGE);

  test('恰好 0% 落灰桶', () => {
    expect(scale()(0)).toBe('var(--heat-flat)');
  });

  test('±0.01(后端收益的最小非零幅度)必须落进有颜色的桶', () => {
    expect(scale()(0.01)).toBe('var(--heat-gain-1)');
    expect(scale()(-0.01)).toBe('var(--heat-loss-1)');
  });

  test('微幅涨跌也有颜色,不再被中性带吞掉', () => {
    const s = scale();
    expect(s(0.3)).toBe('var(--heat-gain-1)');
    expect(s(-0.3)).toBe('var(--heat-loss-1)');
    expect(s(1.2)).toBe('var(--heat-gain-1)');
    expect(s(-1.2)).toBe('var(--heat-loss-1)');
  });

  test('0% 灰桶带宽必须小于数据精度步长,否则会误吞 ±0.01 这类真实值', () => {
    // 后端收益保留 2 位小数 → 最小非零幅度 0.01;半宽 0.005 时灰桶是 [-0.005, 0.005)
    expect(HEATMAP_ZERO_BAND).toBeLessThan(0.01);
  });

  test('盈亏两端的极端值与 null 哨兵各自归桶', () => {
    const s = scale();
    expect(s(12)).toBe('var(--heat-gain-5)');
    expect(s(-12)).toBe('var(--heat-loss-5)');
    expect(s(HEATMAP_NULL_COLOR_VALUE)).toBe('var(--heat-null)');
  });
});

describe('heatmapHeight(绘图区高度严格 = 行数 × 行高,格子形状不随年数变)', () => {
  test('行高恒定:任意行数下 (高度 - 上下边距) ÷ 行数 都等于 HEATMAP_ROW_HEIGHT', () => {
    // 这是「1 年/1 月不再被拉长」的核心不变量:库会无条件覆盖 y 轴 range,
    // 所以只能靠高度严格等于 行数 × 行高 来保证格子恒定
    for (let n = 1; n <= 20; n++) {
      const plot =
        heatmapHeight(n) - HEATMAP_MARGIN.top - HEATMAP_MARGIN.bottom;
      expect(plot / n).toBe(HEATMAP_ROW_HEIGHT);
    }
  });

  test('真实档位实测行数:1月→1、1年→2、成立以来→6', () => {
    expect(heatmapHeight(1)).toBe(30 + 12 + 24);
    expect(heatmapHeight(2)).toBe(60 + 12 + 24);
    expect(heatmapHeight(6)).toBe(180 + 12 + 24);
  });

  test('高度随行数单调递增', () => {
    for (let n = 1; n < 20; n++) {
      expect(heatmapHeight(n + 1)).toBeGreaterThan(heatmapHeight(n));
    }
  });
});

describe('buildEquitySeries(收益曲线分段:峰→谷染绿、谷→修复染红)', () => {
  const equity = (values: number[]): DateValue[] =>
    values.map((value, index) => ({
      date: `2026-01-${String(index + 1).padStart(2, '0')}`,
      value,
    }));
  const dd = (values: number[]): DrawdownPoint[] =>
    values.map((value, index) => ({
      date: `2026-01-${String(index + 1).padStart(2, '0')}`,
      dd: value,
    }));

  // dd: 0 → -10 → -20(谷) → -5 → 0(修复完成)
  const series = equity([0, -5, -20, -15.5, -4]);
  const drawdown = dd([0, -10, -20, -5, 0]);

  test('段几何按日期自推:峰取谷底前最后一个未水下日(不是 maxDrawdownStart)', () => {
    const { points, peakIndex, valleyIndex, recoveryEndIndex } =
      buildEquitySeries(series, drawdown);

    expect(peakIndex).toBe(0);
    expect(valleyIndex).toBe(2);
    expect(recoveryEndIndex).toBe(4);
    expect(points.map((p) => p.decline)).toEqual([0, -5, -20, null, null]);
    expect(points.map((p) => p.recovery)).toEqual([null, null, -20, -15.5, -4]);
  });

  test('未修复(dd 始终没回到 0):修复段画到数据末端', () => {
    const { points, recoveryEndIndex } = buildEquitySeries(
      series.slice(0, 4),
      drawdown.slice(0, 4),
    );

    expect(recoveryEndIndex).toBe(3);
    expect(points[3].recovery).toBe(-15.5);
  });

  test('修复文案:未修复「正在修复」,已修复带天数', () => {
    expect(recoveryLabel(null)).toBe('正在修复');
    expect(recoveryLabel(45)).toBe('45 天修复');
  });

  test('边界:全期无水下日 / 两序列长度不一致 → 两段全 null 且不抛错', () => {
    const noDrawdown = buildEquitySeries(series, dd([0, 0, 0, 0, 0]));
    expect(noDrawdown.peakIndex).toBeNull();
    expect(noDrawdown.valleyIndex).toBeNull();
    expect(
      noDrawdown.points.every((p) => p.decline === null && p.recovery === null),
    ).toBe(true);

    const mismatched = buildEquitySeries(series, drawdown.slice(0, 3));
    expect(mismatched.valleyIndex).toBeNull();
    expect(
      mismatched.points.every((p) => p.decline === null && p.recovery === null),
    ).toBe(true);
  });

  test('Badge 估宽:同字数下 CJK 比 ASCII 宽,且随字数递增', () => {
    // 估宽偏小会让 Badge 装不下文字(白字溢出圆角底之外),这条守一下下限
    expect(badgeWidth('正在修复', 11)).toBeGreaterThan(badgeWidth('abcd', 11));
    expect(badgeWidth('45 天修复', 11)).toBeGreaterThan(
      badgeWidth('天修复', 11),
    );
  });
});

describe('METRIC_GLOSSARY(标题后悬浮卡里的指标讲解)', () => {
  // 6 个关键指标 key(与 buildRiskMetricItems 同源)+ 7 个图表小节 key(由页面传入)
  const glossaryKeys = [
    'annualVolatility',
    'maxDrawdown',
    'sharpe',
    'sortino',
    'informationRatio',
    'winRate',
    'annualizedTrend',
    'equityCurve',
    'drawdownCurve',
    'rollingVolatility',
    'returnDistribution',
    'rollingSharpe',
    'monthlyReturns',
  ];

  test('13 条 key 齐全,且每条三个字段都非空', () => {
    expect(Object.keys(METRIC_GLOSSARY).sort()).toEqual(glossaryKeys.sort());

    // 逐条断言会丢掉「到底缺哪条」的信息,这里先收集再一次性比空数组
    const emptyFields = Object.entries(METRIC_GLOSSARY).flatMap(
      ([key, entry]) =>
        (['title', 'what', 'use'] as const)
          .filter((field) => entry[field].length === 0)
          .map((field) => `${key}.${field}`),
    );
    expect(emptyFields).toEqual([]);
  });

  test('关键指标卡产出的每个 key 都有讲解(将来加第 7 张卡时会红)', () => {
    const missing = buildRiskMetricItems(metrics)
      .map((item) => item.key)
      .filter((key) => !(key in METRIC_GLOSSARY));
    expect(missing).toEqual([]);
  });
});

// 仪表盘指标卡单测:四张卡的当前值口径(最新一条快照) + 缺数据降级。
// 只验「快照行 → 卡片数值」这条口径与两种降级形态;走势图属展示层——降级用例里断言的是
// 「卡片内不再出现任何金额」(金额增量与走势线由同一次降级赋值一起收掉)。
// 走势序列给空数组,避免引入 recharts。
import { render, screen, within } from '@testing-library/react';
import { vi } from 'vitest';

import { DashboardCards } from '@/features/dashboard/components/dashboard-cards';

/** 最新快照行(用例各自改写):四张卡的取值来源,列表新→旧故取第一行 */
const snapshotMock = vi.hoisted(() => ({
  rows: [] as {
    snapshotDate: string;
    totalValue: number;
    cumulativeInvested: number | null;
  }[],
}));

vi.mock('@/features/snapshots/api/get-snapshots', () => ({
  useSnapshotList: () => ({ data: { data: snapshotMock.rows, meta: {} } }),
}));

/** 走势序列:保留模块真实导出(weekOverWeek),只替换取数 hook */
const trendMock = vi.hoisted(() => ({
  points: [] as {
    date: string;
    totalValue: number;
    totalInvested: number;
    profit: number;
    profitRate: number;
  }[],
}));

vi.mock(
  '@/features/dashboard/api/get-portfolio-analytics',
  async (importOriginal) => {
    const actual =
      await importOriginal<
        typeof import('@/features/dashboard/api/get-portfolio-analytics')
      >();
    return { ...actual, usePortfolioTrend: () => ({ data: trendMock.points }) };
  },
);

/** 某张卡片(靠 MetricCard 上的 testid 定位,不爬 DOM) */
const cardOf = (label: string) => screen.getByTestId(`metric-${label}`);

const LABELS = ['总市值', '累计投入', '总盈亏', '累计盈亏率'];

beforeEach(() => {
  trendMock.points = [];
});

test('四张卡取最新一条快照,第四张卡是「累计盈亏率」', async () => {
  // 真库 2026-09-22 那一行:7,663.75 − 6,932.16 = 731.59,收益率 10.55%
  snapshotMock.rows = [
    {
      snapshotDate: '2026-09-22',
      totalValue: 7663.75,
      cumulativeInvested: 6932.16,
    },
  ];
  render(<DashboardCards />);

  // 数值带滚动进场:等动画落到终值再断言(直接 getByText 会抓到中间帧)
  expect(
    await within(cardOf('总市值')).findByText('¥7,663.75'),
  ).toBeInTheDocument();
  expect(
    await within(cardOf('累计投入')).findByText('¥6,932.16'),
  ).toBeInTheDocument();
  expect(
    await within(cardOf('总盈亏')).findByText('+¥731.59'),
  ).toBeInTheDocument();
  expect(
    await within(cardOf('累计盈亏率')).findByText('+10.55%'),
  ).toBeInTheDocument();
  // 改名后旧标题不应再出现(图标映射以指标名为键,改名漏同步会让图标消失)
  expect(screen.queryByText('累计收益率')).not.toBeInTheDocument();
});

test('没有快照行:四张卡的值与环比都显示「—」,且不出现任何金额', () => {
  snapshotMock.rows = [];
  render(<DashboardCards />);

  for (const label of LABELS) {
    // 值 + 环比文案各一个破折号:不拿 0 冒充
    expect(within(cardOf(label)).getAllByText('—')).toHaveLength(2);
    // 降级连金额增量与走势线一起收掉,否则会出现「破折号旁边挂着 +¥0.00 与一条线」
    expect(within(cardOf(label)).queryByText(/¥/)).not.toBeInTheDocument();
  }
});

test('该日无现金流行(累计投入为 null):只有总市值可显示,其余三张降级', async () => {
  snapshotMock.rows = [
    {
      snapshotDate: '2026-09-22',
      totalValue: 7663.75,
      cumulativeInvested: null,
    },
  ];
  render(<DashboardCards />);

  expect(
    await within(cardOf('总市值')).findByText('¥7,663.75'),
  ).toBeInTheDocument();
  for (const label of ['累计投入', '总盈亏', '累计盈亏率']) {
    expect(within(cardOf(label)).getAllByText('—')).toHaveLength(2);
  }
});

test('累计盈亏率卡的环比按百分号呈现,不再写「个百分点」', () => {
  // weekOverWeek 要 ≥8 个点才产出周环比:末尾 1.12% 与倒数第 8 点 1% 之差 = +0.12
  snapshotMock.rows = [
    {
      snapshotDate: '2026-09-22',
      totalValue: 7663.75,
      cumulativeInvested: 6932.16,
    },
  ];
  trendMock.points = Array.from({ length: 8 }, (_, index) => ({
    date: `2026-09-${String(15 + index).padStart(2, '0')}`,
    totalValue: 7000,
    totalInvested: 6000,
    profit: 1000,
    profitRate: index === 7 ? 1.12 : 1,
  }));
  render(<DashboardCards />);

  expect(within(cardOf('累计盈亏率')).getByText('+0.12%')).toBeInTheDocument();
  expect(screen.queryByText(/个百分点/)).not.toBeInTheDocument();
});

// 持仓简况页排序单测:默认市值降序,「持有收益率」表头可点切换(同列翻方向、换列从降序开始)。
// 数据由 useAllPositions 一次拉回全量 → 排序是纯客户端;这里 mock 掉两个数据 hook,
// 只验「表头点击 → 行顺序」这条产品行为(卡片定高/截断属展示层,不在断言范围)。
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { vi } from 'vitest';

import PositionsSummaryRoute from '@/app/routes/app/positions-summary';
import { formatDate, signedNum } from '@/utils/format';

/** 本地今天 / 昨天(断言用):动态构造,不写死日期——否则隔天必挂 */
const todayIso = () => formatDate(new Date());
const yesterdayIso = () =>
  formatDate(new Date(Date.now() - 24 * 60 * 60 * 1000));
/** ISO → 页面上的中文式日期文案(如 9月24日) */
const cnDate = (iso: string) =>
  `${Number(iso.slice(5, 7))}月${Number(iso.slice(8, 10))}日`;

const ROWS = [
  {
    positionId: 1,
    fundName: '小市值高收益',
    currentValue: 100,
    profitRate: 30,
    profit: 10,
  },
  {
    positionId: 2,
    fundName: '大市值亏钱',
    currentValue: 900,
    profitRate: -5,
    profit: -5,
  },
  {
    positionId: 3,
    fundName: '中市值中收益',
    currentValue: 500,
    profitRate: 12,
    profit: 2.5,
  },
];

vi.mock('@/features/positions/api/get-positions', () => ({
  useAllPositions: () => ({
    data: ROWS.map((row) => ({
      ...row,
      realizedProfit: 0,
      totalCost: 0,
      totalShares: 0,
      avgCostPrice: 0,
      status: '0',
    })),
    isLoading: false,
  }),
}));

/** 日收益两档(用例可改写):默认无数据 ⇒ 昨日/今日收益显示「—」且不挂净值日标签 */
const dailyProfitMock = vi.hoisted(() => ({
  data: undefined as
    | undefined
    | {
        latestNavDate: string;
        prevNavDate: string;
        latest: { dailyProfit: number }[];
        prev: { dailyProfit: number }[];
      },
}));

vi.mock('@/features/dashboard/api/get-portfolio-analytics', () => ({
  useDailyFundProfit: () => dailyProfitMock,
}));

/** 最新快照行(用例可改写):「累计盈亏」卡的取值来源 */
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

/** 表格当前的行顺序(首列即基金名称;表头行跳过) */
const rowOrder = () =>
  screen
    .getAllByRole('row')
    .slice(1)
    .map((row) => within(row).getAllByRole('cell')[0].textContent);

const renderPage = () =>
  render(
    <MemoryRouter>
      <PositionsSummaryRoute />
    </MemoryRouter>,
  );

test('默认按市值降序(定高卡片截断后留下最大的几支)', () => {
  renderPage();

  expect(rowOrder()).toEqual(['大市值亏钱', '中市值中收益', '小市值高收益']);
});

test('点「持有收益率」→ 按收益率降序;再点 → 升序', async () => {
  const user = userEvent.setup();
  renderPage();

  await user.click(screen.getByRole('button', { name: /持有收益率/ }));
  expect(rowOrder()).toEqual(['小市值高收益', '中市值中收益', '大市值亏钱']);
  // 换列后当前方向为降序,表头应显示单向降序箭头
  expect(screen.getByTestId('sort-icon-desc')).toBeInTheDocument();

  await user.click(screen.getByRole('button', { name: /持有收益率/ }));
  expect(rowOrder()).toEqual(['大市值亏钱', '中市值中收益', '小市值高收益']);
  expect(screen.getByTestId('sort-icon-asc')).toBeInTheDocument();
});

test('累计盈亏取快照口径:快照市值 − 同日累计净投入', async () => {
  snapshotMock.rows = [
    { snapshotDate: '2026-09-18', totalValue: 1500, cumulativeInvested: 1200 },
  ];
  renderPage();

  // 指标块数值带滚动进场:等动画落到终值再断言
  expect(
    await within(screen.getByTestId('metric-累计盈亏（元）')).findByText(
      signedNum(300),
    ),
  ).toBeInTheDocument();
});

test('快照缺失或该日无现金流(累计净投入为 null)时累计盈亏显示「—」,不伪造 0', () => {
  snapshotMock.rows = [
    { snapshotDate: '2026-09-18', totalValue: 1500, cumulativeInvested: null },
  ];
  renderPage();
  expect(
    within(screen.getByTestId('metric-累计盈亏（元）')).getByText('—'),
  ).toBeInTheDocument();

  snapshotMock.rows = [];
  renderPage();
  expect(
    within(screen.getAllByTestId('metric-累计盈亏（元）')[1]).getByText('—'),
  ).toBeInTheDocument();
});

test('持有收益 = 当前持仓的持有收益汇总(Σ profit)', async () => {
  snapshotMock.rows = [];
  renderPage();

  // 三条固定持仓 profit = 10 / -5 / 2.5
  expect(
    await within(screen.getByTestId('metric-持有收益（元）')).findByText(
      signedNum(7.5),
    ),
  ).toBeInTheDocument();
});

test('点「市值」→ 翻转回升序(同列切方向)', async () => {
  const user = userEvent.setup();
  renderPage();

  await user.click(screen.getByRole('button', { name: /市值/ }));

  expect(rowOrder()).toEqual(['小市值高收益', '中市值中收益', '大市值亏钱']);
});

test('今日/昨日收益标签后挂该档净值日(数据没更新时也能看出它指的是哪天)', () => {
  dailyProfitMock.data = {
    latestNavDate: '2026-09-23',
    prevNavDate: '2026-09-22',
    latest: [{ dailyProfit: 12.5 }],
    prev: [{ dailyProfit: -3 }],
  };
  renderPage();

  expect(
    within(screen.getByTestId('metric-今日收益（元）')).getByText('9月23日'),
  ).toBeInTheDocument();
  expect(
    within(screen.getByTestId('metric-昨日收益（元）')).getByText('9月22日'),
  ).toBeInTheDocument();
  // 另外两格没有「哪一天」的概念,不挂日期标签
  expect(
    within(screen.getByTestId('metric-持有收益（元）')).queryByText('9月23日'),
  ).not.toBeInTheDocument();
});

test('某档无数据:数值显示「—」且不挂净值日(不会出现有日期没数值)', () => {
  // 昨日档空(建仓不足两个净值日):后端仍会给出日期串,但该档没数据 ⇒ 不挂标签
  dailyProfitMock.data = {
    latestNavDate: '2026-09-23',
    prevNavDate: '2026-09-22',
    latest: [{ dailyProfit: 12.5 }],
    prev: [],
  };
  renderPage();

  const yesterdayBlock = screen.getByTestId('metric-昨日收益（元）');
  expect(within(yesterdayBlock).getByText('—')).toBeInTheDocument();
  expect(within(yesterdayBlock).queryByText('9月22日')).not.toBeInTheDocument();
  // 今日档有数据,照常挂
  expect(
    within(screen.getByTestId('metric-今日收益（元）')).getByText('9月23日'),
  ).toBeInTheDocument();
});

/** 今日档(净值日 = 传入日期)的 mock;收益符号决定是否上红/绿 */
const todayBucket = (navDate: string, dailyProfit: number) => ({
  latestNavDate: navDate,
  prevNavDate: navDate,
  latest: [{ dailyProfit }],
  prev: [{ dailyProfit: 1 }],
});

test('净值日就是今天:今日收益 Badge 标「已更新」并按正收益着红', () => {
  const today = todayIso();
  dailyProfitMock.data = todayBucket(today, 12.5);
  renderPage();

  const badge = within(screen.getByTestId('metric-今日收益（元）')).getByText(
    `${cnDate(today)} 已更新`,
  );
  expect(badge).toHaveClass('text-profit', 'bg-profit/10');
});

test('净值日就是今天:今日收益为负时 Badge 着绿', () => {
  const today = todayIso();
  dailyProfitMock.data = todayBucket(today, -8);
  renderPage();

  const badge = within(screen.getByTestId('metric-今日收益（元）')).getByText(
    `${cnDate(today)} 已更新`,
  );
  expect(badge).toHaveClass('text-loss');
});

test('净值日不是今天(如过了零点):Badge 退回灰色且不带「已更新」', () => {
  const yesterday = yesterdayIso();
  dailyProfitMock.data = todayBucket(yesterday, 12.5);
  renderPage();

  const badge = within(screen.getByTestId('metric-今日收益（元）')).getByText(
    cnDate(yesterday),
  );
  expect(screen.queryByText(/已更新/)).not.toBeInTheDocument();
  expect(badge).not.toHaveClass('text-profit');
  expect(badge).not.toHaveClass('text-loss');
});

test('脱敏(隐藏金额)时:Badge 保留「已更新」但不上色,不泄露涨跌方向', async () => {
  const user = userEvent.setup();
  const today = todayIso();
  dailyProfitMock.data = todayBucket(today, 12.5);
  renderPage();

  await user.click(screen.getByRole('button', { name: '隐藏金额' }));

  const badge = within(screen.getByTestId('metric-今日收益（元）')).getByText(
    `${cnDate(today)} 已更新`,
  );
  expect(badge).not.toHaveClass('text-profit');
  expect(badge).not.toHaveClass('bg-profit/10');
});

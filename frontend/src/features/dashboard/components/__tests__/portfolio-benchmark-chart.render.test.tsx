// 收益率对比卡的渲染用例:钉"两序列都就绪前不画图"与"数据质量提示已搬进标题后的浮层"。
// 不断言图表内部(recharts 在 jsdom 下不渲染 svg),只断言占位、图例文案与浮层触发器。
//
// 背景:组合查询的起点依赖基准首日(enabled=false 起步)⇒ 基准必然先到;若这段窗口里
// 先按「组合无数据」兜底画出基准全量轴,随后会被裁剪后的共同起点一拽(还带域过渡动画),
// 使用者看到的就是"先铺满 2004 年、再被拽回来"。故渲染层用 chartReady 门控。
import { render, screen } from '@testing-library/react';
import { vi } from 'vitest';

import { TooltipProvider } from '@/components/ui/tooltip';
import { PortfolioBenchmarkChart } from '@/features/dashboard/components/portfolio-benchmark-chart';

/** 卡片里的警示图标用 Radix Tooltip(必须处于 Provider 内,应用壳在 provider.tsx 全局挂) */
const renderChart = () =>
  render(
    <TooltipProvider>
      <PortfolioBenchmarkChart />
    </TooltipProvider>,
  );

/** undefined = 该查询还没就绪(与 TanStack 的 data 语义一致) */
const state = vi.hoisted(() => ({
  benchmark: undefined as
    undefined | { data: { nav_date: string; accum_nav: number }[] },
  twr: undefined as
    | undefined
    | {
        points: { date: string; value: number }[];
        /** 数据不完整的日期(有值时标题后出现警示图标) */
        incompleteDates?: string[];
        gapFunds?: string[];
      },
}));

vi.mock('@/features/indices/api/get-indices', () => ({
  useIndices: () => ({
    data: [{ indexCode: '000300', indexName: '沪深300', syncStatus: '1' }],
    isLoading: false,
  }),
}));

vi.mock('@/features/funds/api/get-funds', () => ({
  useFundPeriods: () => ({ data: ['1年', '成立以来'] }),
}));

vi.mock('@/features/funds/api/get-index-yields-chart', () => ({
  useIndexYieldChart: () => ({
    data: state.benchmark,
    isLoading: state.benchmark == null,
  }),
}));

vi.mock(
  '@/features/dashboard/api/get-portfolio-analytics',
  async (importOriginal) => {
    const actual =
      await importOriginal<
        typeof import('@/features/dashboard/api/get-portfolio-analytics')
      >();
    return {
      ...actual,
      usePortfolioTwr: () => ({
        data: state.twr,
        isLoading: state.twr == null,
      }),
    };
  },
);

test('基准就绪但组合还没到:先出加载占位,绝不先画「基准全量轴」', () => {
  // 基准是沪深300 的全量历史(2004 起),组合序列尚未返回
  state.benchmark = {
    data: [
      { nav_date: '2004-01-02', accum_nav: 1000 },
      { nav_date: '2021-03-01', accum_nav: 4000 },
    ],
  };
  state.twr = undefined;

  renderChart();

  expect(screen.getByTestId('benchmark-chart-loading')).toBeInTheDocument();
  // 图例与数据质量提示整块都不在:没有画出任何一条线
  expect(screen.queryByText('我的')).not.toBeInTheDocument();
  // 「暂无持仓数据」是"真·无数据"的文案,加载中不许出现(否则把 pending 说成没持仓)
  expect(screen.queryByText('暂无持仓数据')).not.toBeInTheDocument();
  expect(screen.getByText('数据加载中…')).toBeInTheDocument();
});

test('两条线都就绪:占位消失,图例出现(含当前选中的指数名)', () => {
  state.benchmark = { data: [{ nav_date: '2021-03-01', accum_nav: 4000 }] };
  state.twr = { points: [{ date: '2021-03-01', value: 0 }] };

  renderChart();

  expect(
    screen.queryByTestId('benchmark-chart-loading'),
  ).not.toBeInTheDocument();
  expect(screen.queryByText('数据加载中…')).not.toBeInTheDocument();
  expect(screen.getByText('我的')).toBeInTheDocument();
  // 指数名会同时出现在下拉框与图例里(上一轮把图例的「基准」换成了指数名)
  expect(screen.getAllByText('沪深300').length).toBeGreaterThanOrEqual(2);
});

test('有缺口日期时:提示不再压在卡片底部,改为标题后的警示图标 + 浮层', () => {
  state.benchmark = { data: [{ nav_date: '2021-03-01', accum_nav: 4000 }] };
  state.twr = {
    points: [{ date: '2021-03-01', value: 0 }],
    incompleteDates: ['2026-09-20'],
    gapFunds: ['002963'],
  };

  renderChart();

  // 正文零命中即可证明"已从卡片底部搬走":Radix 的浮层内容在未打开时不渲染,
  // 若还留在正文就会命中(这条不依赖 hover 模拟,稳定)
  expect(screen.queryByText(/数据不完整/)).not.toBeInTheDocument();
  // 标题后的警示图标(浮层触发器)已挂上
  expect(screen.getByTestId('benchmark-gap-alert')).toBeInTheDocument();
});

// 收益率对比卡的轴与归一化单测:只钉纯函数(不渲染 recharts)。
// 口径:起点取两条线首日中**更晚**者(只展示最晚成立的),两条线按该共同起点重归一化为 0%。
import { buildBenchmarkPoints } from '@/features/dashboard/components/portfolio-benchmark-chart';

test('组合晚于基准:轴取组合日期,指数更早的部分不展示,基准按起点归一化', () => {
  // 常态:组合 2021-03-01 建仓,沪深300 从 2004 年就有数据
  const benchmark = [
    { nav_date: '2004-01-02', accum_nav: 1000 },
    { nav_date: '2021-03-01', accum_nav: 4000 },
    { nav_date: '2021-03-02', accum_nav: 4040 },
    { nav_date: '2021-03-03', accum_nav: 4400 },
  ];
  const portfolio = [
    { date: '2021-03-01', value: 0 },
    { date: '2021-03-02', value: 1 },
    { date: '2021-03-03', value: 10 },
  ];

  const points = buildBenchmarkPoints(benchmark, portfolio);

  // 轴 = 组合日期(3 点),2004 那根不出现
  expect(points.map((point) => point.date)).toEqual([
    '2021-03-01',
    '2021-03-02',
    '2021-03-03',
  ]);
  // 两条线同一天同从 0% 起步
  expect(points[0]).toEqual({
    date: '2021-03-01',
    portfolio: 0,
    benchmark: 0,
  });
  // 基准改为「自共同起点算」:4000 → 4400 即 +10%(不再是自 2004 年算的 +340%)
  expect(points[2].benchmark).toBe(10);
  expect(points[1].benchmark).toBe(1);
  expect(points[2].portfolio).toBe(10);
});

test('基准晚于组合:轴取基准日期,组合重算到起点 0%(而非带着建仓以来的涨幅)', () => {
  // 反向情形:指数只有 2025 年以来的数据,组合 2021 年就建仓了
  const benchmark = [
    { nav_date: '2025-01-02', accum_nav: 5000 },
    { nav_date: '2025-01-03', accum_nav: 5250 },
  ];
  const portfolio = [
    { date: '2021-03-01', value: 0 },
    { date: '2025-01-02', value: 5 },
    { date: '2025-01-03', value: 10 },
  ];

  const points = buildBenchmarkPoints(benchmark, portfolio);

  expect(points.map((point) => point.date)).toEqual([
    '2025-01-02',
    '2025-01-03',
  ]);
  // 起点处组合的 +5% 被归一化为 0,否则两线起点不同、不可比
  expect(points[0]).toEqual({
    date: '2025-01-02',
    portfolio: 0,
    benchmark: 0,
  });
  // (1.10 / 1.05 − 1) × 100 = 4.76;基准 5250/5000 − 1 = 5%
  expect(points[1].portfolio).toBe(4.76);
  expect(points[1].benchmark).toBe(5);
});

test('基准无数据:轴用组合日期,基准线全为 null', () => {
  const points = buildBenchmarkPoints(
    [],
    [
      { date: '2021-03-01', value: 0 },
      { date: '2021-03-02', value: 3.5 },
    ],
  );

  expect(points).toEqual([
    { date: '2021-03-01', portfolio: 0, benchmark: null },
    { date: '2021-03-02', portfolio: 3.5, benchmark: null },
  ]);
});

test('组合无数据:轴用基准日期,组合线全为 null,基准从自身首日 0% 起', () => {
  const points = buildBenchmarkPoints(
    [
      { nav_date: '2004-01-02', accum_nav: 1000 },
      { nav_date: '2004-01-05', accum_nav: 1100 },
    ],
    [],
  );

  expect(points).toEqual([
    { date: '2004-01-02', portfolio: null, benchmark: 0 },
    { date: '2004-01-05', portfolio: null, benchmark: 10 },
  ]);
});

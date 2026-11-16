// 持仓占比饼图的聚合单测:钉"前 9 大 + 其他、最多 10 片"的口径。
// buildShareSlices 是纯函数(只读 fundName/currentValue),不渲染 recharts。
import type { PositionDetail } from '@/features/positions/api/get-positions';
import {
  buildShareSlices,
  topFundsShare,
} from '@/features/positions/components/portfolio-share-pie';

/** 构造最小持仓行(函数只消费 fundName/currentValue) */
const position = (fundName: string, currentValue: number) =>
  ({ fundName, currentValue }) as PositionDetail;

/** 真实分布(2026-09-23 快照,18 支,按市值降序) */
const REAL_18 = [
  2038.4, 875.2, 832.4, 563.3, 503.5, 501.2, 469.8, 429.2, 352.5, 292.9, 257.2,
  100.6, 94.4, 93.3, 91, 90.5, 53.4, 25.1,
];

test('18 支:恰好 10 片——前 9 大实名,「其他」= 剩余 9 支之和(约 18.9%)', () => {
  const slices = buildShareSlices(
    REAL_18.map((value, index) => position(`基金${index + 1}`, value)),
  );

  expect(slices).toHaveLength(10);
  expect(slices[9].fundName).toBe('其他');
  // 「其他」的市值 = 第 10~18 名之和,占比即其占总市值比例
  const restSum = REAL_18.slice(9).reduce((sum, value) => sum + value, 0);
  expect(slices[9].value).toBeCloseTo(restSum, 6);
  const total = REAL_18.reduce((sum, value) => sum + value, 0);
  expect(slices[9].percent).toBeCloseTo(restSum / total, 12);
  // 前 9 片保持实名与原值
  slices.slice(0, 9).forEach((slice, index) => {
    expect(slice.fundName).toBe(`基金${index + 1}`);
    expect(slice.value).toBe(REAL_18[index]);
  });
  expect(slices.reduce((sum, slice) => sum + slice.percent, 0)).toBeCloseTo(
    1,
    12,
  );
});

test('30 支:仍是 10 片,「其他」= 剩余 21 支之和', () => {
  const values = Array.from({ length: 30 }, (_, index) => 1000 - index * 25);
  const slices = buildShareSlices(
    values.map((value, index) => position(`基金${index + 1}`, value)),
  );

  expect(slices).toHaveLength(10);
  const restSum = values.slice(9).reduce((sum, value) => sum + value, 0);
  expect(slices[9].fundName).toBe('其他');
  expect(slices[9].value).toBeCloseTo(restSum, 6);
  // 前 9 大互不重叠地各自成片
  expect(slices.slice(0, 9).map((slice) => slice.value)).toEqual(
    values.slice(0, 9),
  );
});

test('10 支及以下:全部实名展示,不出现「其他」', () => {
  const ten = buildShareSlices(
    Array.from({ length: 10 }, (_, index) =>
      position(`基金${index + 1}`, 100 - index),
    ),
  );
  expect(ten).toHaveLength(10);
  expect(ten.every((slice) => slice.fundName !== '其他')).toBe(true);

  const nine = buildShareSlices(
    Array.from({ length: 9 }, (_, index) =>
      position(`基金${index + 1}`, 100 - index),
    ),
  );
  expect(nine).toHaveLength(9);
  expect(nine.every((slice) => slice.fundName !== '其他')).toBe(true);
});

test('配色循环:index % 5 取 --pie-1..5,相邻片必不同色', () => {
  const slices = buildShareSlices(
    REAL_18.map((value, index) => position(`基金${index + 1}`, value)),
  );

  slices.forEach((slice, index) => {
    expect(slice.fill).toBe(`var(--pie-${(index % 5) + 1})`);
  });
  for (let i = 1; i < slices.length; i += 1) {
    expect(slices[i].fill).not.toBe(slices[i - 1].fill);
  }
});

// ===== 副标题的集中度口径(topFundsShare) =====

test('18 支:前 10 大占比从全部持仓重算——跨过「其他」边界,不等于 100%', () => {
  const positions = REAL_18.map((value, index) =>
    position(`基金${index + 1}`, value),
  );
  const { count, percent } = topFundsShare(positions);

  expect(count).toBe(10);
  const total = REAL_18.reduce((sum, value) => sum + value, 0);
  const top10 = REAL_18.slice(0, 10).reduce((sum, value) => sum + value, 0);
  expect(percent).toBeCloseTo((top10 / total) * 100, 10);
  // 钉住"没有拿切片求和":切片之和恒为 100%,而前 10 大必然小于全部持仓
  expect(percent).toBeLessThan(100);
});

test('不足 10 支:只数取实际持仓数,占比即全部持仓 = 100%', () => {
  const positions = Array.from({ length: 6 }, (_, index) =>
    position(`基金${index + 1}`, 100 - index),
  );

  expect(topFundsShare(positions)).toEqual({ count: 6, percent: 100 });
});

test('无持仓或市值全 0:返回 0 而非 NaN', () => {
  expect(topFundsShare([])).toEqual({ count: 0, percent: 0 });
  expect(topFundsShare([position('基金1', 0)])).toEqual({
    count: 1,
    percent: 0,
  });
});

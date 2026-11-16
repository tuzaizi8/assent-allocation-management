// src/features/analytics/components/drawdown-chart.tsx —— 回撤曲线(组合 vs 基准,underwater)
// 0 基线之下的面积图:dd 恒为负的百分数,面积越深回撤越大。组合用 loss 语义色填充,
// 基准用灰阶虚线叠在上层(在填充之上才看得见),比出「是自身选基还是市场普跌」。
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  XAxis,
  YAxis,
} from 'recharts';

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart';

import type { DrawdownPoint } from '../api/get-risk-metrics';

const chartConfig = {
  dd: { label: '组合' },
  benchmarkDd: { label: '基准' },
} satisfies ChartConfig;

/** X 轴刻度:均匀抽 6 个点,全部展示会互相重叠 */
const tickDates = (points: DrawdownPoint[]): string[] => {
  if (points.length <= 6) return points.map((p) => p.date);
  const step = Math.floor(points.length / 5);
  return [0, step, step * 2, step * 3, step * 4, points.length - 1].map(
    (i) => points[i]?.date ?? '',
  );
};

/** 两条序列同一交易日轴、等长,直接按下标并成一行(与滚动波动率图同做法) */
const mergeSeries = (portfolio: DrawdownPoint[], benchmark: DrawdownPoint[]) =>
  portfolio.map((point, i) => ({
    date: point.date,
    dd: point.dd,
    benchmarkDd: benchmark[i]?.dd ?? null,
  }));

export function DrawdownChart({
  points,
  benchmark,
}: {
  points: DrawdownPoint[];
  benchmark: DrawdownPoint[];
}) {
  const data = mergeSeries(points, benchmark);
  const ticks = tickDates(points);
  return (
    <ChartContainer
      config={chartConfig}
      className="aspect-auto h-[230px] w-full"
    >
      <ComposedChart
        data={data}
        margin={{ top: 8, right: 8, bottom: 0, left: 8 }}
      >
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="date"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          ticks={ticks}
          tickFormatter={(value: string) => value.slice(5)}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          tickFormatter={(value: number) => `${value}%`}
          width={52}
        />
        <ChartTooltip
          cursor={false}
          content={<ChartTooltipContent indicator="dot" />}
        />
        {/* 回撤线恒在 0 基线下方:基线加粗,水下面积用 loss 语义色 */}
        <ReferenceLine y={0} stroke="var(--border)" />
        <Area
          dataKey="dd"
          type="monotone"
          fill="var(--color-loss)"
          fillOpacity={0.25}
          stroke="var(--color-loss)"
          strokeWidth={1.5}
        />
        {/* 放在面积之后:先画会被半透明的组合填充盖住 */}
        <Line
          dataKey="benchmarkDd"
          type="monotone"
          stroke="var(--muted-foreground)"
          strokeWidth={1.5}
          strokeDasharray="4 3"
          dot={false}
        />
      </ComposedChart>
    </ChartContainer>
  );
}

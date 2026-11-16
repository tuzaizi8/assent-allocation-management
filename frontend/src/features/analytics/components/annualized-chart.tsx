// src/features/analytics/components/annualized-chart.tsx —— 年化收益率走势(组合 vs 基准)
// 每个交易日把当时的累计收益年化一次:两条线同一条公式、同一日期轴(后端按
// QuantStats 的 cagr 口径换算),故可直接比高低。第 21 个交易日前噪声大,不画。
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceDot,
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

import type { DateValue } from '../api/get-risk-metrics';

import { DOT_RADIUS, DotWithBadge } from './chart-badge';

const chartConfig = {
  portfolio: { label: '组合' },
  benchmark: { label: '基准' },
} satisfies ChartConfig;

/** 两条序列同一交易日轴、等长,直接按下标并成一行(与滚动波动率图同做法) */
const mergeSeries = (
  portfolio: DateValue[],
  benchmark: DateValue[],
): { date: string; portfolio: number; benchmark: number | null }[] =>
  portfolio.map((point, i) => ({
    date: point.date,
    portfolio: point.value,
    benchmark: benchmark[i]?.value ?? null,
  }));

const formatPercent = (value: number) => `${value.toFixed(2)}%`;

export function AnnualizedChart({
  points,
  benchmark,
}: {
  points: DateValue[];
  benchmark: DateValue[];
}) {
  const data = mergeSeries(points, benchmark);
  const last = data[data.length - 1];
  return (
    <ChartContainer
      config={chartConfig}
      className="aspect-auto h-[230px] w-full"
    >
      {/* 上下留白是给端点 Badge 的:Badge 在 SVG 层不受绘图区裁剪,只能靠 margin 让出位置 */}
      <ComposedChart
        data={data}
        margin={{ top: 28, right: 16, bottom: 24, left: 0 }}
      >
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="date"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          minTickGap={40}
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
        <ReferenceLine y={0} stroke="var(--border)" />
        {/* 组合用收益色实线 + 淡化面积,基准用灰阶虚线(与滚动波动率图同一套语义) */}
        <Area
          dataKey="portfolio"
          type="monotone"
          stroke="var(--color-profit)"
          fill="var(--color-profit)"
          fillOpacity={0.15}
          strokeWidth={1.5}
        />
        <Line
          dataKey="benchmark"
          type="monotone"
          stroke="var(--muted-foreground)"
          strokeWidth={1.5}
          strokeDasharray="4 3"
          dot={false}
        />
        {/* 最新点数值:成立以来波动极大,曲线上读不出末点值,直接挂 Badge;两条线端点
            同在右边界,故都贴点左侧,再一上一下,即使两线重合也不会互相压住 */}
        {last && (
          <ReferenceDot
            x={last.date}
            y={last.portfolio}
            r={DOT_RADIUS}
            shape={
              <DotWithBadge
                tone="var(--color-profit)"
                text={formatPercent(last.portfolio)}
                align="upper-left"
              />
            }
          />
        )}
        {last && last.benchmark != null && (
          <ReferenceDot
            x={last.date}
            y={last.benchmark}
            r={DOT_RADIUS}
            shape={
              <DotWithBadge
                tone="var(--muted-foreground)"
                text={formatPercent(last.benchmark)}
                align="lower-left"
              />
            }
          />
        )}
      </ComposedChart>
    </ChartContainer>
  );
}

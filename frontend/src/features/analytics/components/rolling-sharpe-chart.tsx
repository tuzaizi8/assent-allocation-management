// src/features/analytics/components/rolling-sharpe-chart.tsx —— 滚动夏普(60 交易日,组合 vs 基准)
// 0 基线折线:高于 0 说明近三个月的风险调整后收益为正,穿越 0 基线的时点最有信息量。
// 两条线同窗口、同无风险利率,可直接比「我的赚钱效率 vs 大盘」。
import {
  CartesianGrid,
  Line,
  LineChart,
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

export function RollingSharpeChart({
  points,
  benchmark,
}: {
  points: DateValue[];
  benchmark: DateValue[];
}) {
  const data = mergeSeries(points, benchmark);
  return (
    <ChartContainer
      config={chartConfig}
      className="aspect-auto h-[230px] w-full"
    >
      <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="date"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          minTickGap={40}
          tickFormatter={(value: string) => value.slice(5)}
        />
        <YAxis tickLine={false} axisLine={false} width={48} />
        <ChartTooltip content={<ChartTooltipContent indicator="dot" />} />
        <ReferenceLine y={0} stroke="var(--border)" />
        {/* 组合改用收益色实线(与滚动波动率/年化走势/回撤曲线同一个「组合」标识色);
            基准恒为灰阶虚线,两条线才不会只靠虚实区分 */}
        <Line
          dataKey="portfolio"
          type="monotone"
          stroke="var(--color-profit)"
          strokeWidth={1.5}
          dot={false}
        />
        <Line
          dataKey="benchmark"
          type="monotone"
          stroke="var(--muted-foreground)"
          strokeWidth={1.5}
          strokeDasharray="4 3"
          dot={false}
        />
      </LineChart>
    </ChartContainer>
  );
}

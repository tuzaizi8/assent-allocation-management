// src/features/analytics/components/rolling-risk-chart.tsx —— 滚动波动率(组合 vs 基准)
// 60 交易日窗口的年化波动率双线:组合实线、基准灰阶虚线,看相对风险的高低切换。
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from 'recharts';

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart';

import type { DateValue } from '../api/get-risk-metrics';

const chartConfig = {
  portfolioVol: { label: '组合' },
  benchmarkVol: { label: '基准' },
} satisfies ChartConfig;

/** 把两条序列按日期合并成行(两者交易日已对齐,长度一致) */
const mergeSeries = (
  portfolio: DateValue[],
  benchmark: DateValue[],
): {
  date: string;
  portfolioVol: number | null;
  benchmarkVol: number | null;
}[] =>
  portfolio.map((p, i) => ({
    date: p.date,
    portfolioVol: p.value,
    benchmarkVol: benchmark[i]?.value ?? null,
  }));

export function RollingRiskChart({
  portfolio,
  benchmark,
}: {
  portfolio: DateValue[];
  benchmark: DateValue[];
}) {
  const data = mergeSeries(portfolio, benchmark);
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
        <YAxis
          tickLine={false}
          axisLine={false}
          tickFormatter={(value: number) => `${value}%`}
          width={52}
        />
        <ChartTooltip content={<ChartTooltipContent indicator="dot" />} />
        <Line
          dataKey="portfolioVol"
          type="monotone"
          stroke="var(--color-profit)"
          strokeWidth={1.5}
          dot={false}
        />
        <Line
          dataKey="benchmarkVol"
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

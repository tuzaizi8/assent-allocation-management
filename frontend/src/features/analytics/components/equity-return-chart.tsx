// 收益走势 + 最大回撤标注:主曲线是组合累计收益率,绿段覆盖最大回撤的峰→谷、红段覆盖谷→修复。
// 段几何全部从 drawdownSeries 自推,不用 metrics.maxDrawdownStart——它是「第一个水下日」而非峰
// (实测比真峰晚一个交易日,拿它当起点会让绿段偏一天、量出的跌幅少 0.75 个百分点)。
import {
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

import type { DateValue, DrawdownPoint } from '../api/get-risk-metrics';

import { DOT_RADIUS, DotWithBadge } from './chart-badge';

const chartConfig = {
  value: { label: '累计收益率', color: 'var(--primary)' },
  decline: { label: '最大回撤', color: 'var(--loss)' },
  recovery: { label: '修复', color: 'var(--profit)' },
} satisfies ChartConfig;

export type EquityPoint = DateValue & {
  /** 峰→谷段(绿);段外为 null,关掉 connectNulls 才不会把两段连起来 */
  decline: number | null;
  /** 谷→修复段(红);段外为 null */
  recovery: number | null;
};

export type EquitySeries = {
  points: EquityPoint[];
  /** 峰 / 谷 / 修复终点在 points 里的下标;推不出时为 null */
  peakIndex: number | null;
  valleyIndex: number | null;
  recoveryEndIndex: number | null;
};

/**
 * 按 drawdownSeries 把曲线切成「跌段 / 修复段」。
 *
 * 谷底 = dd 最小的那天;峰 = 谷底之前最后一个未水下日(dd >= 0,即当时的历史最高点);
 * 修复终点 = 谷底之后第一个回到未水下的日子,始终没回到则取数据末端。
 * 一律按下标算,不依赖 metrics 里 start/end 的语义。
 */
export function buildEquitySeries(
  series: DateValue[],
  drawdown: DrawdownPoint[],
): EquitySeries {
  const points: EquityPoint[] = series.map((point) => ({
    ...point,
    decline: null,
    recovery: null,
  }));
  const empty: EquitySeries = {
    points,
    peakIndex: null,
    valleyIndex: null,
    recoveryEndIndex: null,
  };
  if (series.length === 0 || series.length !== drawdown.length) return empty;

  let valleyIndex = 0;
  for (let i = 1; i < drawdown.length; i++) {
    if (drawdown[i].dd < drawdown[valleyIndex].dd) valleyIndex = i;
  }
  // 全期没有一天在水下 → 没有回撤可标,直接返回空(否则会把首个交易日误当谷底)
  if (drawdown[valleyIndex].dd >= 0) return empty;

  let peakIndex = -1;
  for (let i = valleyIndex; i >= 0; i--) {
    if (drawdown[i].dd >= 0) {
      peakIndex = i;
      break;
    }
  }

  let recoveryEndIndex = -1;
  for (let i = valleyIndex + 1; i < drawdown.length; i++) {
    if (drawdown[i].dd >= 0) {
      recoveryEndIndex = i;
      break;
    }
  }
  if (recoveryEndIndex < 0) recoveryEndIndex = series.length - 1;

  // 谷底落在首个交易日时找不到更早的峰,此时只能不画绿段
  if (peakIndex >= 0 && peakIndex < valleyIndex) {
    for (let i = peakIndex; i <= valleyIndex; i++) {
      points[i].decline = series[i].value;
    }
  } else {
    peakIndex = -1;
  }
  for (let i = valleyIndex; i <= recoveryEndIndex; i++) {
    points[i].recovery = series[i].value;
  }

  return {
    points,
    peakIndex: peakIndex >= 0 ? peakIndex : null,
    valleyIndex,
    recoveryEndIndex,
  };
}

/** 修复段文案:未修复(null)显示「正在修复」,已修复显示天数 */
export function recoveryLabel(recoveryDays: number | null): string {
  return recoveryDays == null ? '正在修复' : `${recoveryDays} 天修复`;
}

export function EquityReturnChart({
  series,
  drawdown,
  maxDrawdown,
  recoveryDays,
}: {
  series: DateValue[];
  drawdown: DrawdownPoint[];
  maxDrawdown: number | null;
  recoveryDays: number | null;
}) {
  const { points, peakIndex, valleyIndex, recoveryEndIndex } =
    buildEquitySeries(series, drawdown);
  const peak = peakIndex == null ? null : points[peakIndex];
  const valley = valleyIndex == null ? null : points[valleyIndex];
  const recoveryTip =
    recoveryEndIndex == null ? null : points[recoveryEndIndex];

  return (
    <ChartContainer
      config={chartConfig}
      className="aspect-auto h-[230px] w-full"
    >
      <ComposedChart
        data={points}
        margin={{ top: 28, right: 16, bottom: 0, left: 0 }}
      >
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="date"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          minTickGap={48}
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
        <Line
          dataKey="value"
          type="monotone"
          dot={false}
          strokeWidth={1.5}
          stroke="var(--color-value)"
        />
        {/* 段外全是 null:必须关掉 connectNulls,否则两段会被连成一条线 */}
        <Line
          dataKey="decline"
          type="monotone"
          dot={false}
          connectNulls={false}
          strokeWidth={2.5}
          stroke="var(--color-loss)"
        />
        <Line
          dataKey="recovery"
          type="monotone"
          dot={false}
          connectNulls={false}
          strokeWidth={2.5}
          stroke="var(--color-profit)"
        />
        {peak && (
          <ReferenceDot
            x={peak.date}
            y={peak.value}
            r={DOT_RADIUS}
            fill="var(--color-loss)"
            stroke="var(--card)"
            strokeWidth={1.5}
          />
        )}
        {valley && (
          <ReferenceDot
            x={valley.date}
            y={valley.value}
            shape={
              <DotWithBadge
                tone="var(--color-loss)"
                text={`最大回撤 ${maxDrawdown == null ? '—' : `${maxDrawdown.toFixed(2)}%`}`}
              />
            }
          />
        )}
        {recoveryTip && (
          <ReferenceDot
            x={recoveryTip.date}
            y={recoveryTip.value}
            shape={
              <DotWithBadge
                tone="var(--color-profit)"
                text={recoveryLabel(recoveryDays)}
                align="left"
              />
            }
          />
        )}
      </ComposedChart>
    </ChartContainer>
  );
}

// src/features/analytics/components/return-histogram.tsx —— 日收益分布直方图
// 20 个等宽 bin 的柱状分布;X 轴用**数值轴**(而非类目轴)——这样最差 5% 的区域底色与
// VaR/CVaR 标线才能落在精确位置上(类目轴的 ReferenceLine 只能吸附到类目值上,会失真)。
// 刻度显式指定在 bin 边界上:柱子只有约 0.5% 宽,recharts 默认的自动刻度(2% 一跳)
// 看不出每根柱落在哪个区间。
import {
  Bar,
  BarChart,
  ReferenceArea,
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

import type { ReturnHistogram } from '../api/get-risk-metrics';

import { BADGE_GAP, BADGE_HEIGHT, TextBadge } from './chart-badge';

const chartConfig = {
  count: { label: '天数' },
} satisfies ChartConfig;

/** 最差 5% 的尾部分位:与后端 var/cvar 的分位口径一致 */
const TAIL_RATIO = 0.05;
/** 刻度字号:旋转 45° 后 11 个标签也不互相压住 */
const TICK_FONT_SIZE = 10;

/**
 * recharts 传给 label 渲染函数的标线矩形。
 * 垂直标线是**零宽**矩形:x = 虚线位置、y = 绘图区顶 —— 拿它算坐标,比 position 那套
 * 锚点语义可控(用 position 时字身的朝向由锚点决定,很容易落到绘图区外被裁)。
 */
type LabelViewBox = { viewBox: { x: number; y: number } };

/** bin 中心作为数值 X 坐标;range 供 tooltip 表头展示完整区间 */
const buildRows = (hist: ReturnHistogram) =>
  hist.counts.map((count, i) => {
    const left = hist.binEdges[i] ?? 0;
    const right = hist.binEdges[i + 1] ?? left;
    return {
      center: Number(((left + right) / 2).toFixed(2)),
      range: `${left.toFixed(1)}% ~ ${right.toFixed(1)}%`,
      count,
    };
  });

export function ReturnHistogram({
  histogram,
  varValue,
  cvarValue,
}: {
  histogram: ReturnHistogram;
  /** VaR/CVaR(%),null 表示算不出,不画标线与底色 */
  varValue: number | null;
  cvarValue: number | null;
}) {
  const data = buildRows(histogram);
  // 第一个 bin 的左边界就是区间内的最小日收益,即「最惨的一天」
  const worstDay = histogram.binEdges[0] ?? 0;
  const totalDays = histogram.counts.reduce((sum, count) => sum + count, 0);
  const tailDays = Math.max(1, Math.round(totalDays * TAIL_RATIO));
  // 21 个边界取隔一个的 11 个:正好落在每根柱的左边界上,且窄屏也不会重叠
  const tickEdges = histogram.binEdges.filter((_, i) => i % 2 === 0);
  // 图上看不出来的三件事(门槛、破线后的均值、最惨一天)在这里用一句话给全,用词与
  // hover card 对齐(门槛=VaR、破线后平均=CVaR);交易日总数不重复(卡头描述里已有)
  const summary =
    varValue != null && cvarValue != null
      ? `最差的 5%(约 ${tailDays} 天):门槛 ${varValue.toFixed(2)}%,破线后平均 ${cvarValue.toFixed(2)}%;最惨一天 ${worstDay.toFixed(2)}%。`
      : `最惨一天 ${worstDay.toFixed(2)}%。`;
  return (
    <div className="flex flex-col gap-2">
      <ChartContainer
        config={chartConfig}
        className="aspect-auto h-[230px] w-full"
      >
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
          <XAxis
            dataKey="center"
            type="number"
            domain={['dataMin', 'dataMax']}
            ticks={tickEdges}
            interval={0}
            tickLine={false}
            axisLine={false}
            tickMargin={8}
            height={44}
            angle={-45}
            textAnchor="end"
            fontSize={TICK_FONT_SIZE}
            tickFormatter={(value: number) => `${value.toFixed(1)}%`}
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={40}
            allowDecimals={false}
            label={{
              value: '天数',
              angle: -90,
              position: 'insideLeft',
              fontSize: TICK_FONT_SIZE,
              fill: 'var(--muted-foreground)',
            }}
          />
          <ChartTooltip
            content={
              <ChartTooltipContent
                indicator="dot"
                labelFormatter={(
                  _center: unknown,
                  payload: readonly { payload?: { range?: string } }[],
                ) => payload[0]?.payload?.range ?? ''}
              />
            }
          />
          {/* 最差 5% 的区域底色:实测分位点一般落在某根柱子内部,按柱染色会有
              「半根柱子算不算最差 5%」的歧义;区域底色与标线严格对齐 */}
          {varValue != null && (
            <ReferenceArea
              x1={worstDay}
              x2={varValue}
              fill="var(--color-loss)"
              fillOpacity={0.08}
            />
          )}
          <Bar dataKey="count" fill="var(--muted-foreground)" radius={3} />
          {/* 标线画在柱子之后,否则会被柱子压住。标注只写指标名(VaR / CVaR):含义在
              标题后的 hover card 里、数值在卡底摘要句里,标线上再写一遍只会挤。两枚 Badge
              都**居中骑在自己那条虚线上**(向右展开会让 CVaR 那枚压到 VaR 的线上,分不清
              谁是谁),上下两行错开一枚 Badge 高,因此贴得再近也不会互相压住 */}
          {varValue != null && (
            <ReferenceLine
              x={varValue}
              stroke="var(--color-chart-5)"
              strokeDasharray="4 3"
              label={({ viewBox }: LabelViewBox) => (
                <TextBadge
                  x={viewBox.x}
                  y={viewBox.y + BADGE_GAP}
                  anchor="center"
                  tone="var(--color-chart-3)"
                  fillOpacity={0.85}
                  text="VaR"
                />
              )}
            />
          )}
          {cvarValue != null && (
            <ReferenceLine
              x={cvarValue}
              stroke="var(--color-chart-5)"
              strokeDasharray="4 3"
              label={({ viewBox }: LabelViewBox) => (
                <TextBadge
                  x={viewBox.x}
                  y={viewBox.y + BADGE_GAP + BADGE_HEIGHT + BADGE_GAP}
                  anchor="center"
                  tone="var(--color-chart-3)"
                  fillOpacity={0.85}
                  text="CVaR"
                />
              )}
            />
          )}
        </BarChart>
      </ChartContainer>
      <p className="text-muted-foreground text-xs leading-relaxed">{summary}</p>
    </div>
  );
}

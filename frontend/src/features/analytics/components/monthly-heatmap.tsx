// 月度收益热力图:年份为行、1~12 月 + 「全年」为列,用 cell 矩阵呈现。
// 全站唯一不走 shadcn ChartContainer+recharts 的图表:recharts 没有 band×band 的
// 格子矩阵能力,而这张卡要的正是「日历格子」观感。动画由 motion() 渲染器提供,
// 定义对象里的 motion 只是惰性策略,不激活动画。
import { cell, defineChart, type ChartPoint } from '@tanstack/charts';
import { motion } from '@tanstack/charts/motion';
import { tooltip } from '@tanstack/charts/tooltip';
import { Chart } from '@tanstack/react-charts/core';
import { scaleBand, scaleThreshold } from 'd3-scale';
import { useMemo } from 'react';

import type { MonthlyReturnRow } from '../api/get-risk-metrics';

export type HeatmapCell = {
  /** 年份(字符串,y 轴 band 域) */
  year: string;
  /** 0..11 = 1~12 月,12 = 「全年」列(取 yearTotal) */
  monthIdx: number;
  /** 月度收益(%);null = 无数据 */
  value: number | null;
  /** 色阶输入:null 走哨兵值,单独占 null 桶 */
  colorValue: number;
};

export const MONTH_LABELS = [
  '1月',
  '2月',
  '3月',
  '4月',
  '5月',
  '6月',
  '7月',
  '8月',
  '9月',
  '10月',
  '11月',
  '12月',
  '全年',
];

/** null 格的色阶输入:必须小于 HEATMAP_COLOR_DOMAIN[0] 才能独占 null 桶;真实月度收益不可能低于 -999% */
export const HEATMAP_NULL_COLOR_VALUE = -1000;

/**
 * 「恰好 0%」灰桶的半宽。后端收益统一保留 2 位小数,故最小非零幅度就是 0.01——
 * 半宽取 0.005 时灰桶 [-0.005, 0.005) 在真实数据里只可能装下恰好 0,
 * 于是「灰块只代表 0%,只要涨了或跌了都有颜色」由带宽本身保证(不是靠四舍五入碰运气)。
 */
export const HEATMAP_ZERO_BAND = 0.005;

/** 阈值按实测分布标定(6 年月度收益 -9.82~+11.51、年度 -15.95~+17.15):盈亏各 5 档对称 + 恰好 0% 窄带 + null 桶,共 12 档 */
export const HEATMAP_COLOR_DOMAIN = [
  -999.5,
  -10,
  -6,
  -3,
  -1.5,
  -HEATMAP_ZERO_BAND,
  HEATMAP_ZERO_BAND,
  1.5,
  3,
  6,
  10,
];
/** 取色见 index.css 的 --heat-*:低 chroma 浅→深渐变,暗色主题下方向自动反转 */
export const HEATMAP_COLOR_RANGE = [
  'var(--heat-null)',
  'var(--heat-loss-5)',
  'var(--heat-loss-4)',
  'var(--heat-loss-3)',
  'var(--heat-loss-2)',
  'var(--heat-loss-1)',
  'var(--heat-flat)',
  'var(--heat-gain-1)',
  'var(--heat-gain-2)',
  'var(--heat-gain-3)',
  'var(--heat-gain-4)',
  'var(--heat-gain-5)',
];

/** 图例标签:直接写区间,比「深亏/微亏」这类形容词更好核对;与 range 去掉 null 桶后一一对应 */
export const HEATMAP_LEGEND_LABELS = [
  '< -10%',
  '-10 ~ -6%',
  '-6 ~ -3%',
  '-3 ~ -1.5%',
  '-1.5 ~ 0%',
  '= 0%',
  '0 ~ 1.5%',
  '1.5 ~ 3%',
  '3 ~ 6%',
  '6 ~ 10%',
  '> 10%',
];

// 行高恒定:库在 resolveConfiguredScale 里无条件执行 scale.range(range),会覆盖我们给 y 轴设的
// range——band 永远铺满绘图区。所以想让格子恒定 30px 高,只能让绘图区高度正好等于 年数 × 30,
// 即高度随年数线性增长;给个「最小高度」兜底反而会把 1~2 年的行拉高变形
export const HEATMAP_ROW_HEIGHT = 30;
export const HEATMAP_MARGIN = { top: 12, right: 16, bottom: 24, left: 44 };

/** 行数 → 图表高度:绘图区高度严格 = 行数 × 行高,故任意档位格子形状完全一致 */
export function heatmapHeight(rowCount: number): number {
  return (
    rowCount * HEATMAP_ROW_HEIGHT + HEATMAP_MARGIN.top + HEATMAP_MARGIN.bottom
  );
}

/** 月度收益行 → 扁平 cell 矩阵(年数 × 13);全年列取 yearTotal,null 保留 */
export function buildHeatmapCells(rows: MonthlyReturnRow[]): HeatmapCell[] {
  return rows.flatMap((row) => {
    const year = String(row.year);
    const cells: HeatmapCell[] = row.months.map((value, monthIdx) => ({
      year,
      monthIdx,
      value,
      colorValue: value ?? HEATMAP_NULL_COLOR_VALUE,
    }));
    cells.push({
      year,
      monthIdx: 12,
      value: row.yearTotal,
      colorValue: row.yearTotal ?? HEATMAP_NULL_COLOR_VALUE,
    });
    return cells;
  });
}

// spring 弹簧入场(入场动画必须由渲染器提供:Charts 的 /core 宿主不吃定义里的 motion)
const motionRenderer = motion({
  initial: 'always',
  transition: { type: 'spring', stiffness: 170, damping: 18, mass: 1 },
});

function tooltipContent(points: readonly ChartPoint<HeatmapCell>[]) {
  const datum = points[0]?.datum as HeatmapCell | undefined;
  if (!datum) return { title: '', rows: [] };
  const title =
    datum.monthIdx === 12
      ? `${datum.year}年 全年`
      : `${datum.year}年 ${MONTH_LABELS[datum.monthIdx]}`;
  return {
    title,
    rows: [
      {
        label: '收益',
        value: datum.value == null ? '—' : `${datum.value.toFixed(2)}%`,
        // 读数的色点用语义色(与色阶中档同值);0 与 null 都是中性,别落进亏损分支
        color:
          datum.value == null || datum.value === 0
            ? 'var(--muted-foreground)'
            : datum.value > 0
              ? 'var(--profit)'
              : 'var(--loss)',
      },
    ],
  };
}

export function MonthlyHeatmap({ rows }: { rows: MonthlyReturnRow[] }) {
  const cells = useMemo(() => buildHeatmapCells(rows), [rows]);
  const years = useMemo(
    () => [...new Set(cells.map((cell_) => cell_.year))],
    [cells],
  );
  const chartHeight = heatmapHeight(years.length);

  const definition = useMemo(
    () =>
      defineChart(
        {
          marks: [
            cell(cells, {
              id: 'monthly-returns-cells',
              x: 'monthIdx',
              y: 'year',
              color: 'colorValue',
              // 间隙全部交给 inset:band 的 paddingInner 会让 step 随档位数微变,破坏「格子恒定」
              inset: 1.5,
              radius: 4,
              // 切档位时整批格子换行,没有稳定 key 弹簧动画会错位重播
              key: (datum) => `${datum.year}-${datum.monthIdx}`,
            }),
          ],
          // 0.18.0 的 x/y 必须挂在 scales 下(不是定义对象顶层)
          scales: {
            x: {
              scale: () => scaleBand<number>().paddingInner(0).paddingOuter(0),
              axis: {
                line: false,
                ticks: {
                  size: 0,
                  format: (v: number) => MONTH_LABELS[v] ?? '',
                },
              },
            },
            y: {
              scale: () =>
                scaleBand<string>()
                  .domain(years)
                  .paddingInner(0)
                  .paddingOuter(0),
              axis: { line: false, ticks: { size: 0 } },
            },
          },
          color: {
            // domain 必须显式给:库不从观测值推断阈值域,缺了会在渲染时抛
            // "Threshold color-scale factory requires an explicit domain"
            scale: () => scaleThreshold<number, string>(),
            domain: HEATMAP_COLOR_DOMAIN,
            range: HEATMAP_COLOR_RANGE,
          },
          margin: HEATMAP_MARGIN,
          theme: {
            foreground: 'var(--muted-foreground)',
            grid: 'var(--border)',
            background: 'transparent',
          },
        },
        {
          // 单格读数:tooltip 只取 points[0],用 group-x 会取到同月里任意一年的值
          focus: 'nearest',
          tooltip: {
            use: tooltip,
            className:
              'font-sans shadow-none rounded-md bg-popover text-popover-foreground border p-2 text-xs',
            anchor: 'group-center',
            placement: 'auto',
            content: tooltipContent,
          },
        },
      ),
    [cells, years],
  );

  return (
    <div className="w-full">
      <Chart
        definition={definition}
        renderer={motionRenderer}
        height={chartHeight}
        ariaLabel="月度收益热力图"
      />
      <div className="text-muted-foreground mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-xs">
        {HEATMAP_LEGEND_LABELS.map((label, index) => (
          <span key={label} className="flex items-center gap-1.5">
            <span
              className="size-3 rounded-[3px]"
              // 跳过 range[0](null 桶):该档在真实数据里不出现(后端对区间外月份给 0.0 而非 null)
              style={{ background: HEATMAP_COLOR_RANGE[index + 1] ?? '' }}
            />
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}

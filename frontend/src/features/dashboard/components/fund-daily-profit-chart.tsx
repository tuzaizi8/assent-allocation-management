// src/features/dashboard/components/fund-daily-profit-chart.tsx —— 各基金昨日/今日收益条形图
// 数据取 /portfolio/analytics/daily-fund-profit(两档并列):今日档=最新净值日、
// 昨日档=上一净值日,净值 T+1 发布后两档各自滚动、互不覆盖——替代旧方案
// (list 行 dailyProfit 滚动单值 + 按日历日过滤 latestNavDate,昨日档在净值更新后恒空)。
// 零轴居中:正收益向右红柱、负收益向左绿柱。金额**不画在柱端**(基金多时行高会小于字号,
// 数字与相邻行黏合到读不出来),改由悬浮 Tooltip 展示——那里给的是未截断的完整基金名 + 金额。
import { useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  XAxis,
  YAxis,
} from 'recharts';

import {
  Tabs,
  TabsList,
  TabsTrigger,
} from '@/components/animate-ui/components/radix/tabs';
import { ChartEmpty } from '@/components/shared/chart-empty';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart';
import { Skeleton } from '@/components/ui/skeleton';
import { trendColor } from '@/utils/format';

import {
  useDailyFundProfit,
  type DailyFundProfitRow,
} from '../api/get-portfolio-analytics';

const chartConfig = {
  value: { label: '收益 (元)', color: 'var(--color-profit)' },
} satisfies ChartConfig;

/** 柱体着色:正红负绿,零值走中性灰(既不涨也不跌,不应带涨跌暗示) → 走 utils 统一实现 */
const barFill = trendColor;

/** 稳定空数组:直接用 `?? []` 会每次渲染产生新引用,让下游 useMemo 失效白算 */
const EMPTY_ROWS: DailyFundProfitRow[] = [];

type ProfitTab = 'yesterday' | 'today';

const EMPTY_HINTS: Record<ProfitTab, string> = {
  // 昨日档为空通常是建仓不足两个净值日(凑不出上一净值日的份额基数)
  yesterday: '暂无上一净值日收益数据',
  // 场外基金净值 T+1 公布:最新净值日就是上一交易日,今日档多数时候有数据
  today: '暂无今日收益数据',
};

// 柱区左右边距:两侧**必须等宽**——X 轴取 [-maxAbs, maxAbs] 对称域,边距不等会把零轴推偏;
// 留 12px 是让最长的那根柱不贴住视口边缘(数值不再画在柱端,故原先给标签留的 47~76px 列宽全部还给柱区)
const BAR_SIDE_PAD = 12;

export function FundDailyProfitChart() {
  const { data, isLoading } = useDailyFundProfit();
  const [tab, setTab] = useState<ProfitTab>('yesterday');

  const rows = useMemo(
    () => (tab === 'today' ? data?.latest : data?.prev) ?? EMPTY_ROWS,
    [tab, data],
  );
  const navDate =
    tab === 'today' ? (data?.latestNavDate ?? '') : (data?.prevNavDate ?? '');

  const chartData = useMemo(
    () =>
      rows
        .map((row) => ({
          fundName: row.fundName,
          value: Number(row.dailyProfit.toFixed(2)),
        }))
        .filter((item) => item.value !== 0)
        .sort((a, b) => b.value - a.value),
    [rows],
  );

  // 描述行展示该档真实净值日(而非日历日)——周末打开时昨日档显示的是上一交易日
  const description = navDate
    ? `${navDate} 各基金收益（元）`
    : '各基金上一净值日收益（元）';

  // 零轴两侧等距:取绝对值最大值对称铺开,下限 1 防全零时 domain 退化
  const maxAbs = useMemo(
    () => Math.max(1, ...chartData.map((item) => Math.abs(item.value))),
    [chartData],
  );

  return (
    <Card className="@container/card pt-0 shadow-sm shadow-black/5">
      <CardHeader className="flex items-center gap-2 space-y-0 py-5 sm:flex-row">
        <div className="grid flex-1 gap-1">
          <CardTitle>基金收益</CardTitle>
          <CardDescription>{description}</CardDescription>
        </div>
        <Tabs value={tab} onValueChange={(v) => setTab(v as ProfitTab)}>
          <TabsList>
            <TabsTrigger value="yesterday">昨日</TabsTrigger>
            <TabsTrigger value="today">今日</TabsTrigger>
          </TabsList>
        </Tabs>
      </CardHeader>
      <CardContent className="px-2 pt-4 sm:px-6 sm:pt-6">
        {isLoading ? (
          // 首屏骨架与图表同高:避免"加载中…"换成柱图时卡片高度跳一下
          <Skeleton className="h-[230px] w-full" />
        ) : chartData.length === 0 ? (
          <ChartEmpty text={EMPTY_HINTS[tab]} />
        ) : (
          // 切档时重挂载整张图:柱子的入场动画从新数据重新播放,而不是原地跳变
          <div
            key={tab}
            className="animate-in fade-in-0 duration-200 motion-reduce:animate-none"
          >
            <ChartContainer
              config={chartConfig}
              className="aspect-auto h-[230px] w-full"
            >
              <BarChart
                data={chartData}
                layout="vertical"
                margin={{
                  top: 4,
                  right: BAR_SIDE_PAD,
                  bottom: 4,
                  left: BAR_SIDE_PAD,
                }}
              >
                <CartesianGrid horizontal={false} strokeDasharray="4 4" />
                {/* 基金名 tick 字号 10px(轴默认 12px):让名称一列更轻。字号只影响观感,
                  截断仍按下面的 8 字阈值走——想让名称多显示几个字要放宽该阈值,与字号无关 */}
                <YAxis
                  dataKey="fundName"
                  type="category"
                  tickLine={false}
                  axisLine={false}
                  width={120}
                  tick={{ fontSize: 10 }}
                  tickFormatter={(value: string) =>
                    value.length > 8 ? `${value.slice(0, 8)}…` : value
                  }
                />
                <XAxis
                  type="number"
                  domain={[-maxAbs, maxAbs]}
                  tickLine={false}
                  axisLine={false}
                  tickMargin={8}
                />
                <ChartTooltip
                  cursor={false}
                  content={<ChartTooltipContent indicator="dot" />}
                />
                <ReferenceLine x={0} stroke="var(--border)" />
                {/* 柱宽上限 16px 对齐原视觉;行多时 recharts 按类目带高度自动等分收窄每根柱
                  且类目带间天然留隙。金额不画在柱端:基金多时行高会小于字号、数字彼此黏合,
                  改由 Tooltip 展示(含未截断的完整基金名) */}
                <Bar dataKey="value" radius={4} maxBarSize={16}>
                  {chartData.map((item) => (
                    <Cell key={item.fundName} fill={barFill(item.value)} />
                  ))}
                </Bar>
              </BarChart>
            </ChartContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

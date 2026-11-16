// src/features/funds/components/fund-yield-chart-card.tsx —— 基金详情页收益率对比卡片
// 照仪表盘 PortfolioBenchmarkChart 结构改造(该组件含 mock/TODO 不直接复用):
// 双序列面积图——基金线(真数据 GET /fund/chart/yield-curve 复权累计收益率,红涨绿跌) vs
// 指数基准(GET /fund/chart/index-yields 的 accum_nav,灰阶衬托);原"我的"文案换基金名称。
import { useMemo, useState } from 'react';
import { Area, AreaChart, CartesianGrid, XAxis } from 'recharts';

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
  type ChartConfig,
} from '@/components/ui/chart';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  useFundYieldChart,
  type FundYieldPoint,
  type MoneyYieldPoint,
} from '@/features/funds/api/get-fund-yield-chart';
import { useFundPeriods } from '@/features/funds/api/get-funds';
import { useIndexYieldChart } from '@/features/funds/api/get-index-yields-chart';
import { useIndices } from '@/features/indices/api/get-indices';
import { signedPct } from '@/utils/format';

// ===== 悬停反馈(页面域自绘,照仪表盘已验证范式) =====
// 根因:基金线 stroke 是渐变 url 引用,不是合法 CSS 颜色——
// tooltip 指示方块与 activeDot 均在页面域自绘,按该点收益率正负逐点取红/绿。

type TooltipRow = {
  dataKey?: string | number;
  value?: number | string;
};

type YieldChartTooltipProps = {
  active?: boolean;
  label?: unknown;
  payload?: TooltipRow[];
  fundName: string;
  /** 基准行的展示名:直接给当前选中的指数名(如「沪深300 (%)」),不再拼「基准·」前缀 */
  benchmarkLabel: string;
};

/** 自定义 tooltip:基金行指示方块随该点收益正负红/绿,基准行恒灰(chart-1) */
function YieldChartTooltip({
  active,
  label,
  payload,
  fundName,
  benchmarkLabel,
}: YieldChartTooltipProps) {
  if (!active || !payload?.length) {
    return null;
  }
  return (
    <div className="grid min-w-32 items-start gap-1.5 rounded-lg border border-border/50 bg-background px-2.5 py-1.5 text-xs shadow-xl">
      {label != null && label !== '' && (
        <div className="font-medium">{String(label)}</div>
      )}
      <div className="grid gap-1.5">
        {payload.map((row) => {
          const isFund = String(row.dataKey) === 'fund';
          const indicatorColor = isFund
            ? Number(row.value ?? 0) >= 0
              ? 'var(--color-profit)'
              : 'var(--color-loss)'
            : 'var(--chart-1)';
          return (
            <div key={String(row.dataKey)} className="flex items-center gap-2">
              <div
                className="h-2.5 w-2.5 shrink-0 rounded-[2px]"
                style={{ backgroundColor: indicatorColor }}
              />
              <div className="flex flex-1 items-center justify-between leading-none">
                <span className="text-muted-foreground">
                  {isFund ? `${fundName} (%)` : benchmarkLabel}
                </span>
                {row.value != null && (
                  <span className="font-medium text-foreground tabular-nums">
                    {typeof row.value === 'number'
                      ? row.value.toLocaleString()
                      : String(row.value)}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** 悬停圆圈:严格跟随该点曲线颜色(0 轴上方红/下方绿),r=4 + 背景色细描边沿默认观感 */
type ActiveDotProps = {
  cx?: number | string;
  cy?: number | string;
  payload?: { fund?: number };
};
const renderFundActiveDot = ({ cx, cy, payload }: ActiveDotProps) => (
  <circle
    cx={cx}
    cy={cy}
    r={4}
    fill={
      Number(payload?.fund ?? 0) >= 0
        ? 'var(--color-profit)'
        : 'var(--color-loss)'
    }
    stroke="var(--background)"
    strokeWidth={2}
  />
);

/** 带符号百分比(图例与跑赢/跑输共用,避免格式漂移) */

export function FundYieldChartCard({
  fundCode,
  fundName,
}: {
  fundCode: string;
  fundName: string;
}) {
  // 时间档由后端下发,本地只持兜底初值(清单未加载/为空时下拉至少有一档)
  const [period, setPeriod] = useState<string>('1年');
  // 用户显式选择 null=未选;未选时取清单首项,不写死指数名(清单变化自适应)
  const [selectedIndex, setSelectedIndex] = useState<string | null>(null);
  // 悬停联动:null=未悬停(显示最新点),悬停时描述行与图例跟随该点
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const { data: indices, isLoading: indicesLoading } = useIndices();
  const { data: periods } = useFundPeriods();
  const activeIndex = selectedIndex ?? indices?.[0]?.indexName ?? null;
  const { data: benchmark, isLoading } = useIndexYieldChart(
    activeIndex ?? undefined,
    period,
  );
  const { data: fundYield, isLoading: fundLoading } = useFundYieldChart(
    fundCode,
    period,
  );
  // 货币基金:后端 data 是七日年化序列({nav_date, annualized_7d}),无基准对比
  const isMoneyFund = fundYield?.is_money_fund === true;
  // 清单未加载/为空时保底一档,防下拉空选项导致 Radix 受控值不匹配
  const periodOptions = periods?.length ? periods : ['1年'];

  const chartData = useMemo(() => {
    // 货币基金分支:单序列七日年化(%),基准恒 null——复用同一图表骨架,
    // 全正值 → zeroOffset=100 → 面积整体盈利红,语义成立
    if (fundYield?.is_money_fund) {
      const moneySeries = fundYield.data as MoneyYieldPoint[];
      return moneySeries.map((point) => ({
        date: point.nav_date,
        fund: point.annualized_7d,
        benchmark: null as number | null,
      }));
    }
    // 双序列按各自日期对齐:基金曲线日期为主轴(本卡主体),基准缺失日 null 断线
    const fundSeries = (fundYield?.data as FundYieldPoint[] | undefined) ?? [];
    const benchmarkSeries = benchmark?.data ?? [];
    const benchmarkByDate = new Map(
      benchmarkSeries.map((point) => [point.nav_date, point.accum_nav]),
    );
    // 基准按基金曲线首日重归一化:指数接口 accum_nav 以指数自身首日(如沪深300 为 2002 年)=1.0,
    // 而基金线以基金首日=1.0——起点不同日会使任何档位的对比失真(新基金成立不足一年时尤甚)。
    // 统一除以基准在基金首日(≤ 基金首日的最近交易日)的值,两序列即在同一交易日 0% 起点对比;
    // 短档下该值≈1.0 无副作用;基金首日早于基准数据首日时回退用基准首个值
    const fundFirstDate = fundSeries[0]?.nav_date;
    const earlier = benchmarkSeries.filter(
      (p) => fundFirstDate == null || p.nav_date <= fundFirstDate,
    );
    const baseBench =
      earlier.length > 0
        ? earlier[earlier.length - 1].accum_nav
        : (benchmarkSeries[0]?.accum_nav ?? 1);

    // 日期轴以基金曲线为准:基准早于基金首日的内容截断不展示——
    // 对比从基金成立日(首日=1.0)起算,不渲染 2002~2009 这类基金尚未成立的空档期
    const dates = fundSeries.map((point) => point.nav_date);
    const fundByDate = new Map(
      fundSeries.map((point) => [point.nav_date, point.accum_nav]),
    );
    return Array.from(dates)
      .sort()
      .map((date) => ({
        date,
        fund:
          fundByDate.get(date) != null
            ? Number(((fundByDate.get(date)! - 1) * 100).toFixed(2))
            : null,
        // 重归一化后的基准归一化净值(1.0 起步)转累计收益率(%),与基金线同起点可比
        benchmark:
          benchmarkByDate.get(date) != null
            ? Number(
                ((benchmarkByDate.get(date)! / baseBench - 1) * 100).toFixed(2),
              )
            : null,
      }));
  }, [fundYield, benchmark]);

  // 基金线红涨绿跌:0 值在数据包围盒中的纵向位置(%),红绿在此硬切——
  // 全正→100% 全红,全负→0% 全绿,平坦(span=0)→全红,规避除零 NaN
  const zeroOffset = useMemo(() => {
    const values = chartData
      .map((d) => d.fund)
      .filter((v): v is number => v != null);
    const max = Math.max(...values, 0);
    const min = Math.min(...values, 0);
    return max === min ? 100 : (max / (max - min)) * 100;
  }, [chartData]);

  // 显示点派生值:基金收益率/基准收益率/相对差值(基准缺失日 benchmark 为 null)
  const displayIndex = hoverIndex ?? chartData.length - 1;
  const currentPoint = chartData[displayIndex];
  const myVal = currentPoint?.fund ?? 0;
  const benchVal = currentPoint?.benchmark ?? null;
  const diff = benchVal == null ? null : Number((myVal - benchVal).toFixed(2));

  // 图表子树整体记忆化:hoverIndex 的 setState 不重建本块 JSX → React 跳过子树,
  // 悬停联动只重渲染描述行与图例(否则全量点每次 mousemove 触发整图重算即卡死)
  const chart = useMemo(() => {
    // config 随基金名动态生成,必须与 JSX 同 memo,否则每轮新引用使 memo 失效
    const chartConfig = {
      fund: {
        label: `${fundName} (%)`,
        color: 'var(--color-profit)',
      },
      benchmark: {
        label: `${activeIndex ?? '基准指数'} (%)`,
        color: 'var(--chart-1)',
      },
    } satisfies ChartConfig;
    return (
      <ChartContainer
        config={chartConfig}
        className="aspect-auto h-[200px] w-full"
      >
        <AreaChart
          data={chartData}
          onMouseMove={(state) => {
            const index = Number(state?.activeTooltipIndex);
            if (
              Number.isInteger(index) &&
              index >= 0 &&
              index < chartData.length
            ) {
              setHoverIndex(index);
            }
          }}
          onMouseLeave={() => setHoverIndex(null)}
        >
          <defs>
            {/* 基金面积:0 轴上方盈利红/下方亏损绿,zeroOffset 处硬切 */}
            <linearGradient id="fillFund" x1="0" y1="0" x2="0" y2="1">
              <stop
                offset="0%"
                stopColor="var(--color-profit)"
                stopOpacity={0.8}
              />
              <stop
                offset={`${zeroOffset}%`}
                stopColor="var(--color-profit)"
                stopOpacity={0.1}
              />
              <stop
                offset={`${zeroOffset}%`}
                stopColor="var(--color-loss)"
                stopOpacity={0.1}
              />
              <stop
                offset="100%"
                stopColor="var(--color-loss)"
                stopOpacity={0.8}
              />
            </linearGradient>
            {/* 基金线体:同 zeroOffset 分段,全不透明 */}
            <linearGradient id="strokeFund" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--color-profit)" />
              <stop offset={`${zeroOffset}%`} stopColor="var(--color-profit)" />
              <stop offset={`${zeroOffset}%`} stopColor="var(--color-loss)" />
              <stop offset="100%" stopColor="var(--color-loss)" />
            </linearGradient>
            <linearGradient id="fillBenchmark" x1="0" y1="0" x2="0" y2="1">
              <stop
                offset="5%"
                stopColor="var(--color-benchmark)"
                stopOpacity={0.2}
              />
              <stop
                offset="95%"
                stopColor="var(--color-benchmark)"
                stopOpacity={0.1}
              />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} strokeDasharray="4 4" />
          <XAxis
            dataKey="date"
            tickLine={false}
            axisLine={false}
            tickMargin={8}
            minTickGap={32}
            tickFormatter={(value: string) =>
              new Date(value).toLocaleDateString('zh-CN', {
                month: 'numeric',
                day: 'numeric',
              })
            }
          />
          <ChartTooltip
            cursor={false}
            content={
              <YieldChartTooltip
                fundName={fundName}
                benchmarkLabel={`${activeIndex ?? '基准指数'} (%)`}
              />
            }
          />
          {/* 对比语义不做 stackId 堆叠;基准缺失日传 null 自然断线 */}
          <Area
            dataKey="benchmark"
            type="monotone"
            fill="url(#fillBenchmark)"
            stroke="var(--color-benchmark)"
            connectNulls={false}
          />
          <Area
            dataKey="fund"
            type="monotone"
            fill="url(#fillFund)"
            stroke="url(#strokeFund)"
            activeDot={renderFundActiveDot}
            connectNulls={false}
          />
        </AreaChart>
      </ChartContainer>
    );
  }, [chartData, zeroOffset, activeIndex, fundName]);

  return (
    // pt-0 + CardHeader 分割线 + 阴影形态:与仪表盘收益率对比卡片同款
    <Card className="@container/card pt-0 shadow-sm shadow-black/5">
      <CardHeader className="flex items-center gap-2 space-y-0 py-5 sm:flex-row">
        <div className="grid flex-1 gap-1">
          <CardTitle>{isMoneyFund ? '七日年化走势' : '收益率曲线'}</CardTitle>
          <CardDescription>
            {isMoneyFund ? (
              '货币基金无净值曲线,收益按七日年化(%)展示'
            ) : diff == null ? (
              '基准暂无数据'
            ) : (
              <>
                {diff >= 0 ? '跑赢' : '跑输'}
                {activeIndex}
                <span className={diff >= 0 ? 'text-profit' : 'text-loss'}>
                  {' '}
                  {signedPct(diff)}
                </span>
              </>
            )}
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          {!isMoneyFund && (
            <Select
              value={activeIndex ?? undefined}
              onValueChange={setSelectedIndex}
              disabled={indicesLoading}
            >
              <SelectTrigger
                className="w-28 **:data-[slot=select-value]:block **:data-[slot=select-value]:truncate"
                size="sm"
                aria-label="选择基准指数"
              >
                <SelectValue placeholder="选择基准指数" />
              </SelectTrigger>
              <SelectContent className="rounded-xl">
                {(indices ?? []).map((item) => (
                  <SelectItem
                    key={item.indexCode}
                    value={item.indexName}
                    className="rounded-lg"
                  >
                    {item.indexName}
                    {/* syncStatus 为字典值:'1'已同步 '0'未同步 '2'已过期——非已同步均提示 */}
                    {item.syncStatus === '1' ? null : (
                      <span className="text-muted-foreground ml-1.5 text-xs">
                        {item.syncStatus === '2' ? '已过期' : '未同步'}
                      </span>
                    )}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          <Select value={period} onValueChange={setPeriod}>
            <SelectTrigger
              className="w-28 **:data-[slot=select-value]:block **:data-[slot=select-value]:truncate"
              size="sm"
              aria-label="选择时间范围"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="rounded-xl">
              {periodOptions.map((item) => (
                <SelectItem key={item} value={item} className="rounded-lg">
                  {item}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </CardHeader>
      <CardContent className="px-2 pt-4 sm:px-6 sm:pt-6">
        {fundLoading ? (
          <Skeleton className="h-[200px] w-full" />
        ) : chartData.length === 0 ? (
          <ChartEmpty
            height={200}
            text={
              isMoneyFund
                ? '该时间段内暂无七日年化数据'
                : '该时间段内暂无净值数据'
            }
          />
        ) : (
          // 换基准/换档时重挂载:两条线重新走一遍入场动画,而不是原地换数据造成跳变
          <div
            key={`${activeIndex ?? 'none'}:${period}:${isMoneyFund ? 'money' : 'normal'}`}
            className="animate-in fade-in-0 duration-200 motion-reduce:animate-none"
          >
            {chart}
          </div>
        )}
        {/* 图例:色块与数值随显示点(悬停优先,未悬停为最新)动态变化 */}
        <div className="text-muted-foreground mt-2 flex items-center justify-center gap-4 text-xs">
          <span className="flex items-center gap-1.5">
            <span
              className="h-2.5 w-2.5 rounded-[2px]"
              style={{
                backgroundColor:
                  myVal >= 0 ? 'var(--color-profit)' : 'var(--color-loss)',
              }}
            />
            {fundName}
            <span
              className={`font-medium tabular-nums ${
                myVal >= 0 ? 'text-profit' : 'text-loss'
              }`}
            >
              {fundLoading ? '—' : signedPct(myVal)}
            </span>
          </span>
          {!isMoneyFund && (
            <span className="flex items-center gap-1.5">
              <span
                className="h-2.5 w-2.5 rounded-[2px]"
                style={{ backgroundColor: 'var(--chart-1)' }}
              />
              {activeIndex ?? '基准指数'}
              <span
                className={`font-medium tabular-nums ${
                  benchVal != null
                    ? benchVal >= 0
                      ? 'text-profit'
                      : 'text-loss'
                    : ''
                }`}
              >
                {isLoading || benchVal == null ? '—' : signedPct(benchVal)}
              </span>
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

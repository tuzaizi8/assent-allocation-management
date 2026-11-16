// src/features/dashboard/components/portfolio-benchmark-chart.tsx —— 收益率对比面积图
// 双序列:持仓收益率(GET /portfolio/analytics/comparison 的 TWR,100 基准减 100 转累计收益率 %,
// 红涨绿跌——0 轴上方盈利红/下方亏损绿) vs 指数基准(真实接口 GET /fund/chart/index-yields 的
// accum_nav,从 1.0 起步转累计收益率 %,灰阶衬托)。
// 口径备注:后端 TWR 只剥离「采样点当天」的资金进出(2026-09-14 起按当日申购/赎回**总额**剥离,
// 同日既有买入又有赎回不再互相抵消),两个采样点之间的买卖仍不剥离 → 取数必须日频。
// 轴与归一化:日期轴取**两条线首日中更晚的那个**(组合建仓晚于指数起点时即以建仓日为轴,
// 指数更早的部分不展示),两条线再按这个共同起点重归一化为 0% 才可比——
// 与基金详情页收益率曲线(fund-yield-chart-card.tsx)同一做法,详见 buildBenchmarkPoints。
// 时间段用统一下拉框选择(设计稿的双形态控件已裁剪),档位清单由 GET /fund/periods
// 下发(与后端 filter_records_by_period 同源,前端不维护档位常量)。
// 基准指数可下拉切换(数据源 GET /index/list 内置清单,未同步指数可选但带提示),
// 默认选中清单首项(不写死指数名,清单变化自适应)。
import { TriangleAlertIcon } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Area, AreaChart, CartesianGrid, XAxis } from 'recharts';

import { DateField } from '@/components/shared/date-field';
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
import { Spinner } from '@/components/ui/spinner';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  defaultCustomRange,
  normalizeCustomRange,
  PERIOD_CUSTOM,
} from '@/features/analytics/lib/period';
import { useFundPeriods } from '@/features/funds/api/get-funds';
import { useIndexYieldChart } from '@/features/funds/api/get-index-yields-chart';
import { useIndices } from '@/features/indices/api/get-indices';
import { signedPct } from '@/utils/format';

import { usePortfolioTwr } from '../api/get-portfolio-analytics';

/** 档位清单未加载/为空时的下拉兜底初值(真实档位由 GET /fund/periods 下发) */
const DEFAULT_CHART_PERIOD = '1年';

/** 图表单点:两条线的缺失都用 null 表达(recharts 自然断线),不伪造 0 */
type BenchmarkChartPoint = {
  date: string;
  portfolio: number | null;
  benchmark: number | null;
};

/** 基准序列项(只声明本模块消费的字段,接口还回其它字段) */
type BenchmarkSeriesPoint = { nav_date: string; accum_nav: number };
/** 组合 TWR 序列项(同上) */
type PortfolioSeriesPoint = { date: string; value: number };

/**
 * 把两条线对齐到同一日期轴,并以「更晚的那个起点」为共同 0% 重新归一化。
 *
 * 为什么:组合 2021 年建仓、沪深300 从 2004 年就有数据,若以基准为轴(旧口径)则「成立以来」
 * 会把指数的全量历史铺满、且两条线起点不同日——对比失真。故起点取**两条线首日中更晚者**
 * (即"只展示最晚成立的"),更早那条线在起点之前的点一律不进入结果。
 *
 * 两条线都要按共同起点重归一化(与基金详情页收益率曲线同一做法):
 * 基准 `accum_nav ÷ 起点处值`;组合 `(1 + v/100) ÷ (1 + 起点处值/100) − 1`。
 * 常态(组合更晚)下起点处的组合值本就是 0(建仓当天 = 0%),组合那一侧是空操作;
 * 反向情形(指数同步得晚、比组合首日更晚)则组合被真正重算,两条线仍同起点可比。
 *
 * 两种空数据回退保持原行为:基准无数据 → 轴用组合、只画组合线;组合无数据 → 轴用基准、只画基准线。
 *
 * 调用约定:**两个序列都就绪后再调用**——空数组兜底是给"查询已返回且确实为空"用的,
 * pending 期传进来会先画出一条错的轴(渲染层的就绪门负责挡掉这一帧)。
 */
export function buildBenchmarkPoints(
  benchmarkSeries: BenchmarkSeriesPoint[],
  portfolioSeries: PortfolioSeriesPoint[],
): BenchmarkChartPoint[] {
  // 基准无数据(指数未同步):以组合自身日期为轴,只画「我的」一条线
  if (!benchmarkSeries.length) {
    return portfolioSeries.map((point) => ({
      date: point.date,
      portfolio: point.value,
      benchmark: null,
    }));
  }

  const toPct = (value: number) => Number(value.toFixed(2));

  // 组合无数据(还没建仓):轴用基准自己的日期,只画基准线(从基准自身首日 0% 算起)
  if (!portfolioSeries.length) {
    const base = benchmarkSeries[0].accum_nav;
    return benchmarkSeries.map((point) => ({
      date: point.nav_date,
      portfolio: null,
      benchmark: toPct((point.accum_nav / base - 1) * 100),
    }));
  }

  const portfolioFirst = portfolioSeries[0].date;
  const benchmarkFirst = benchmarkSeries[0].nav_date;
  // 起点取更晚者,轴用它的日期序列(两条线都是日频,点数与悬停索引天然对齐)
  const axisIsPortfolio = portfolioFirst >= benchmarkFirst;
  const axisStart = axisIsPortfolio ? portfolioFirst : benchmarkFirst;

  // 起点处取值:「不晚于起点」的最近一根;取不到(起点早于该序列首日)回退该序列首值
  const baseBench =
    [...benchmarkSeries].reverse().find((point) => point.nav_date <= axisStart)
      ?.accum_nav ?? benchmarkSeries[0].accum_nav;
  const basePortfolio =
    [...portfolioSeries].reverse().find((point) => point.date <= axisStart)
      ?.value ?? 0;
  const benchPct = (accumNav: number) =>
    toPct((accumNav / baseBench - 1) * 100);
  const portPct = (value: number) =>
    toPct(((1 + value / 100) / (1 + basePortfolio / 100) - 1) * 100);

  if (axisIsPortfolio) {
    // 轴 = 组合日期;基准按「不晚于该日」取最近一根
    let cursor = 0;
    let lastBench = baseBench;
    return portfolioSeries.map((point) => {
      while (
        cursor < benchmarkSeries.length &&
        benchmarkSeries[cursor].nav_date <= point.date
      ) {
        lastBench = benchmarkSeries[cursor].accum_nav;
        cursor += 1;
      }
      return {
        date: point.date,
        portfolio: portPct(point.value),
        benchmark: benchPct(lastBench),
      };
    });
  }

  // 轴 = 基准日期;组合按「不晚于该日」取最近一根(建仓前取不到 → null,不画成 0 轴上的点)
  let cursor = 0;
  let lastPortfolio: number | null = null;
  return benchmarkSeries.map((point) => {
    while (
      cursor < portfolioSeries.length &&
      portfolioSeries[cursor].date <= point.nav_date
    ) {
      lastPortfolio = portfolioSeries[cursor].value;
      cursor += 1;
    }
    return {
      date: point.nav_date,
      portfolio: lastPortfolio == null ? null : portPct(lastPortfolio),
      benchmark: benchPct(point.accum_nav),
    };
  });
}

// ===== 悬停反馈(页面域自绘,ui/chart.tsx 保持原样) =====
// 根因:持仓线 stroke 是渐变 url 引用,不是合法 CSS 颜色——
// ① 共享 tooltip 的指示方块注入 background-color 后透明不可见;
// ② activeDot 继承渐变后按小圆圈自身 bbox 解析出"半红半绿"。
// 故 tooltip 内容与圆圈均在页面域自绘,按该点收益率正负逐点取红/绿。

type TooltipRow = {
  dataKey?: string | number;
  value?: number | string;
};

type BenchmarkChartTooltipProps = {
  active?: boolean;
  label?: unknown;
  payload?: TooltipRow[];
  benchmarkLabel: string;
};

/** 自定义 tooltip:持仓行指示方块随该点收益正负红/绿,基准行恒灰(chart-1) */
function BenchmarkChartTooltip({
  active,
  label,
  payload,
  benchmarkLabel,
}: BenchmarkChartTooltipProps) {
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
          const isPortfolio = String(row.dataKey) === 'portfolio';
          const value = row.value == null ? null : Number(row.value);
          // 组合行按该点收益正负着色;取不到值(建仓前)给中性灰,不冒充 0 着成红
          const indicatorColor =
            !isPortfolio || value == null
              ? 'var(--chart-1)'
              : value >= 0
                ? 'var(--color-profit)'
                : 'var(--color-loss)';
          return (
            <div key={String(row.dataKey)} className="flex items-center gap-2">
              <div
                className="h-2.5 w-2.5 shrink-0 rounded-[2px]"
                style={{ backgroundColor: indicatorColor }}
              />
              <div className="flex flex-1 items-center justify-between leading-none">
                <span className="text-muted-foreground">
                  {isPortfolio ? '持仓收益率 (%)' : benchmarkLabel}
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
  payload?: { portfolio?: number | null };
};
const renderPortfolioActiveDot = ({ cx, cy, payload }: ActiveDotProps) => (
  <circle
    cx={cx}
    cy={cy}
    r={4}
    // 取不到值(建仓前)给中性灰:不把缺失点画成红/绿
    fill={
      payload?.portfolio == null
        ? 'var(--chart-1)'
        : payload.portfolio >= 0
          ? 'var(--color-profit)'
          : 'var(--color-loss)'
    }
    stroke="var(--background)"
    strokeWidth={2}
  />
);

export function PortfolioBenchmarkChart({
  /** 是否提供「自定义」时间档:该卡仪表盘页也复用,自定义只在持仓分析页开 */
  allowCustomRange = false,
}: {
  allowCustomRange?: boolean;
}) {
  // 时间档由后端下发,本地只持兜底初值(清单未加载/为空时下拉至少有一档)
  const [period, setPeriod] = useState<string>(DEFAULT_CHART_PERIOD);
  // 自定义区间的草稿值:初始给近一年,选中「自定义」时不会先面对两个空字段
  const [customRange, setCustomRange] = useState(defaultCustomRange);
  // 用户显式选择 null=未选;未选时取清单首项,不写死指数名(清单变化自适应)
  const [selectedIndex, setSelectedIndex] = useState<string | null>(null);
  // 悬停联动:null=未悬停(显示最新点),悬停时描述行与图例跟随该点
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const isCustom = period === PERIOD_CUSTOM;
  // 空值(日期字段的清除按钮)与反序都在这里收口:渲染用它,请求也用它
  const range = normalizeCustomRange(customRange);

  const { data: indices, isLoading: indicesLoading } = useIndices();
  const { data: periods } = useFundPeriods();
  const activeIndex = selectedIndex ?? indices?.[0]?.indexName ?? null;
  const { data: benchmark, isLoading: benchmarkLoading } = useIndexYieldChart(
    activeIndex ?? undefined,
    period,
    isCustom ? range.start : undefined,
    isCustom ? range.end : undefined,
  );
  // 组合取数起点用基准首日:档位推算日可能落在周末/节假日,用它才能覆盖到档位起点
  // (两线同日同起点由 buildBenchmarkPoints 的重归一化保证,不依赖这个锚点)
  const benchmarkStart = benchmark?.data?.[0]?.nav_date;
  const { data: portfolioTwr, isLoading: portfolioLoading } = usePortfolioTwr(
    benchmarkStart,
    // 自定义时结束日必须一起传,否则组合序列会延伸出自定义区间
    isCustom ? range.end : undefined,
  );
  // 记录不完整的日期与基金:这些天收益率按「不产生收益」处理,卡片上给一行说明
  const gapDates = portfolioTwr?.incompleteDates ?? [];
  const gapFunds = portfolioTwr?.gapFunds ?? [];
  // 清单未加载/为空时保底一档,防下拉空选项导致 Radix 受控值不匹配;仅分析页追加「自定义」
  const periodOptions = [
    ...(periods?.length ? periods : [DEFAULT_CHART_PERIOD]),
    ...(allowCustomRange ? [PERIOD_CUSTOM] : []),
  ];
  // 两个序列都就绪才画:组合查询的起点依赖基准首日(enabled=false 起步),所以基准必然先到。
  // 基准已到、组合未到的这段窗口里若先按「组合无数据」兜底画出基准全量轴,随后会被裁剪后的
  // 共同起点一拽(还带着 recharts 的域过渡)——即"先铺满 2004 年、再被拽回来"的乱动画。
  // 判定用「数据对象是否存在」而不是 isLoading:TWR 查询在 enabled=false 阶段 isLoading 为 false,
  // 只有对象存在才能覆盖全部未就绪阶段;查询成功返回空数组时对象仍在,两道真·空数据兜底不受影响。
  const chartReady = benchmark != null && portfolioTwr != null;

  // 对齐与归一化都收在 buildBenchmarkPoints:轴取两条线首日中更晚者,两条线按该起点同从 0% 起
  const chartData = useMemo<BenchmarkChartPoint[]>(
    () =>
      buildBenchmarkPoints(benchmark?.data ?? [], portfolioTwr?.points ?? []),
    [benchmark, portfolioTwr],
  );

  // 持仓线红涨绿跌:0 值在数据包围盒中的纵向位置(%),红绿在此硬切——
  // 全正→100% 全红,全负→0% 全绿,平坦(span=0)→全红,规避除零 NaN
  const zeroOffset = useMemo(() => {
    const values = chartData
      .map((point) => point.portfolio)
      .filter((value): value is number => value != null);
    const max = Math.max(...values, 0);
    const min = Math.min(...values, 0);
    return max === min ? 100 : (max / (max - min)) * 100;
  }, [chartData]);

  // 显示点派生值:我的收益率/基准收益率/相对差值(建仓前与基准缺失日都可能是 null)
  const displayIndex = hoverIndex ?? chartData.length - 1;
  const currentPoint = chartData[displayIndex];
  const myVal = currentPoint?.portfolio ?? null;
  const benchVal = currentPoint?.benchmark ?? null;
  const diff =
    myVal == null || benchVal == null
      ? null
      : Number((myVal - benchVal).toFixed(2));

  // 图表子树整体记忆化:hoverIndex 的 setState 不重建本块 JSX → React 跳过子树,
  // 悬停联动只重渲染描述行与图例(否则全量点每次 mousemove 触发整图重算即卡死)
  const chart = useMemo(() => {
    // config 随选中基准动态生成,必须与 JSX 同 memo,否则每轮新引用使 memo 失效
    const chartConfig = {
      portfolio: {
        label: '持仓收益率 (%)',
        color: 'var(--color-profit)',
      },
      benchmark: {
        label: `基准指数 (%)`,
        color: 'var(--chart-1)',
      },
    } satisfies ChartConfig;
    return (
      <ChartContainer
        config={chartConfig}
        className="aspect-auto h-[230px] w-full"
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
            {/* 持仓面积:0 轴上方盈利红/下方亏损绿,zeroOffset 处硬切 */}
            <linearGradient id="fillPortfolio" x1="0" y1="0" x2="0" y2="1">
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
            {/* 持仓线体:同 zeroOffset 分段,全不透明 */}
            <linearGradient id="strokePortfolio" x1="0" y1="0" x2="0" y2="1">
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
              <BenchmarkChartTooltip
                benchmarkLabel={`${activeIndex ?? '基准指数'} (%)`}
              />
            }
          />
          {/* 对比语义不做 stackId 堆叠;基准缺失日传 null 自然断线 */}
          {/* 全量 5000+ 点:monotone 插值较 natural 降本且不过冲;保留切换动画(关动画显生硬) */}
          <Area
            dataKey="benchmark"
            type="monotone"
            fill="url(#fillBenchmark)"
            stroke="var(--color-benchmark)"
            connectNulls={false}
          />
          <Area
            dataKey="portfolio"
            type="monotone"
            fill="url(#fillPortfolio)"
            stroke="url(#strokePortfolio)"
            activeDot={renderPortfolioActiveDot}
          />
        </AreaChart>
      </ChartContainer>
    );
  }, [chartData, zeroOffset, activeIndex]);

  return (
    // pt-0 + CardHeader border-b:header 与图表之间的分割线,照 dashboard-01 ChartAreaInteractive 原版;
    // 默认阴影形态,颜色覆盖为黑色 5% 不透明度(与指标卡片统一)
    <Card className="@container/card pt-0 shadow-sm shadow-black/5">
      <CardHeader className="flex items-center gap-2 space-y-0 py-5 sm:flex-row">
        <div className="grid flex-1 gap-1">
          <div className="flex items-center gap-1.5">
            <CardTitle>收益率对比</CardTitle>
            {/* 数据质量提示:那些天组合的赎回回款大于实际被移走的市值(基金早期买入不在导出件里),
                收益率已按「不产生收益」处理——不说的话这段看着像凭空涨跌,补齐历史后自然消失。
                已从图表下方搬到这里:不再在卡片底部占一整行,改为标题后的琥珀色警示图标 + 浮层;
                触发器沿用导入页 statement-issue-list 的写法(TooltipTrigger asChild,告警统一琥珀色)。 */}
            {gapDates.length > 0 && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <TriangleAlertIcon
                    data-testid="benchmark-gap-alert"
                    className="size-3.5 shrink-0 stroke-amber-600"
                  />
                </TooltipTrigger>
                <TooltipContent>
                  含 {gapDates.length} 天数据不完整（基金历史记录缺失
                  {gapFunds.length > 0
                    ? `：${gapFunds.slice(0, 3).join('、')}`
                    : ''}
                  {gapFunds.length > 3 ? ' 等' : ''}
                  ），该段收益率已按不产生收益处理
                </TooltipContent>
              </Tooltip>
            )}
          </div>
          <CardDescription>
            {!chartReady ? (
              '数据加载中…'
            ) : diff != null ? (
              <>
                {diff >= 0 ? '跑赢' : '跑输'}
                {activeIndex}
                <span className={diff >= 0 ? 'text-profit' : 'text-loss'}>
                  {' '}
                  {signedPct(diff)}
                </span>
              </>
            ) : myVal == null ? (
              '暂无持仓数据'
            ) : (
              '基准暂无数据'
            )}
          </CardDescription>
        </div>
        <div className="flex flex-wrap items-center gap-2">
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
          {/* 自定义区间:选中「自定义」后才出现;起始晚于结束时把结束日一起推到同日,不产生反序区间 */}
          {isCustom && (
            <>
              <DateField
                id="benchmark-range-start"
                value={customRange.start}
                placeholder="开始日期"
                onChange={(start) =>
                  setCustomRange((r) => ({
                    start,
                    end: start > r.end ? start : r.end,
                  }))
                }
              />
              <span className="text-muted-foreground text-sm">至</span>
              <DateField
                id="benchmark-range-end"
                value={customRange.end}
                placeholder="结束日期"
                onChange={(end) =>
                  setCustomRange((r) => ({
                    start: end < r.start ? end : r.start,
                    end,
                  }))
                }
              />
            </>
          )}
        </div>
      </CardHeader>
      <CardContent className="px-2 pt-4 sm:px-6 sm:pt-6">
        {!chartReady ? (
          // 与图表同高的骨架:占位不塌成一个小 spinner,卡片高度也不跳
          <div
            className="flex h-[230px] items-center justify-center px-2 sm:px-4"
            data-testid="benchmark-chart-loading"
          >
            <Skeleton className="h-[200px] w-full" />
            <Spinner className="sr-only" />
          </div>
        ) : (
          <>
            {/* 换基准/换档时重挂载图表:两条线重新走一遍入场动画,避免原地换数据造成"跳变" */}
            <div
              key={`${activeIndex ?? 'none'}:${period}:${
                isCustom ? `${range.start}:${range.end}` : 'preset'
              }`}
              className="animate-in fade-in-0 duration-200 motion-reduce:animate-none"
            >
              {chart}
            </div>
            {/* 图例:色块与数值随显示点(悬停优先,未悬停为最新)动态变化 */}
            <div className="text-muted-foreground mt-2 flex items-center justify-center gap-4 text-xs">
              <span className="flex items-center gap-1.5">
                <span
                  className="h-2.5 w-2.5 rounded-[2px]"
                  style={{
                    backgroundColor:
                      myVal == null
                        ? 'var(--chart-1)'
                        : myVal >= 0
                          ? 'var(--color-profit)'
                          : 'var(--color-loss)',
                  }}
                />
                我的
                <span
                  className={`font-medium tabular-nums ${
                    myVal == null
                      ? ''
                      : myVal >= 0
                        ? 'text-profit'
                        : 'text-loss'
                  }`}
                >
                  {portfolioLoading || myVal == null ? '—' : signedPct(myVal)}
                </span>
              </span>
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
                  {benchmarkLoading || benchVal == null
                    ? '—'
                    : signedPct(benchVal)}
                </span>
              </span>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

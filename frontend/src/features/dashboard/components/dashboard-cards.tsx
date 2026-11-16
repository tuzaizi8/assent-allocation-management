// src/features/dashboard/components/dashboard-cards.tsx —— 仪表盘指标卡片区
// 四张卡的当前值与「快照管理」列表逐位同源:取**最新一条快照行**(总市值=totalValue、
// 累计投入=cumulativeInvested、总盈亏=两者之差、累计盈亏率=总盈亏÷累计投入);
// 环比与 mini 走势由快照口径的走势序列(`comparison`)派生,两边因此同一口径。
// 卡片结构:指标名标题(与"收益率对比"图表卡同款 CardTitle) + 数值 + 浅灰副标题 + 底部 mini 走势图。
import {
  PercentIcon,
  PiggyBankIcon,
  TrendingUpIcon,
  WalletIcon,
  type LucideIcon,
} from 'lucide-react';
import { motion, useReducedMotion } from 'motion/react';
import { useId, useMemo } from 'react';
import { Area, AreaChart, YAxis } from 'recharts';

import { Card, CardContent, CardTitle } from '@/components/ui/card';
import { ChartContainer, type ChartConfig } from '@/components/ui/chart';
import { Skeleton } from '@/components/ui/skeleton';
import {
  useSnapshotList,
  type SnapshotRange,
} from '@/features/snapshots/api/get-snapshots';
import { useCountUp } from '@/hooks/use-count-up';
import {
  formatMoney,
  signedMoney,
  signedPct,
  trendClass,
  trendColor,
} from '@/utils/format';

import {
  usePortfolioTrend,
  weekOverWeek,
} from '../api/get-portfolio-analytics';

// 空区间 = 走后端默认区间(结束日今天、起始前 90 天);引用稳定,避免每次渲染新对象引发重复请求
const EMPTY_SNAPSHOT_RANGE: SnapshotRange = {};

/** 缺数据的统一占位:值、环比文案都用它——不拿 0 冒充真实数字 */
const EMPTY_VALUE = '—';

/** 指标语义图标(右上角点缀):按指标名映射,新增指标需同步补映射 */
const METRIC_ICONS: Record<string, LucideIcon> = {
  总市值: WalletIcon,
  累计投入: PiggyBankIcon,
  总盈亏: TrendingUpIcon,
  累计盈亏率: PercentIcon,
};

type Metric = {
  label: string;
  /** 原始数值:null 表示缺数据(展示为 —),有值时参与滚动动画 */
  value: number | null;
  /** 数值格式化:动画逐帧渲染时按同一口径输出 */
  format: (value: number) => string;
  /** 数值后的金额增量:仅金额类指标提供,百分比指标为 null */
  change?: number | null;
  /** 副标题涨跌值:驱动文字与迷你图的红/绿/灰三态着色;百分比指标传百分点差(展示时带 %) */
  trendValue: number;
  /** 副标题文案(已格式化;百分比指标这里是百分点差,按 % 呈现) */
  trendText: string;
  trendSuffix: string;
  /** 底部 mini 走势图序列 */
  spark: number[];
};

/** 底部 mini 走势图:无轴无 tooltip 的纯视觉序列,线与填充随涨跌语义着色 */
function MetricSparkline({
  data,
  trendValue,
}: {
  data: number[];
  trendValue: number;
}) {
  // 多卡实例渐变 id 必须互不相同(useId),否则 url(#) 引用串色
  const gradientId = useId();
  const stroke = trendColor(trendValue);
  // 图表配置与派生序列都按输入记忆化:否则父卡片每次重渲染都新建引用,
  // recharts 视为新数据重建子树(4 张卡叠加后是可见的抖动)
  const chartConfig = useMemo(
    () => ({ v: { color: stroke } }) satisfies ChartConfig,
    [stroke],
  );
  const chartData = useMemo(() => data.map((v, i) => ({ i, v })), [data]);
  // 起点锚在垂直中线:四张卡的迷你线必须从同一条水平线起步,否则涨的从低位起、
  // 跌的从高位起,并排看彼此对不齐。振幅只由该卡自己的数据定,上下各占一半卡高,
  // 涨跌两侧才都铺得开——锚死在一端会让反方向的幅度被压成直线。
  const domain = useMemo<[number, number]>(() => {
    if (!data.length) {
      return [0, 1];
    }
    const base = data[0];
    // 取离起点最远的偏差:纯涨/纯跌序列的另一侧没有数据,对称定域才能让起点落在中线
    const excursion = Math.max(...data.map((v) => Math.abs(v - base)));
    // 全额用满半个卡高,不再内缩:对称锚位下每侧上限就是半个卡高,留白只会白白削弱振幅。
    // 边缘余量交给 margin(2px)承担,配合 monotone 不过冲,极值点不会被裁。
    // 全平序列幅度为 0(如建仓初期的累计投入):兜一个可视高度,否则各点共线贴中线
    const half = excursion > 0 ? excursion : Math.max(Math.abs(base) * 0.1, 1);
    return [base - half, base + half];
  }, [data]);
  return (
    <ChartContainer config={chartConfig} className="h-12 w-full">
      {/* 上下对称留 2px:给 1.5px 描边留半宽,也保证绘图区中点即卡片垂直中线 */}
      <AreaChart
        data={chartData}
        margin={{ top: 2, right: 0, bottom: 2, left: 0 }}
      >
        <YAxis hide domain={domain} />
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity={0.35} />
            <stop offset="100%" stopColor={stroke} stopOpacity={0.05} />
          </linearGradient>
        </defs>
        <Area
          dataKey="v"
          // monotone 数学上不会越过端点值;natural 会在陡变处过冲,仅靠留白吸收不干净
          type="monotone"
          fill={`url(#${gradientId})`}
          stroke={stroke}
          strokeWidth={1.5}
        />
      </AreaChart>
    </ChartContainer>
  );
}

function MetricCard({
  metric,
  index,
  loading,
}: {
  metric: Metric;
  index: number;
  loading: boolean;
}) {
  const Icon = METRIC_ICONS[metric.label];
  const reduceMotion = useReducedMotion();
  const display = useCountUp(metric.value, { enabled: !reduceMotion });
  return (
    // 卡片依次进场:延迟按索引递增,与数值滚动一起构成"数据到达"的观感
    <motion.div
      className="h-full"
      initial={reduceMotion ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: index * 0.06, ease: 'easeOut' }}
    >
      {/* testid 让单测能定位到具体卡片取值(否则只能从 DOM 往上爬,测试库明确禁止) */}
      <Card
        className="@container/card relative h-full shadow-sm shadow-black/5"
        data-testid={`metric-${metric.label}`}
      >
        {Icon && (
          <Icon className="text-muted-foreground absolute right-4 top-4 size-5" />
        )}
        <CardContent className="flex flex-col gap-1.5">
          <CardTitle className="text-sm font-medium">{metric.label}</CardTitle>
          <div className="flex items-baseline gap-1.5">
            {loading ? (
              <Skeleton className="h-6 w-28" />
            ) : (
              <span className="text-lg font-semibold tabular-nums @[250px]/card:text-2xl">
                {display == null ? EMPTY_VALUE : metric.format(display)}
              </span>
            )}
            {/* 金额增量小字:仅金额类指标有,着色同涨跌三态语义 */}
            {!loading && metric.change != null && (
              <span
                className={`text-xs tabular-nums ${trendClass(metric.change)}`}
              >
                {signedMoney(metric.change)}
              </span>
            )}
          </div>
          {loading ? (
            <Skeleton className="h-3 w-24" />
          ) : (
            <div className="text-muted-foreground text-xs">
              <span className={trendClass(metric.trendValue)}>
                {metric.trendText}
              </span>{' '}
              {metric.trendSuffix}
            </div>
          )}
          {/* 序列不足(无快照/建仓不足一周)时不画迷你图,避免拿两三个点冒充走势 */}
          {loading ? (
            <Skeleton className="h-12 w-full" />
          ) : (
            metric.spark.length > 1 && (
              <MetricSparkline
                data={metric.spark}
                trendValue={metric.trendValue}
              />
            )
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}

export function DashboardCards() {
  const { data: trend, isLoading: trendLoading } = usePortfolioTrend();
  // 四张卡的当前值取「最新一条快照」(与快照管理页逐位一致):列表新→旧,第一行即最新;
  // 没有「最新一条」专用端点,pageSize=1 的这次请求很轻
  const { data: snapshotPage, isLoading: snapshotLoading } = useSnapshotList(
    1,
    1,
    EMPTY_SNAPSHOT_RANGE,
  );
  const latest = snapshotPage?.data?.[0];
  // 首屏用骨架而不是先摆一排「—」:空值代表"确实没有数据",不能和"还在加载"混用
  const loading = trendLoading || snapshotLoading;

  const metrics = useMemo<Metric[]>(() => {
    const points = trend ?? [];
    const valueSeries = points.map((p) => p.totalValue);
    const investedSeries = points.map((p) => p.totalInvested);
    const profitSeries = points.map((p) => p.profit);
    const rateSeries = points.map((p) => p.profitRate);

    const valueWow = weekOverWeek(valueSeries);
    const investedWow = weekOverWeek(investedSeries);
    const profitWow = weekOverWeek(profitSeries);
    // 累计盈亏率本身是百分比,环比取**百分点差**(再算百分比会读成"涨幅的涨幅");展示按 % 写
    const rateWow = weekOverWeek(rateSeries);

    // 降级只作用于真正缺的那个数:该日没有现金流行(累计投入为 null)时,总市值照样显示
    const totalValue = latest?.totalValue ?? null;
    const cumulativeInvested = latest?.cumulativeInvested ?? null;
    const totalProfit =
      totalValue != null && cumulativeInvested != null
        ? totalValue - cumulativeInvested
        : null;
    // 累计盈亏率 = 总盈亏 ÷ 累计投入;投入为 0 不可除,交给下面的「—」降级
    const totalRate =
      totalProfit != null &&
      cumulativeInvested != null &&
      cumulativeInvested !== 0
        ? (totalProfit / cumulativeInvested) * 100
        : null;

    const built: Metric[] = [
      {
        label: '总市值',
        value: totalValue,
        format: formatMoney,
        change: valueWow?.change ?? null,
        // 着色跟金额增量的符号:变化率在基准为 0(一周前未建仓)时无意义,文字降级为 —
        trendValue: valueWow?.change ?? 0,
        trendText:
          valueWow?.rate != null ? signedPct(valueWow.rate) : EMPTY_VALUE,
        trendSuffix: '较上周',
        spark: valueSeries,
      },
      {
        label: '累计投入',
        value: cumulativeInvested,
        format: formatMoney,
        change: investedWow?.change ?? null,
        trendValue: investedWow?.change ?? 0,
        trendText:
          investedWow?.rate != null ? signedPct(investedWow.rate) : EMPTY_VALUE,
        trendSuffix: '较上周',
        spark: investedSeries,
      },
      {
        label: '总盈亏',
        value: totalProfit,
        format: signedMoney,
        change: profitWow?.change ?? null,
        trendValue: profitWow?.change ?? 0,
        trendText:
          profitWow?.rate != null ? signedPct(profitWow.rate) : EMPTY_VALUE,
        trendSuffix: '较上周',
        spark: profitSeries,
      },
      {
        label: '累计盈亏率',
        value: totalRate,
        format: signedPct,
        change: null,
        // 环比不可得时给 —:显示「0.00%」等于把「没数据」说成「上周零变动」
        trendValue: rateWow?.change ?? 0,
        // 值是两个收益率之差的百分点差,按 % 呈现(与其余三张卡的百分比文案同一写法)
        trendText: rateWow != null ? signedPct(rateWow.change) : EMPTY_VALUE,
        trendSuffix: '较上周',
        spark: rateSeries,
      },
    ];
    // 缺数据的那张卡整体降级:值已是「—」,这里把金额增量/环比/走势线一并收掉,
    // 否则会出现「值是破折号、旁边却还挂着数字与一条线」的混展示
    return built.map((metric) =>
      metric.value == null
        ? { ...metric, change: null, trendText: EMPTY_VALUE, spark: [] }
        : metric,
    );
  }, [latest, trend]);

  return (
    <div className="grid grid-cols-1 gap-4 @xl/main:grid-cols-2 @5xl/main:grid-cols-4">
      {metrics.map((metric, index) => (
        <MetricCard
          key={metric.label}
          metric={metric}
          index={index}
          loading={loading}
        />
      ))}
    </div>
  );
}

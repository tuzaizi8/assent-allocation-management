// src/features/snapshots/components/quarterly-change-card.tsx —— 季度持仓变化卡片
// 左右两半:左边饼图(按 fund_type 聚合的本季市值占比,照 portfolio-share-pie 的
// shadcn 官方范式),右边相邻季度持仓变动表(模仿基金季报)。
// 变化对比全部在前端算(后端只交付季度序列),相邻匹配键是 fund_code。
// 状态与排序裁决(2026-10-12):只有变化恰为 0 才持平,±0.01pp 都算加/减仓;
// 全部按本季占比降序列入同一张表(新进自然居前、退出垫底),退出用 -、持平用 =;
// 变化单位用 %(百分点),表格内容定宽、超出横向滑动。
import { ArrowDownRight, ArrowUpRight, Equal, Minus, Plus } from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';
import { Cell, Pie, PieChart } from 'recharts';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
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
  useQuarterlySnapshots,
  type QuarterlyFund,
  type QuarterlyQuarter,
} from '@/features/snapshots/api/get-snapshots';

/** 变动表的一行:在仓基金(含新进)与退出基金统一成同一形状 */
type ChangeRow = {
  fundCode: string;
  fundName: string;
  /** 上季占比;新进基金为 null */
  prevRatio: number | null;
  /** 本季占比;退出基金为 null */
  currRatio: number | null;
  /** 占比变化(百分点,正加负减);新进/退出为 null */
  delta: number | null;
  status: 'new' | 'increase' | 'decrease' | 'flat' | 'exit';
};

const STATUS_BADGE: Record<
  ChangeRow['status'],
  { label: string; className: string; icon: ReactNode }
> = {
  new: {
    label: '新进',
    className: 'bg-primary/10 text-primary',
    icon: <Plus className="size-3" />,
  },
  increase: {
    label: '加仓',
    className: 'bg-transparent text-profit',
    icon: <ArrowUpRight className="size-3" />,
  },
  decrease: {
    label: '减仓',
    className: 'bg-transparent text-loss',
    icon: <ArrowDownRight className="size-3" />,
  },
  flat: {
    label: '持平',
    className: 'bg-transparent text-muted-foreground',
    icon: <Equal className="size-3" />,
  },
  exit: {
    label: '退出',
    className: 'bg-transparent text-muted-foreground',
    icon: <Minus className="size-3" />,
  },
};

/** 与 index.css 的 --pie-1..5 一一对应(shadcn 默认 chart 色板),N 片按序循环 */
const PIE_COLORS = [
  'var(--pie-1)',
  'var(--pie-2)',
  'var(--pie-3)',
  'var(--pie-4)',
  'var(--pie-5)',
];

function quarterLabel(q: QuarterlyQuarter): string {
  const [y, m] = q.quarterEnd.split('-');
  return `${y}Q${Math.ceil(Number(m) / 3)}`;
}

function fundDisplayName(f: QuarterlyFund): string {
  return f.fundName || `（已删）${f.fundCode}`;
}

export function QuarterlyChangeCard() {
  const { data, isLoading } = useQuarterlySnapshots();
  const quarters = useMemo(() => data?.quarters ?? [], [data]);
  // 对比对:取相邻两季(默认最新一对);index 指向后一季(变化发生在 prev→curr)
  const [pairIndex, setPairIndex] = useState<number | null>(null);

  const pairs = useMemo(
    () => quarters.slice(1).map((curr, i) => ({ prev: quarters[i], curr })),
    [quarters],
  );
  const activePair =
    pairs.length > 0
      ? pairs[
          pairIndex != null
            ? Math.min(pairIndex, pairs.length - 1)
            : pairs.length - 1
        ]
      : null;

  // 变动表分两段:在仓(新进/加仓/减仓/持平)按本季占比降序;退出不参与在仓排序,
  // 追加在最后、按上季占比降序(2026-10-12 用户裁决)
  const rows = useMemo<ChangeRow[]>(() => {
    if (!activePair) return [];
    const prevMap = new Map(activePair.prev.funds.map((f) => [f.fundCode, f]));
    const currMap = new Map(activePair.curr.funds.map((f) => [f.fundCode, f]));
    const inMarket: ChangeRow[] = activePair.curr.funds.map((curr) => {
      const prev = prevMap.get(curr.fundCode);
      if (!prev) {
        return {
          fundCode: curr.fundCode,
          fundName: fundDisplayName(curr),
          prevRatio: null,
          currRatio: curr.ratio,
          delta: null,
          status: 'new',
        };
      }
      const delta = Math.round((curr.ratio - prev.ratio) * 100) / 100;
      const status: ChangeRow['status'] =
        delta === 0 ? 'flat' : delta > 0 ? 'increase' : 'decrease';
      return {
        fundCode: curr.fundCode,
        fundName: fundDisplayName(curr),
        prevRatio: prev.ratio,
        currRatio: curr.ratio,
        delta,
        status,
      };
    });
    inMarket.sort((a, b) => (b.currRatio ?? 0) - (a.currRatio ?? 0));
    const exited: ChangeRow[] = activePair.prev.funds
      .filter((f) => !currMap.has(f.fundCode))
      .map((f) => ({
        fundCode: f.fundCode,
        fundName: fundDisplayName(f),
        prevRatio: f.ratio,
        currRatio: null,
        delta: null,
        status: 'exit',
      }));
    exited.sort((a, b) => (b.prevRatio ?? 0) - (a.prevRatio ?? 0));
    return [...inMarket, ...exited];
  }, [activePair]);

  // 左侧饼图:本季持仓按 fund_type 聚合市值;类型名缺失兜底「未分类」。
  // 每片带上该类型的基金明细(code/name/占比)——hover 展示「这个类型里都有谁」
  const typeSlices = useMemo(() => {
    if (!activePair) return [];
    const agg = new Map<
      string,
      { value: number; funds: { code: string; name: string; ratio: number }[] }
    >();
    for (const f of activePair.curr.funds) {
      const key = f.fundType || '未分类';
      const entry = agg.get(key) ?? { value: 0, funds: [] };
      entry.value += f.marketValue;
      entry.funds.push({
        code: f.fundCode,
        name: fundDisplayName(f),
        ratio: f.ratio,
      });
      agg.set(key, entry);
    }
    const total = [...agg.values()].reduce((a, b) => a + b.value, 0);
    return [...agg.entries()]
      .sort((a, b) => b[1].value - a[1].value)
      .map(([type, entry], i) => ({
        name: type,
        value: entry.value,
        percent: total > 0 ? (entry.value / total) * 100 : 0,
        fill: PIE_COLORS[i % PIE_COLORS.length],
        funds: entry.funds.sort((a, b) => b.ratio - a.ratio),
      }));
  }, [activePair]);

  // shadcn 范式:config 键 = 类型名,ChartStyle 据此生成 --color-类型,Cell 的 fill 引用之
  const chartConfig = Object.fromEntries(
    typeSlices.map((slice) => [
      slice.name,
      { label: slice.name, color: slice.fill },
    ]),
  ) as ChartConfig;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="text-base">季度持仓变化</CardTitle>
        {pairs.length > 0 && (
          <Select
            value={String(pairIndex != null ? pairIndex : pairs.length - 1)}
            onValueChange={(v) => setPairIndex(Number(v))}
          >
            <SelectTrigger className="w-44">
              <SelectValue placeholder="选择季度" />
            </SelectTrigger>
            <SelectContent>
              {pairs.map((pair, i) => (
                <SelectItem key={i} value={String(i)}>
                  {quarterLabel(pair.prev)} → {quarterLabel(pair.curr)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </CardHeader>
      <CardContent>
        {isLoading && (
          // 与内容同布局的骨架:饼图块与变动表各一块,加载完不跳版
          <div className="grid gap-6 lg:grid-cols-2">
            <Skeleton className="mx-auto h-[300px] w-full max-w-[260px] rounded-xl" />
            <Skeleton className="h-[380px] w-full rounded-xl" />
          </div>
        )}
        {!isLoading && pairs.length === 0 && (
          <p className="text-muted-foreground py-6 text-center text-sm">
            至少需要两个季度末的记录才能对比，先去补录历史交易吧。
          </p>
        )}
        {!isLoading && activePair && (
          // 换季度时整块重挂载:饼图重新播入场,变动行依次出现,避免数字原地跳变
          <div
            key={`${activePair.prev.quarterEnd}:${activePair.curr.quarterEnd}`}
            className="animate-in fade-in-0 grid gap-6 duration-200 motion-reduce:animate-none lg:grid-cols-2"
          >
            {/* ===== 左:本季基金类型占比饼图(fund.fund_type 聚合) ===== */}
            <div className="flex flex-col gap-2">
              <span className="text-muted-foreground text-xs">
                {quarterLabel(activePair.curr)} 基金类型占比
              </span>
              {/* 饼图+图例套共同容器:浅底+边框+内边距,明确"一组"的视觉归属 */}
              <div>
                <ChartContainer
                  config={chartConfig}
                  // ResponsiveContainer 按父级测量尺寸:flex-col+items-center 下必须给确定宽度,否则量出 0 高整图消失;
                  // 高度贴合饼直径(172px)+少量余量,避免 aspect-square 的上下空隙把图例推远
                  className="mx-auto h-[188px] w-full max-w-[240px]"
                >
                  <PieChart>
                    <ChartTooltip
                      cursor={false}
                      content={({ active, payload }) => {
                        if (!active || !payload?.length) return null;
                        const slice = payload[0]
                          .payload as (typeof typeSlices)[number];
                        return (
                          <div className="border bg-popover rounded-lg px-3 py-2 text-xs shadow-md min-w-48">
                            <div className="mb-1 font-medium">
                              {slice.name}
                              <span className="text-muted-foreground ml-2 tabular-nums">
                                {slice.percent.toFixed(2)}%
                              </span>
                            </div>
                            <div className="flex flex-col gap-0.5">
                              {slice.funds.map((fund) => (
                                <div
                                  key={fund.code}
                                  className="flex items-center justify-between gap-4"
                                >
                                  <span className="text-muted-foreground truncate">
                                    {fund.name}
                                  </span>
                                  <span className="tabular-nums">
                                    {fund.ratio.toFixed(2)}%
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        );
                      }}
                    />
                    <Pie
                      data={typeSlices}
                      dataKey="value"
                      nameKey="name"
                      innerRadius={48}
                      outerRadius={86}
                      paddingAngle={2}
                      strokeWidth={2}
                    >
                      {typeSlices.map((slice) => (
                        <Cell
                          key={slice.name}
                          fill={`var(--color-${slice.name})`}
                        />
                      ))}
                    </Pie>
                  </PieChart>
                </ChartContainer>
                {/* 图例:手写横排(recharts Legend 在此布局下竖排乱套,hover 才是 shadcn 官方件) */}
                <div className="mx-auto mt-3 grid w-fit grid-cols-2 gap-x-3 gap-y-1 text-xs">
                  {typeSlices.map((slice) => (
                    <div key={slice.name} className="flex items-center gap-1.5">
                      <span className="flex min-w-0 items-center gap-1.5">
                        <span
                          className="size-2.5 shrink-0 rounded-[2px]"
                          style={{ backgroundColor: slice.fill }}
                        />
                        <span className="truncate">{slice.name}</span>
                      </span>
                      <span className="tabular-nums">
                        {slice.percent.toFixed(1)}%
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* ===== 右:相邻季度持仓变动表(统一一张表,退出垫底) ===== */}
            {/* 定高与左饼图块对齐,超出纵向滚动;行内容定宽超出横向滑动 */}
            <div className="max-h-[380px] overflow-y-auto">
              <div className="flex flex-col gap-2">
                <div className="text-muted-foreground grid grid-cols-[1fr_64px_64px_64px_60px] items-center gap-x-2.5 border-b pb-1.5 text-xs">
                  <span>基金</span>
                  <span className="text-right">
                    {quarterLabel(activePair.prev)}
                  </span>
                  <span className="text-right">
                    {quarterLabel(activePair.curr)}
                  </span>
                  <span className="text-right">变化</span>
                  <span className="text-center">状态</span>
                </div>
                {rows.map((row, rowIndex) => {
                  const badge = STATUS_BADGE[row.status];
                  const deltaColor =
                    row.delta == null
                      ? 'text-muted-foreground'
                      : row.delta > 0
                        ? 'text-profit'
                        : row.delta < 0
                          ? 'text-loss'
                          : 'text-muted-foreground';
                  return (
                    <div
                      key={row.fundCode}
                      className="animate-in fade-in-0 fill-mode-both grid grid-cols-[1fr_64px_64px_64px_60px] items-center gap-x-2.5 border-b py-1.5 text-sm duration-150 motion-reduce:animate-none last:border-b-0"
                      style={{
                        animationDelay: `${Math.min(rowIndex, 8) * 20}ms`,
                      }}
                    >
                      <span className="truncate">
                        {row.fundName}
                        <span className="text-muted-foreground ml-1.5 text-xs">
                          {row.fundCode}
                        </span>
                      </span>
                      <span className="text-muted-foreground text-right tabular-nums">
                        {row.prevRatio == null
                          ? '—'
                          : `${row.prevRatio.toFixed(2)}%`}
                      </span>
                      <span className="text-right font-medium tabular-nums">
                        {row.currRatio == null
                          ? '—'
                          : `${row.currRatio.toFixed(2)}%`}
                      </span>
                      <span className={`text-right tabular-nums ${deltaColor}`}>
                        {row.delta == null
                          ? '—'
                          : `${row.delta > 0 ? '+' : ''}${row.delta.toFixed(2)}%`}
                      </span>
                      <span className="flex justify-center">
                        <Badge
                          variant="outline"
                          className={`${badge.className} gap-0.5 px-1.5`}
                        >
                          {badge.icon}
                          {badge.label}
                        </Badge>
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

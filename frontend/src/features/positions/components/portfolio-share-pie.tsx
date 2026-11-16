// src/features/positions/components/portfolio-share-pie.tsx —— 持仓简况页「持仓占比」饼图卡
// **照 shadcn 官方参考实现**(ui.shadcn.com 的 Pie Chart - Label):recharts 原生片外标签 +
// 引导线 + 入场动画。此前两轮自研(蓝色渐变无区分度、片内标注挤压小仓)均被否,
// 结论留档在知识库 04 §1.1——不再自研标注/避让/配色算法。
// 与参考仅两点差异(均为本页刚需):① 5 色对 N 片循环(index % 5,相邻片必不同色);
// ② tooltip 的 formatter 做金额脱敏(跟随页面「眼睛」开关)。
import { memo, useEffect, useMemo, useRef } from 'react';
import type { RefObject } from 'react';
import { Pie, PieChart } from 'recharts';

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
import type { PositionDetail } from '@/features/positions/api/get-positions';
import { formatMoney } from '@/utils/format';

/** 与 index.css 的 --pie-1..5 一一对应(shadcn 默认 chart 色板),N 片按序循环 */
const PIE_COLORS = [
  'var(--pie-1)',
  'var(--pie-2)',
  'var(--pie-3)',
  'var(--pie-4)',
  'var(--pie-5)',
];

/** 一片:fill 直接挂在数据行上(shadcn 范式),tooltip 从 payload 里取基金名/占比 */
export type ShareSlice = {
  fundName: string;
  value: number;
  percent: number;
  fill: string;
};

/** 最多展示的切片数:前 TOP_N 大各自成片 + 1 片「其他」 */
const TOP_N = 9;
/** 超过该支数才出现「其他」:恰好 10 支时全部实名展示,"其他(1 支)"会无意义地藏掉一支的名字 */
const AGGREGATE_ABOVE = TOP_N + 1;
/** 副标题统计的「前 N 大」集中度:与分片边界(TOP_N=9)无关——第 10 名当前被并在「其他」里,仍要计入 */
const TOP_SHARE_COUNT = 10;

/**
 * 聚合规则:按市值降序后,前 TOP_N 支各自成片;剩余支数 > 1 时合并为一片「其他」
 * (value = 剩余市值之和)。percent = 该片市值 ÷ **全部持仓**总市值,
 * 故「其他」的占比天然等于剩余各支之和(Σpercent = 1)。
 */
export function buildShareSlices(positions: PositionDetail[]): ShareSlice[] {
  const ordered = [...positions].sort(
    (left, right) => right.currentValue - left.currentValue,
  );
  const total = ordered.reduce((sum, p) => sum + p.currentValue, 0);
  const toSlice = (
    fundName: string,
    value: number,
    index: number,
  ): ShareSlice => ({
    fundName,
    value,
    percent: total > 0 ? value / total : 0,
    fill: PIE_COLORS[index % PIE_COLORS.length],
  });
  if (ordered.length <= AGGREGATE_ABOVE) {
    return ordered.map((position, index) =>
      toSlice(position.fundName, position.currentValue, index),
    );
  }
  const top = ordered
    .slice(0, TOP_N)
    .map((position, index) =>
      toSlice(position.fundName, position.currentValue, index),
    );
  const restValue = ordered
    .slice(TOP_N)
    .reduce((sum, position) => sum + position.currentValue, 0);
  return [...top, toSlice('其他', restValue, TOP_N)];
}

/**
 * 前 N 大(按市值降序)合计占比(%)= 前 N 名市值之和 ÷ 全部持仓总市值 × 100——卡头副标题的集中度。
 * **不能拿上面的切片求和**:切片是「前 TOP_N=9 实名 + 一片其他」,10 片之和恒等于总市值(100%),
 * 没有信息量;要的是第 10 名(当前被并在「其他」里)也计入。N 超过持仓数即全部持仓 ⇒ 100%;
 * 总市值为 0(无持仓或市值全 0)返回 0,避免渲染出 NaN。
 */
export function topFundsShare(
  positions: PositionDetail[],
  topN = TOP_SHARE_COUNT,
): { count: number; percent: number } {
  const count = Math.min(topN, positions.length);
  const total = positions.reduce((sum, p) => sum + p.currentValue, 0);
  if (total <= 0) return { count, percent: 0 };
  const topSum = [...positions]
    .sort((left, right) => right.currentValue - left.currentValue)
    .slice(0, topN)
    .reduce((sum, p) => sum + p.currentValue, 0);
  return { count, percent: (topSum / total) * 100 };
}

const chartConfig = {
  value: { label: '持仓市值' },
} satisfies ChartConfig;

/**
 * 饼图子树:**必须 memo**,别删——本页的眼睛脱敏开关与表格排序都是 useState,点一下整页重渲染,
 * 而 recharts 3.8.0 的 Pie 用 useAnimationId 按 **props 对象的引用**判断"要不要重播动画"
 * (polar/Pie.js:618 的 resolveDefaultProps 每次返回新对象 ⇒ 每次重渲染都换 animationId,
 * JavascriptAnimate 因 key 变化被重挂载从头播;且动画期间 showLabels=false ⇒ 片外百分比整片消失再画出),
 * 于是"点眼睛/点排序"会看到标签反复闪——与业务无关。这里只接收引用稳定的 slices 与引用恒定的
 * hiddenRef,让子树被 memo 跳过:上述操作不再重渲染它,只有持仓数据真的变了才重播一次。
 */
const SharePieChart = memo(function SharePieChart({
  slices,
  hiddenRef,
}: {
  slices: ShareSlice[];
  /** 脱敏开关走 ref:引用恒定,故切它不会让本子树重渲染;formatter 在 hover 时读到的仍是最新值 */
  hiddenRef: RefObject<boolean>;
}) {
  return (
    // 图表区吃满卡片剩余高度(h-full,不写死像素):卡片加高后饼随之同比放大、底部不留白;
    // 右侧让出 w-32 给图例 ⇒ 用 flex-1 + min-w-0,并把外径收到 70%(留足片外标签的横向余量)
    <ChartContainer
      config={chartConfig}
      className="aspect-auto h-full min-w-0 flex-1 pb-0 [&_.recharts-pie-label-text]:fill-foreground"
    >
      <PieChart>
        <ChartTooltip
          cursor={false}
          content={
            <ChartTooltipContent
              hideLabel
              formatter={(value, name, item) => {
                const row = item?.payload as ShareSlice | undefined;
                return (
                  <div className="flex w-full items-center justify-between gap-3">
                    <span className="text-muted-foreground">
                      {row?.fundName ?? String(name ?? '')}
                    </span>
                    <span className="font-mono font-medium tabular-nums">
                      {hiddenRef.current
                        ? '¥****'
                        : formatMoney(row?.value ?? Number(value))}
                      <span className="text-muted-foreground ml-1.5">
                        {((row?.percent ?? 0) * 100).toFixed(1)}%
                      </span>
                    </span>
                  </div>
                );
              }}
            />
          }
        />
        {/* 原生片外标签 + 引导线 + 动画:与 shadcn 参考一致。
            唯一替换的是文本——参考默认渲染 dataKey 原始值(市值),这里改显百分比;
            x/y/textAnchor 仍是 recharts 自己算好的片外位置,引导线也由它绘制,不自研布局 */}
        <Pie
          data={slices}
          dataKey="value"
          nameKey="fundName"
          // 外径收到 70%(默认约 80%):片外标签在窄侧也留得住横向余量,不会被 SVG 裁掉
          outerRadius="70%"
          label={({ x, y, textAnchor, percent }) => {
            if (x == null || y == null || percent == null) return null;
            return (
              <text
                x={x}
                y={y}
                textAnchor={textAnchor}
                dominantBaseline="central"
                className="fill-foreground text-xs"
              >
                {(percent * 100).toFixed(1)}%
              </text>
            );
          }}
        />
      </PieChart>
    </ChartContainer>
  );
});

export function PortfolioSharePieCard({
  positions,
  hidden,
}: {
  positions: PositionDetail[];
  /** 隐私开关:浮层里的金额跟随脱敏,占比百分比不属于金额、照常显示 */
  hidden: boolean;
}) {
  const slices = useMemo<ShareSlice[]>(
    () => buildShareSlices(positions),
    [positions],
  );
  const topShare = useMemo(() => topFundsShare(positions), [positions]);
  // 图表子树只认 ref(引用恒定),故用 effect 把最新值同步进去——不在渲染期写 ref
  const hiddenRef = useRef(hidden);
  useEffect(() => {
    hiddenRef.current = hidden;
  }, [hidden]);

  // 卡片高度与左侧「简易持仓」表卡同值(377px = 那卡的 8 行定高公式),两卡并排等高
  return (
    <Card className="flex h-[377px] flex-col gap-0 overflow-hidden py-0 shadow-sm shadow-black/5">
      <CardHeader className="py-4">
        <CardTitle>持仓占比</CardTitle>
        {/* 副标题由「合计 ¥X」改为集中度:金额随脱敏藏起来了,而"前十只占多少"才是看这张饼图时
            真正想知道的;百分比不属于金额、照常显示(与 tooltip 的口径一致) */}
        <CardDescription>
          {topShare.count > 0
            ? `前 ${topShare.count} 只基金占比为 ${topShare.percent.toFixed(1)}%`
            : '暂无持仓'}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 gap-2 pb-4">
        <SharePieChart slices={slices} hiddenRef={hiddenRef} />
        {/* 图例:色块与扇区**同色同序**(都取自 slices) ⇒ 一眼看出哪片是哪支(片上只标百分比);
            名称过长截断为省略号,悬浮看全名;聚合后最多 10 行,超高可滚动 */}
        <ul className="flex w-32 shrink-0 flex-col justify-center gap-1 overflow-y-auto text-xs">
          {slices.map((slice) => (
            <li key={slice.fundName} className="flex items-center gap-1.5">
              <span
                className="size-2.5 shrink-0 rounded-[2px]"
                style={{ backgroundColor: slice.fill }}
              />
              <span className="min-w-0 flex-1 truncate" title={slice.fundName}>
                {slice.fundName}
              </span>
              <span className="text-muted-foreground shrink-0 tabular-nums">
                {(slice.percent * 100).toFixed(1)}%
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

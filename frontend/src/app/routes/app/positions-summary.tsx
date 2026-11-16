// 持仓简况页 —— 只看有效持仓(后端 list 默认排除已全部赎回的软删行)
// 数据是一次拉回的全量(useAllPositions),排序在客户端做即可:三列仍不值得引入 TanStack 实例,
// 表头交互复用 shared/data-table-column-header 的 SortableHeaderButton(与明细页同一视觉);
// 纯概览只读:无行点击下钻(明细看持仓明细页),入口只有底部「查看全部」
import {
  ArrowRightIcon,
  ChevronRightIcon,
  EyeIcon,
  EyeOffIcon,
} from 'lucide-react';
import { motion, useReducedMotion } from 'motion/react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router';

import { SortableHeaderButton } from '@/components/shared/data-table-column-header';
import type { SortDirection } from '@/components/shared/data-table-column-header';
import { EmptyStateArt } from '@/components/shared/empty-state-art';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Spinner } from '@/components/ui/spinner';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { paths } from '@/config/paths';
import { useDailyFundProfit } from '@/features/dashboard/api/get-portfolio-analytics';
import {
  useAllPositions,
  type PositionDetail,
} from '@/features/positions/api/get-positions';
import { PortfolioSharePieCard } from '@/features/positions/components/portfolio-share-pie';
import {
  useSnapshotList,
  type SnapshotRange,
} from '@/features/snapshots/api/get-snapshots';
import { useCountUp } from '@/hooks/use-count-up';
import {
  formatDate,
  formatMoney,
  profitClass,
  signedNum,
  signedPct,
} from '@/utils/format';

// 稳定空数组兜底(引用稳定习惯,与明细页一致)
const EMPTY_POSITIONS: PositionDetail[] = [];
// 空区间 = 走后端默认区间;引用稳定,避免每次渲染新对象引发重复请求
const EMPTY_SNAPSHOT_RANGE: SnapshotRange = {};

/** 日收益行:两档并列接口的行结构(只取本页需要的字段,避免重复建模) */
type DailyProfitRow = { dailyProfit: number };

/**
 * 净值日 ISO 串 → 「9月23日」:标签上只挂月日,去前导零后与「已更新」连读自然。
 * 仍不做 new Date(iso):'2026-09-23' 会按 UTC 午夜解析,负时区会退回前一日;
 * 后端契约就是 YYYY-MM-DD,切字符串零风险。空串/不合规返回 null(该格不挂 Badge)。
 */
const toChineseDate = (iso?: string): string | null => {
  const parts = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '');
  return parts ? `${Number(parts[2])}月${Number(parts[3])}日` : null;
};

/** 已更新态的红绿:红涨绿跌,淡色底 + 同色字一样走语义 token;零值不着色(与 profitClass 同口径) */
const updatedToneClass = (value: number) =>
  value > 0
    ? 'bg-profit/10 text-profit'
    : value < 0
      ? 'bg-loss/10 text-loss'
      : '';

/** 简况页可排序列(两列都是派生指标,排序在本页做) */
type SummarySortKey = 'currentValue' | 'profitRate';

type SummarySorting = { key: SummarySortKey; desc: boolean };

/** 点同列翻方向;换列则从该列降序开始(金额类列先看大的,与明细页一致) */
const toggleSort = (
  current: SummarySorting,
  key: SummarySortKey,
): SummarySorting => ({
  key,
  desc: current.key === key ? !current.desc : true,
});

export default function PositionsSummaryRoute() {
  const { data: positions = EMPTY_POSITIONS, isLoading } = useAllPositions();
  // 隐私开关:金额默认明文,点击眼睛整卡脱敏(截图/投屏场景)
  const [hidden, setHidden] = useState(false);
  // 默认市值降序:卡片定高截断只留前 7 支,排序决定留下的是哪几支
  const [sorting, setSorting] = useState<SummarySorting>({
    key: 'currentValue',
    desc: true,
  });

  // 客户端排序:不改原数组;同值按 positionId 兜底,顺序稳定
  const sortedPositions = useMemo(() => {
    const factor = sorting.desc ? -1 : 1;
    return [...positions].sort(
      (left, right) =>
        (left[sorting.key] - right[sorting.key]) * factor ||
        left.positionId - right.positionId,
    );
  }, [positions, sorting]);

  const directionOf = (key: SummarySortKey): SortDirection =>
    sorting.key === key ? (sorting.desc ? 'desc' : 'asc') : false;
  const { data: dailyFundProfit } = useDailyFundProfit();
  // 「今日」档是否有数据:数值与净值日 Badge 共用这一判定,避免出现"挂着日期却显示 —"的错配
  const hasLatestProfit = (dailyFundProfit?.latest.length ?? 0) > 0;
  const latestNavDate = hasLatestProfit
    ? (dailyFundProfit?.latestNavDate ?? '')
    : '';
  // 「已更新」⇔ 该档净值日就是今天:后端当晚把当日净值写进 Redis 后 latestNavDate 才滚到今天,
  // 所以白天(尚未收盘/尚未入库)与过了零点的次日都是"不是今天"⇒ 只显示净值日、不标已更新。
  // 用 formatDate 取本地今天再比字符串(同格式),避免 new Date(净值日) 按 UTC 解析退一日。
  const todayUpdated =
    latestNavDate !== '' &&
    latestNavDate.slice(0, 10) === formatDate(new Date());
  // 累计盈亏取「最新一条快照」口径(与快照管理页逐位一致):列表新→旧,故第一行即最新;
  // 没有「最新一条」专用端点,pageSize=1 的这次请求很轻
  const { data: snapshotPage } = useSnapshotList(1, 1, EMPTY_SNAPSHOT_RANGE);
  const latestSnapshot = snapshotPage?.data?.[0];
  // 快照盈亏 = 当日快照市值 − 同日累计净投入(cumulativeInvested);该日无现金流记录时缺值 →
  // 显示「—」而不是伪造 0(与快照管理页同一处理)
  const snapshotProfit =
    latestSnapshot && latestSnapshot.cumulativeInvested != null
      ? latestSnapshot.totalValue - latestSnapshot.cumulativeInvested
      : null;

  // 派生指标放进一次遍历 + useMemo:隐私开关切换时不必重算(此前每次渲染跑两轮 reduce + 双层嵌套)
  const metrics = useMemo(() => {
    let totalValue = 0;
    let holdingProfit = 0;
    for (const position of positions) {
      totalValue += position.currentValue;
      // 持有收益 = **当前所有有效持仓**的持有收益汇总(每条持仓「市值 − 结转后成本」之和)。
      // 口径就这么定义,勿改成别的算法:它只回答「现在拿着的这些赚了多少」,
      // 历史已实现的盈亏不在其中——那部分由下面的「累计盈亏」(快照口径)负责
      holdingProfit += position.profit;
    }
    // 日收益来自两档并列接口:昨日=上一净值日、今日=最新净值日,各自独立求和——
    // 今日买入的份额昨日并不持有,后端按「上一净值日已持有份额」算好,前端只求和不再推算
    const sumProfit = (rows?: DailyProfitRow[]) =>
      (rows ?? []).reduce((sum, row) => sum + row.dailyProfit, 0);
    return {
      totalValue,
      holdingProfit,
      // 上一净值日一档为空(建仓不足两个净值日)时给 null:显示「—」而不是伪造一个 0 收益,
      // 与今日档同口径
      yesterdayProfit:
        (dailyFundProfit?.prev.length ?? 0) > 0
          ? sumProfit(dailyFundProfit?.prev)
          : null,
      todayProfit: sumProfit(dailyFundProfit?.latest),
    };
  }, [positions, dailyFundProfit]);

  const reduceMotion = useReducedMotion();
  // 汇总值从 0 滚到当前市值:切换隐私开关时只换文案,不重播滚动
  const totalDisplay = useCountUp(metrics.totalValue, {
    enabled: !reduceMotion,
  });

  return (
    <div className="flex flex-col gap-4">
      {/* ===== 汇总大卡:第一层总市值独占,第二层三项收益等分 ===== */}
      {positions.length > 0 && (
        <Card className="animate-in fade-in-0 gap-0 py-0 shadow-sm shadow-black/5 duration-200 motion-reduce:animate-none">
          <div className="px-6 py-6">
            <div className="text-center text-lg leading-none font-medium text-foreground">
              总市值
            </div>
            <div className="mt-3.5 flex items-center justify-center gap-2">
              {/* leading-none 收掉 2.5rem 自带的行高留白,否则第一层被撑高、与第二层显得脱节 */}
              <span className="text-[2.5rem] leading-none font-semibold tabular-nums">
                {hidden
                  ? '¥****'
                  : totalDisplay == null
                    ? '—'
                    : formatMoney(totalDisplay)}
              </span>
              <button
                type="button"
                onClick={() => setHidden((prev) => !prev)}
                aria-label={hidden ? '显示金额' : '隐藏金额'}
                className="text-muted-foreground hover:text-foreground cursor-pointer transition-colors"
              >
                {hidden ? (
                  <EyeOffIcon className="size-6" />
                ) : (
                  <EyeIcon className="size-6" />
                )}
              </button>
            </div>
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-4">
            <MetricBlock
              label="昨日收益（元）"
              value={metrics.yesterdayProfit}
              hidden={hidden}
              // 净值日只在该档有数据时才挂(取值就是 value 的那次判空),日期与金额同源不会错配
              navDate={
                metrics.yesterdayProfit == null
                  ? null
                  : dailyFundProfit?.prevNavDate
              }
            />
            <MetricBlock
              label="今日收益（元）"
              value={hasLatestProfit ? metrics.todayProfit : null}
              hidden={hidden}
              navDate={latestNavDate || null}
              // 「已更新」只在净值日就是今天时出现;脱敏时不给色——金额都藏起来了,
              // 再按涨跌上红绿等于把刚藏起来的涨跌方向漏出去
              navDateSuffix={todayUpdated ? '已更新' : undefined}
              navDateClass={
                todayUpdated && !hidden
                  ? updatedToneClass(metrics.todayProfit)
                  : undefined
              }
            />
            <MetricBlock
              label="持有收益（元）"
              value={metrics.holdingProfit}
              hidden={hidden}
            />
            <MetricBlock
              label="累计盈亏（元）"
              value={snapshotProfit}
              hidden={hidden}
            />
          </div>
        </Card>
      )}

      {/* ===== 简易表格(Card 承载:Table 根不带边框,由 Card 圆角边框收视觉) ===== */}
      {isLoading ? (
        // 骨架与真实布局同高:大卡 + 两列卡片,加载完不跳版
        <div
          className="flex flex-col gap-4"
          data-testid="positions-summary-loading"
        >
          <Skeleton className="h-[188px] w-full rounded-xl" />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Skeleton className="h-[377px] rounded-xl" />
            <Skeleton className="h-[377px] rounded-xl" />
          </div>
          <Spinner className="sr-only" />
        </div>
      ) : positions.length === 0 ? (
        <EmptyGuide />
      ) : (
        // 双列栅格:左「简易持仓」表、右「持仓占比」饼图卡,两卡同高 377px;窄屏回落单列
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {/* 高度恒定预留 8 支(表头 40+1 + 8×36 + 7×1 分隔线 + footer 40+1 = 377px),无滚动条、
            超 8 支由 overflow-hidden 截断——完整入口只有底部「查看全部」,滚动条会让它失去意义;
            行高显式 h-9 钉死:否则字号/内边距一变,定高就会切出半截行 */}
          <Card className="animate-in fade-in-0 flex h-[377px] flex-col gap-0 overflow-hidden py-0 duration-200 motion-reduce:animate-none">
            {/* 行动画是 transform:CSS 会把变换后的边界计入滚动容器的溢出区,shadcn Table 自带的
              overflow-x-auto 容器会在动画期间闪现滚动条;此表 table-fixed+截断本就不需要横向滚动,
              直接钉死内层容器为 overflow-hidden(外层 overflow-hidden 挡不住它自己盒内画的滚动条) */}
            <div className="min-h-0 flex-1 overflow-hidden [&_[data-slot='table-container']]:overflow-hidden">
              {/* table-fixed + 40/30/30:名称列留足长名空间(超长截断为省略号,悬浮看全名),
                  金额两列据此整体右移,不再贴着名称 */}
              <Table className="table-fixed">
                <TableHeader className="bg-muted">
                  <TableRow>
                    <TableHead className="w-[40%] text-center">
                      基金名称
                    </TableHead>
                    <TableHead className="w-[30%]">
                      <SortableHeaderButton
                        title="市值"
                        align="center"
                        direction={directionOf('currentValue')}
                        onToggle={() =>
                          setSorting((current) =>
                            toggleSort(current, 'currentValue'),
                          )
                        }
                      />
                    </TableHead>
                    <TableHead className="w-[30%]">
                      <SortableHeaderButton
                        title="持有收益率"
                        align="center"
                        direction={directionOf('profitRate')}
                        onToggle={() =>
                          setSorting((current) =>
                            toggleSort(current, 'profitRate'),
                          )
                        }
                      />
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedPositions.map((position, index) => (
                    // 首次进入按行序级联淡入上浮,最多累计 7 行;排序切换时用 layout 让行滑动到新位置,
                    // transform 不参与行高计算,h-9 钉死的卡片定高不会被动画撑开
                    <motion.tr
                      key={position.positionId}
                      layout={!reduceMotion}
                      initial={reduceMotion ? false : { opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{
                        layout: { duration: 0.2, ease: 'easeOut' },
                        opacity: {
                          duration: 0.25,
                          delay: Math.min(index, 7) * 0.04,
                        },
                        y: {
                          duration: 0.25,
                          delay: Math.min(index, 7) * 0.04,
                          ease: 'easeOut',
                        },
                      }}
                      className="h-9 border-b transition-colors hover:bg-muted/50"
                    >
                      <TableCell className="text-center font-medium">
                        {/* 行高定死 h-9 ⇒ 长名不能换行兜住:截断为省略号,悬浮看全名 */}
                        <span
                          className="block truncate"
                          title={position.fundName}
                        >
                          {position.fundName}
                        </span>
                      </TableCell>
                      <TableCell className="text-center tabular-nums">
                        {formatMoney(position.currentValue)}
                      </TableCell>
                      <TableCell
                        className={`text-center tabular-nums ${profitClass(position.profitRate)}`}
                      >
                        {signedPct(position.profitRate)}
                      </TableCell>
                    </motion.tr>
                  ))}
                </TableBody>
              </Table>
            </div>
            {/* footer 常驻卡片底部(不随数据行走):数据不足 5 支时也沉底 */}
            <div className="flex justify-end border-t bg-muted/50 px-4 py-2.5">
              <Link
                to={paths.app.asset.positions.getHref()}
                className="flex items-center gap-1 text-sm hover:underline"
              >
                查看全部
                <ChevronRightIcon className="size-4" />
              </Link>
            </div>
          </Card>
          <PortfolioSharePieCard positions={positions} hidden={hidden} />
        </div>
      )}
    </div>
  );
}

/**
 * 第二层指标块:标签已带单位故数值不再加 ¥ 前缀;脱敏时不着色(红绿会泄露涨跌);null 表示无数据。
 * navDate 可选:传了就在标签后挂一枚净值日小标签(只「今日/昨日收益」两格传)——这两档在
 * 数据未更新时同样有值,不标出实际净值日就分不清它指的是哪一天;
 * navDateSuffix / navDateClass 供「已更新」态用(后缀文案 + 涨跌着色),不传即原样灰底。
 */
function MetricBlock({
  label,
  value,
  hidden,
  navDate,
  navDateSuffix,
  navDateClass,
}: {
  label: string;
  value: number | null;
  hidden: boolean;
  /** 该档实际净值日(YYYY-MM-DD);无数据传 null/不传 */
  navDate?: string | null;
  /** 日期后追加的短词(如今日档的「已更新」),不传则只显示日期 */
  navDateSuffix?: string;
  /** 附加在该标签上的类(涨跌着色),不传用默认灰底 */
  navDateClass?: string;
}) {
  // 取月日与脱敏开关无关:日期非敏感,且金额变 **** 时更需要它区分是哪天
  const navDateText = navDate ? toChineseDate(navDate) : null;
  const reduceMotion = useReducedMotion();
  const display = useCountUp(value, { enabled: !reduceMotion });
  return (
    // testid 让单测能定位到具体卡片取值(否则只能从 DOM 往上爬,测试库明确禁止)
    <div className="px-6 py-6 text-center" data-testid={`metric-${label}`}>
      <div className="text-muted-foreground flex items-center justify-center gap-1.5 text-base">
        <span>{label}</span>
        {navDateText && (
          <Badge variant="secondary" className={navDateClass}>
            {navDateSuffix ? `${navDateText} ${navDateSuffix}` : navDateText}
          </Badge>
        )}
      </div>
      <div
        className={`text-2xl font-semibold tabular-nums ${
          hidden
            ? ''
            : value == null
              ? 'text-muted-foreground'
              : profitClass(value)
        }`}
      >
        {hidden ? '****' : display == null ? '—' : signedNum(display)}
      </div>
    </div>
  );
}

/** 空态引导:简况页无写操作,建仓入口指回明细页 */
function EmptyGuide() {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed py-16">
      <EmptyStateArt className="h-14 w-24" />
      <span className="text-muted-foreground">
        暂无持仓，去持仓明细建仓后即可在此查看简况
      </span>
      <Button asChild variant="outline" size="sm">
        <Link to={paths.app.asset.positions.getHref()}>
          前往持仓明细
          <ArrowRightIcon />
        </Link>
      </Button>
    </div>
  );
}

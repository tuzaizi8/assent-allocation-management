// src/app/routes/app/snapshots.tsx —— 快照管理页
// 运维入口:按区间补齐(生成)或整体重建,页面只有「单行工具栏 + 表格」两截。
// 表格范式对齐 users.tsx(DataTableShell + useDataTable + 服务端分页 + 列显隐);
// 工具栏对齐 logs.tsx(日期置最左 + 至 + 白底查询),重置取 users 页搜索框右侧的图标按钮形态;
// 区间走「输入态/查询态分离」——编辑日期不发请求,点查询才生效(与日志页同款)。
import {
  columnVisibilityFeature,
  tableFeatures,
  type ColumnDef,
} from '@tanstack/react-table';
import {
  DatabaseIcon,
  Loader2,
  RefreshCwIcon,
  RotateCcwIcon,
  SearchIcon,
  Trash2Icon,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  XAxis,
  YAxis,
} from 'recharts';

import { ChartEmpty } from '@/components/shared/chart-empty';
import { ColumnVisibilityDropdown } from '@/components/shared/column-visibility-dropdown';
import { DataTablePagination } from '@/components/shared/data-table-pagination';
import { DataTableShell } from '@/components/shared/data-table-shell';
import { DateField } from '@/components/shared/date-field';
import { DeleteConfirmDialog } from '@/components/shared/delete-confirm-dialog';
import { DetailDrawer } from '@/components/shared/detail-drawer';
import { Button } from '@/components/ui/button';
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  useDeleteAllSnapshots,
  useGenerateSnapshots,
  useRebuildSnapshots,
  useSnapshotDayDetail,
  useSnapshotList,
  type SnapshotDailyRow,
  type SnapshotRange,
} from '@/features/snapshots/api/get-snapshots';
import { QuarterlyChangeCard } from '@/features/snapshots/components/quarterly-change-card';
import { useDataTable } from '@/hooks/use-data-table';
import { formatMoney, profitClass, signedMoney } from '@/utils/format';

// 明细表只有列显隐诉求(无行选择/无列过滤),按需注册特性
const features = tableFeatures({ columnVisibilityFeature });

// 当日明细条形图:单序列市值。配色用 shadcn 官方蓝(oklch 259.8°≈blue-500)——
// 本站 --chart-1..3 是灰阶且被全站其它图表消费,不能为这一张图改全局变量
const dayChartConfig = {
  marketValue: {
    label: '市值',
    color: 'oklch(0.623 0.214 259.815)',
  },
} satisfies ChartConfig;

// 稳定空数组兜底(v9 要求 data 引用稳定,否则每次渲染都重建行模型)
const EMPTY_ROWS: SnapshotDailyRow[] = [];

const COLUMN_LABELS: Record<string, string> = {
  snapshotDate: '日期',
  fundCount: '基金数',
  totalValue: '市值合计',
  cumulativeInvested: '累计投入',
  profit: '盈亏',
};

export default function SnapshotsRoute() {
  // 区间:输入态(可编辑)与查询态(已提交,驱动请求)分离
  const [startInput, setStartInput] = useState('');
  const [endInput, setEndInput] = useState('');
  const [range, setRange] = useState<SnapshotRange>({});
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [rebuildOpen, setRebuildOpen] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);
  // 行点击抽屉:点哪天看哪天的基金明细(date 驱动按需单查,关抽屉即置空停请求)
  const [viewingDate, setViewingDate] = useState<string | null>(null);

  const { data: pageData, isLoading } = useSnapshotList(page, pageSize, range);
  const generate = useGenerateSnapshots();
  const rebuild = useRebuildSnapshots();
  const clearAll = useDeleteAllSnapshots();
  const { data: dayDetail, isLoading: dayLoading } =
    useSnapshotDayDetail(viewingDate);

  const rows = pageData?.data ?? EMPTY_ROWS;
  const meta = pageData?.meta;

  const columns = useMemo<ColumnDef<typeof features, SnapshotDailyRow>[]>(
    () => [
      {
        accessorKey: 'snapshotDate',
        header: () => <span className="block text-left">日期</span>,
        // 点击对象是日期文字本身(Button link 自带 hover 下划线),对齐持仓明细页基金名称的交互
        cell: ({ row }) => (
          <Button
            variant="link"
            className="text-foreground h-auto w-fit px-0 py-0 text-left font-medium tabular-nums"
            onClick={() => setViewingDate(row.original.snapshotDate)}
          >
            {row.original.snapshotDate}
          </Button>
        ),
        enableHiding: false,
      },
      {
        accessorKey: 'fundCount',
        header: () => <span className="block text-right">基金数</span>,
        cell: ({ row }) => (
          <span className="block text-right tabular-nums">
            {row.original.fundCount}
          </span>
        ),
      },
      {
        accessorKey: 'totalValue',
        header: () => <span className="block text-right">市值合计</span>,
        cell: ({ row }) => (
          <span className="block text-right tabular-nums">
            {formatMoney(row.original.totalValue)}
          </span>
        ),
      },
      {
        accessorKey: 'cumulativeInvested',
        header: () => <span className="block text-right">累计投入</span>,
        // 该日无现金流记录时后端给 null:显示破折号,不塞 0 冒充「投入为零」
        cell: ({ row }) => (
          <span className="block text-right tabular-nums">
            {row.original.cumulativeInvested == null
              ? '—'
              : formatMoney(row.original.cumulativeInvested)}
          </span>
        ),
      },
      {
        id: 'profit',
        header: () => <span className="block text-right">盈亏</span>,
        cell: ({ row }) => {
          const invested = row.original.cumulativeInvested;
          if (invested == null) {
            return <span className="block text-right">—</span>;
          }
          const profit = row.original.totalValue - invested;
          return (
            <span
              className={`block text-right tabular-nums ${profitClass(profit)}`}
            >
              {signedMoney(profit)}
            </span>
          );
        },
      },
    ],
    [],
  );

  const { table } = useDataTable({
    features,
    data: rows,
    columns,
    getRowId: (row) => row.snapshotDate,
  });

  // 提交查询:区间变化后回到第 1 页,避免停留在越界页码
  const handleQuery = () => {
    setRange({
      startDate: startInput || undefined,
      endDate: endInput || undefined,
    });
    setPage(1);
  };

  const handleResetRange = () => {
    setStartInput('');
    setEndInput('');
    setRange({});
    setPage(1);
  };

  return (
    <div className="flex flex-col gap-4">
      {/* ===== 单行工具栏:日期 + 查询/重置(左) | 列显隐 + 生成/重建(右) ===== */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <DateField
            id="snapshot-start-date"
            value={startInput}
            onChange={setStartInput}
            placeholder="起始日期"
          />
          <span className="text-muted-foreground text-sm">至</span>
          <DateField
            id="snapshot-end-date"
            value={endInput}
            onChange={setEndInput}
            placeholder="结束日期"
          />
          <Button variant="default" size="sm" onClick={handleQuery}>
            <SearchIcon />
            查询
          </Button>
          {/* 重置沿用 users 页搜索框右侧的形态:无文字图标按钮(查询已用文字,不再重复刷新图标) */}
          <Button
            variant="ghost"
            size="icon"
            className="text-muted-foreground size-8"
            onClick={handleResetRange}
            aria-label="重置区间"
          >
            <RefreshCwIcon className="size-4" />
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ColumnVisibilityDropdown
            table={table}
            columnLabels={COLUMN_LABELS}
          />
          {/* 语义分层:生成是主操作(黑底),重建是重维护(白底描边),清空是最危险操作(红底) */}
          {/* 生成固定最近 90 天、与日期区间无关(2026-10-12 用户裁决:区间只属于查询);全量场景是重建 */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="default"
                size="sm"
                disabled={generate.isPending}
                onClick={() => generate.mutate()}
              >
                {generate.isPending ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <DatabaseIcon />
                )}
                生成记录
              </Button>
            </TooltipTrigger>
            <TooltipContent className="max-w-64">
              生成最近 90 天的历史持仓记录;恢复全部历史请用「重建记录」
            </TooltipContent>
          </Tooltip>
          {/* 重建非删除:不加红色(红色 + 垃圾桶会让人以为是在删数据),语义靠图标与二次确认表达 */}
          <Button
            variant="outline"
            size="sm"
            disabled={rebuild.isPending || generate.isPending}
            onClick={() => setRebuildOpen(true)}
          >
            {rebuild.isPending ? (
              <Loader2 className="animate-spin" />
            ) : (
              <RotateCcwIcon />
            )}
            重建记录
          </Button>
          {/* 三级清空:只清快照与现金流,不影响持仓与流水,故排在重建之后(右组最末) */}
          <Button
            variant="destructive"
            size="sm"
            disabled={clearAll.isPending || rebuild.isPending}
            onClick={() => setClearOpen(true)}
          >
            {clearAll.isPending ? (
              <Loader2 className="animate-spin" />
            ) : (
              <Trash2Icon />
            )}
            清空记录
          </Button>
        </div>
      </div>

      {/* ===== 明细表:服务端分页(新→旧) ===== */}
      <div className="flex flex-col gap-3">
        <DataTableShell
          table={table}
          columnCount={columns.length}
          isLoading={isLoading}
          emptyText="该区间暂无历史持仓记录，可点击「生成记录」按交易记录补齐"
        />
        <DataTablePagination
          meta={meta}
          page={page}
          pageSize={pageSize}
          isLoading={isLoading}
          leftLabel={meta ? `共 ${meta.totalItems} 天` : undefined}
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
        />
      </div>

      {/* ===== 季度持仓变化卡片:模仿基金季报的持仓变动,分页器下的历史回看 ===== */}
      <QuarterlyChangeCard />

      {/* ===== 当日基金明细抽屉(日期点击;shadcn Bar Chart 横向条,条长即市值) ===== */}
      <DetailDrawer
        open={viewingDate != null}
        onOpenChange={(open) => {
          if (!open) setViewingDate(null);
        }}
        title={viewingDate}
        description={`当日基金明细 · 市值合计 ${formatMoney(dayDetail?.totalValue ?? 0)}`}
        loading={dayLoading && !dayDetail}
        scroll
      >
        {dayDetail && dayDetail.funds.length > 0 && (
          // col-span-2:DetailDrawer 内容容器是 grid-cols-2(为 users/logs 字段网格设计),
          // 单个图表不声明跨列就只占左列,右侧空出——视觉上被切成两半(2026-10-12 实证)
          <div className="col-span-2">
            <ChartContainer
              config={dayChartConfig}
              // 高度随基金数伸缩:每根条约 34px;宽度占满抽屉全宽(max-w-md 会压挤 Y 轴名称)
              className="w-full"
              style={{ height: dayDetail.funds.length * 34 + 40 }}
            >
              <BarChart
                accessibilityLayer
                data={dayDetail.funds}
                layout="vertical"
                margin={{ left: 4, right: 48 }}
              >
                <CartesianGrid horizontal={false} />
                <XAxis type="number" tickLine={false} axisLine={false} hide />
                <YAxis
                  type="category"
                  dataKey="fundName"
                  width={232}
                  tickLine={false}
                  axisLine={false}
                  // 已删基金名称为 null,类别轴显示代码兜底
                  tickFormatter={(value: string) => value || '（基金已删除）'}
                />
                <ChartTooltip
                  content={
                    <ChartTooltipContent
                      className="w-[180px]"
                      labelKey="fundName"
                      formatter={(value) => (
                        <div className="flex w-full items-center justify-between gap-2">
                          <span className="text-muted-foreground">市值</span>
                          <span className="font-mono font-medium tabular-nums">
                            {formatMoney(Number(value))}
                          </span>
                        </div>
                      )}
                    />
                  }
                />
                <Bar
                  dataKey="marketValue"
                  fill="var(--color-marketValue)"
                  radius={4}
                  barSize={18}
                >
                  <LabelList
                    dataKey="ratio"
                    position="right"
                    className="fill-foreground"
                    fontSize={11}
                    formatter={(value) => `${String(value)}%`}
                  />
                </Bar>
              </BarChart>
            </ChartContainer>
          </div>
        )}
        {dayDetail && dayDetail.funds.length === 0 && (
          <div className="col-span-2">
            <ChartEmpty
              height={160}
              text="该日无快照行（可能当日无持仓或快照尚未生成）。"
            />
          </div>
        )}
      </DetailDrawer>

      {/* 重建不是删除:图标与确认按钮都不走删除语义(红色/垃圾桶会误导),但保留二次确认 */}
      <DeleteConfirmDialog
        open={rebuildOpen}
        onOpenChange={setRebuildOpen}
        title="确认重建记录？"
        description="将清空当前全部历史持仓记录与现金流水，再按买卖记录逐日重建到今天。重建期间分析接口可能短暂读到不完整数据。"
        pending={rebuild.isPending}
        confirmText="确认重建"
        destructive={false}
        icon={<RotateCcwIcon />}
        onConfirm={() =>
          rebuild.mutate(undefined, { onSettled: () => setRebuildOpen(false) })
        }
      />

      {/* 三级清空:只清派生数据,持仓与流水不动,可随时重新生成 */}
      <DeleteConfirmDialog
        open={clearOpen}
        onOpenChange={setClearOpen}
        title="确认清空全部记录？"
        description="将清空全部历史持仓记录与现金流。持仓与买卖流水不受影响，可随时点击「生成记录」或「重建记录」重新生成。"
        pending={clearAll.isPending}
        confirmText="确认清空"
        onConfirm={() =>
          clearAll.mutate(undefined, { onSettled: () => setClearOpen(false) })
        }
      />
    </div>
  );
}

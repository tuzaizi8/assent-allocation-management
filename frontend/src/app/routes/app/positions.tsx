// 持仓管理页 —— 设计语言照 funds.tsx(工具栏 + 表格 + components/shared/ 公共件),两处差异:
// ① 无权限守卫:持仓域后端已改为仅登录 + 行级隔离,前端不加 HasPermission
// ② 交易记录是独立菜单页(/app/asset/transactions),本页只管"当前持仓"视角
import {
  columnVisibilityFeature,
  rowSortingFeature,
  tableFeatures,
  type ColumnDef,
  type SortingState,
  type Updater,
} from '@tanstack/react-table';
import { isAxiosError } from 'axios';
import {
  EllipsisVerticalIcon,
  Loader2,
  MinusIcon,
  PlusIcon,
  RefreshCwIcon,
  ShoppingCartIcon,
  Trash2Icon,
  TrendingDownIcon,
  TrendingUpIcon,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';

import { ColumnVisibilityDropdown } from '@/components/shared/column-visibility-dropdown';
import { DataTableColumnHeader } from '@/components/shared/data-table-column-header';
import { DataTablePagination } from '@/components/shared/data-table-pagination';
import { DataTableShell } from '@/components/shared/data-table-shell';
import { DeleteConfirmDialog } from '@/components/shared/delete-confirm-dialog';
import { DetailDrawer, DetailField } from '@/components/shared/detail-drawer';
import { EntityCell } from '@/components/shared/entity-cell';
import { getFundTypeVisual } from '@/components/shared/fund-type-badge';
import { SearchInput } from '@/components/shared/search-input';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { paths } from '@/config/paths';
import { StatusBadge } from '@/features/dict/components/status-badge';
import {
  useDeleteAllPositions,
  usePositionDetail,
  usePositions,
  useRebuildPositions,
  useRedeemPosition,
  type PositionDetail,
  type RedeemInput,
} from '@/features/positions/api/get-positions';
import {
  RedeemForm,
  TradeForm,
} from '@/features/positions/components/position-forms';
import { TransactionHistory } from '@/features/positions/components/position-history';
import { useDataTable } from '@/hooks/use-data-table';
import {
  formatMoney,
  formatNumber,
  formatUnitPrice,
  profitClass,
  signedMoney,
  signedPct,
} from '@/utils/format';

// v9 显式注册表格特性:列显隐 + 排序(持仓操作都是行级单条,不需要行选择)。
// 只注册 rowSortingFeature(排序状态与表头交互),**不**注册 createSortedRowModel:
// 数据是服务端分页的一页、排序键是后端算出来的派生指标,客户端排序会排错。
const features = tableFeatures({
  columnVisibilityFeature,
  rowSortingFeature,
});

/** 排序表头 → 后端参数(只放开三个派生指标,与后端 POSITION_SORT_KEYS 一一对应) */
const POSITION_SORT_PARAMS: Record<
  string,
  'current_value' | 'profit' | 'profit_rate'
> = {
  currentValue: 'current_value',
  profit: 'profit',
  profitRate: 'profit_rate',
};

/** 默认排序:当前市值降序(列表页默认视图,与后端缺省一致) */
const DEFAULT_SORTING: SortingState = [{ id: 'currentValue', desc: true }];

// 稳定空数组兜底(v9 要求 data 引用稳定,避免每次渲染新建 [] 导致行模型失效)
const EMPTY_POSITIONS: PositionDetail[] = [];

const POSITION_COLUMN_LABELS: Record<string, string> = {
  totalShares: '持有份额',
  avgCostPrice: '平均成本',
  currentValue: '当前市值',
  profit: '持有收益',
  profitRate: '持有收益率',
  status: '状态',
};

// 右对齐数字在默认 p-2 下几乎贴容器右缘,统一补右侧呼吸边距,表头与数据同距对齐
const AMOUNT_CELL = 'text-right tabular-nums pr-4';

/** 数值列表头右对齐,与单元格的 tabular-nums 右对齐保持同一阅读轴 */
const rightHeader = (label: string) => {
  const Header = () => <div className="text-right pr-4">{label}</div>;
  return Header;
};

export default function PositionsRoute() {
  const navigate = useNavigate();
  const [createOpen, setCreateOpen] = useState(false);
  const [purchaseOpen, setPurchaseOpen] = useState(false);
  // 赎回分两步:先填表单,再经确认弹窗复核(份额与日期不可逆,避免误点即成交)
  const [redeemTarget, setRedeemTarget] = useState<PositionDetail | null>(null);
  const [pendingRedeem, setPendingRedeem] = useState<RedeemInput | null>(null);
  // 赎回响应丢失(超时/断网)时置位:弹窗进入「结果未知」态,禁止同一笔重复提交
  const [redeemUnknown, setRedeemUnknown] = useState(false);
  const [viewingId, setViewingId] = useState<number | null>(null);
  const [clearOpen, setClearOpen] = useState(false);
  const [rebuildOpen, setRebuildOpen] = useState(false);

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  // 搜索(输入态/查询态分离——照 users 页模式,避免逐字发请求;空=全量)
  const [searchInput, setSearchInput] = useState('');
  const [searchQuery, setSearchQuery] = useState<string | undefined>(undefined);

  // 排序(服务端):表头点击 → sorting 变化 → 回第一页重新取数
  const [sorting, setSorting] = useState<SortingState>(DEFAULT_SORTING);
  const handleSortingChange = (updater: Updater<SortingState>) => {
    setSorting(updater);
    setPage(1);
  };
  const sortBy = POSITION_SORT_PARAMS[sorting[0]?.id ?? ''] ?? 'current_value';
  const sortOrder: 'asc' | 'desc' = sorting[0]?.desc === false ? 'asc' : 'desc';

  const { data, isLoading } = usePositions(
    page,
    pageSize,
    searchQuery,
    sortBy,
    sortOrder,
  );
  const { data: detail, isLoading: detailLoading } =
    usePositionDetail(viewingId);
  const redeem = useRedeemPosition();
  const clearAll = useDeleteAllPositions();
  const rebuildPositions = useRebuildPositions();

  // 搜索提交(服务端模糊,回到第一页)
  const handleSearch = () => {
    setSearchQuery(searchInput.trim() || undefined);
    setPage(1);
  };
  // 重置:清搜索词回全量(输入框清空 + 查询态清空)
  const handleReset = () => {
    setSearchInput('');
    setSearchQuery(undefined);
    setPage(1);
  };

  const rows = data?.data ?? EMPTY_POSITIONS;
  const meta = data?.meta;
  // 抽屉先用列表行数据即时渲染,明细到位后再以明细为准(列表行与明细同构)
  const viewingRow =
    viewingId == null
      ? null
      : (rows.find((row) => row.positionId === viewingId) ?? null);
  const shownDetail = detail ?? viewingRow;

  const positionColumns = useMemo<ColumnDef<typeof features, PositionDetail>[]>(
    () => [
      // 主列:名称点击跳转基金详情页面(照字典管理范式);持仓明细由操作列「明细」按钮触发
      {
        accessorKey: 'fundName',
        header: '基金名称',
        cell: ({ row }) => {
          // 方块首字表达基金类型(债/指/混/股/货…),比名称首字更有信息量
          const visual = getFundTypeVisual(row.original.fundType);
          return (
            <EntityCell
              title={row.original.fundName}
              subtitle={row.original.fundCode}
              monoSubtitle
              initial={visual?.char ?? row.original.fundName?.slice(0, 1)}
              leadingClassName={visual?.blockClass}
              onTitleClick={() =>
                navigate(
                  paths.app.asset.fundInfo.getHref(row.original.fundCode),
                )
              }
            />
          );
        },
        enableHiding: false,
      },
      {
        accessorKey: 'totalShares',
        header: rightHeader('持有份额'),
        cell: ({ row }) => (
          <div className={AMOUNT_CELL}>
            {formatNumber(row.original.totalShares)}
          </div>
        ),
      },
      {
        accessorKey: 'avgCostPrice',
        header: rightHeader('平均成本'),
        cell: ({ row }) => (
          <div className={`${AMOUNT_CELL} text-muted-foreground`}>
            {`¥${formatUnitPrice(row.original.avgCostPrice)}`}
          </div>
        ),
      },
      {
        accessorKey: 'currentValue',
        header: ({ column }) => (
          <DataTableColumnHeader
            column={column}
            title="当前市值"
            align="right"
          />
        ),
        cell: ({ row }) => (
          <div className={`${AMOUNT_CELL} font-semibold`}>
            {formatMoney(row.original.currentValue)}
          </div>
        ),
      },
      {
        accessorKey: 'profit',
        header: ({ column }) => (
          <DataTableColumnHeader
            column={column}
            title="持有收益"
            align="right"
          />
        ),
        cell: ({ row }) => (
          <div className={`${AMOUNT_CELL} ${profitClass(row.original.profit)}`}>
            {signedMoney(row.original.profit)}
          </div>
        ),
      },
      {
        accessorKey: 'profitRate',
        header: ({ column }) => (
          <DataTableColumnHeader
            column={column}
            title="持有收益率"
            align="right"
          />
        ),
        cell: ({ row }) => {
          const rate = row.original.profitRate;
          // 涨跌配趋势图标:与 fintech 的 P&L 单元格同一读法,扫列时先看到方向
          const TrendIcon =
            rate > 0 ? TrendingUpIcon : rate < 0 ? TrendingDownIcon : MinusIcon;
          return (
            <div
              className={`${AMOUNT_CELL} flex items-center justify-end gap-1 ${profitClass(rate)}`}
            >
              <TrendIcon className="size-3.5" />
              {signedPct(rate)}
            </div>
          );
        },
      },
      {
        accessorKey: 'status',
        header: '状态',
        cell: ({ row }) => (
          <StatusBadge
            dictType="sys_position_status"
            value={row.original.status}
            failureValue="2"
          />
        ),
      },
      {
        id: 'actions',
        cell: ({ row }) => (
          // 行操作收进 Ellipsis 下拉(与用户管理同款):表格更清爽,赎回仍用红色语义
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="data-open:bg-muted text-muted-foreground size-8"
              >
                <EllipsisVerticalIcon />
                <span className="sr-only">打开菜单</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-32">
              <DropdownMenuItem
                onSelect={() => setViewingId(row.original.positionId)}
              >
                明细
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                variant="destructive"
                onSelect={() => setRedeemTarget(row.original)}
              >
                赎回
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ),
        enableHiding: false,
      },
    ],
    [navigate],
  );

  const positionTable = useDataTable({
    features,
    data: rows,
    columns: positionColumns,
    getRowId: (row) => row.positionId.toString(),
    state: { sorting },
    onSortingChange: handleSortingChange,
  });

  const handleConfirmRedeem = () => {
    if (!pendingRedeem) return;
    redeem.mutate(pendingRedeem, {
      onSuccess: () => {
        setPendingRedeem(null);
        setRedeemTarget(null);
        // 全额赎回后端会软删持仓,抽屉里的明细已失效,一并收起
        setViewingId(null);
      },
      onError: (error) => {
        // 仅网络层失败(无 response)是结果未知:服务端可能已成功落库;
        // 业务错误(HTTP 200 success=false / 4xx/5xx)是确定失败,可正常重试
        if (isAxiosError(error) && !error.response) setRedeemUnknown(true);
      },
    });
  };

  return (
    <div className="flex flex-col gap-4">
      {/* 工具栏(照 users 页):搜索在左,列显隐/建仓/买入在右 */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {/* 搜索(服务端模糊:基金名称/代码,回车提交) */}
          <SearchInput
            value={searchInput}
            onValueChange={setSearchInput}
            onSubmit={handleSearch}
            onReset={handleReset}
            placeholder="搜索基金名称/代码"
            className="w-44 pl-8"
          />
        </div>
        <div className="flex items-center gap-2">
          <ColumnVisibilityDropdown
            table={positionTable.table}
            columnLabels={POSITION_COLUMN_LABELS}
          />
          <Button
            variant="default"
            size="sm"
            onClick={() => setCreateOpen(true)}
          >
            <PlusIcon />
            <span className="hidden lg:inline">建仓</span>
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPurchaseOpen(true)}
          >
            <ShoppingCartIcon />
            <span className="hidden lg:inline">买入</span>
          </Button>
          {/* 重建持仓:头表全删按流水重放(position_id 重挂),流水不动可反复执行,修复/清空后恢复两用 */}
          <Button
            variant="outline"
            size="sm"
            disabled={rebuildPositions.isPending}
            onClick={() => setRebuildOpen(true)}
          >
            {rebuildPositions.isPending ? (
              <Loader2 className="animate-spin" />
            ) : (
              <RefreshCwIcon />
            )}
            <span className="hidden lg:inline">重建持仓</span>
          </Button>
          {/* 清空持仓是二级删除:连带清快照,买卖流水保留,故放在右组最末(越靠右越危险) */}
          <Button
            variant="destructive"
            size="sm"
            disabled={clearAll.isPending}
            onClick={() => setClearOpen(true)}
          >
            {clearAll.isPending ? (
              <Loader2 className="animate-spin" />
            ) : (
              <Trash2Icon />
            )}
            <span className="hidden lg:inline">清空持仓</span>
          </Button>
        </div>
      </div>

      <DataTableShell
        table={positionTable.table}
        columnCount={positionColumns.length}
        isLoading={isLoading}
        emptyText="暂无持仓，点击建仓开始记录"
      />
      <DataTablePagination
        meta={meta}
        page={page}
        pageSize={pageSize}
        isLoading={isLoading}
        onPageChange={setPage}
        onPageSizeChange={(size) => {
          setPageSize(size);
          setPage(1);
        }}
        leftLabel={<>共 {meta?.totalItems ?? 0} 条持仓</>}
        idPrefix="position-rows-per-page"
      />

      {/* ===== 持仓明细抽屉(按需单查;列表行已同构,故先用行数据即时渲染) ===== */}
      <DetailDrawer
        open={viewingId != null}
        onOpenChange={(open) => {
          if (!open) setViewingId(null);
        }}
        title={shownDetail?.fundName}
        description="持仓明细"
        loading={detailLoading && !viewingRow}
        scroll
      >
        {shownDetail && (
          <>
            <DetailField label="基金代码" value={shownDetail.fundCode} />
            <DetailField label="基金类型" value={shownDetail.fundType || '-'} />
            <DetailField
              label="持有份额"
              value={shownDetail.totalShares.toFixed(4)}
            />
            <DetailField
              label="平均成本"
              value={shownDetail.avgCostPrice.toFixed(4)}
            />
            <DetailField
              label="当前市值"
              value={shownDetail.currentValue.toFixed(2)}
            />
            <DetailField
              label="持仓成本"
              value={shownDetail.totalCost.toFixed(2)}
            />
            <div className="flex flex-col gap-1">
              <span className="text-muted-foreground">持有收益</span>
              <span className={profitClass(shownDetail.profit)}>
                {shownDetail.profit.toFixed(2)}
              </span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-muted-foreground">持有收益率</span>
              <span className={profitClass(shownDetail.profitRate)}>
                {shownDetail.profitRate.toFixed(2)}%
              </span>
            </div>
            {/* 已实现 + 累计:这只基金「买入→清仓→再买入」多轮下来一共赚亏多少 */}
            <div className="flex flex-col gap-1">
              <span className="text-muted-foreground">已实现收益</span>
              <span className={profitClass(shownDetail.realizedProfit)}>
                {shownDetail.realizedProfit.toFixed(2)}
              </span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-muted-foreground">累计盈亏</span>
              <span className={profitClass(shownDetail.totalProfit)}>
                {shownDetail.totalProfit.toFixed(2)}
              </span>
            </div>
            <DetailField
              label="状态"
              value={
                <StatusBadge
                  dictType="sys_position_status"
                  value={shownDetail.status}
                  failureValue="2"
                />
              }
            />
            <TransactionHistory
              purchases={shownDetail.purchaseRecords}
              redemptions={shownDetail.redemptionRecords}
            />
          </>
        )}
      </DetailDrawer>

      {/* ===== 赎回确认(复核份额与日期;全额赎回后端自动清仓)。
           赎回是交易动作而非删除,不用 DeleteConfirmDialog(垃圾桶/红色删除按钮会误导) ===== */}
      <Dialog
        open={pendingRedeem != null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingRedeem(null);
            setRedeemUnknown(false);
          }
        }}
      >
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>赎回持仓</DialogTitle>
            <DialogDescription>
              {`确认赎回「${redeemTarget?.fundName ?? pendingRedeem?.fundCode ?? ''}」${pendingRedeem?.shares ?? ''} 份吗？赎回日期 ${pendingRedeem?.redemptionDate ?? ''}。全额赎回后持仓自动清仓，交易记录仍可查询。`}
            </DialogDescription>
          </DialogHeader>
          {redeemUnknown && (
            <Alert variant="destructive">
              <AlertTitle>本次操作结果未知（可能已成功）</AlertTitle>
              <AlertDescription>
                请求响应丢失，服务端可能已在处理或已完成赎回。请刷新页面核实持仓与交易记录，核实前请勿重复提交。
              </AlertDescription>
            </Alert>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              disabled={redeem.isPending}
              onClick={() => setPendingRedeem(null)}
            >
              {redeemUnknown ? '关闭' : '取消'}
            </Button>
            <Button
              disabled={redeem.isPending || redeemUnknown}
              onClick={handleConfirmRedeem}
            >
              {redeem.isPending && <Loader2 className="animate-spin" />}
              确认赎回
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ===== 建仓 / 买入(Radix 关闭即卸载,重开天然无表单残留) ===== */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>建仓</DialogTitle>
            <DialogDescription>
              首次买入某只基金；份额由后端按买入日净值自动换算
            </DialogDescription>
          </DialogHeader>
          <TradeForm mode="create" onDone={setCreateOpen} />
        </DialogContent>
      </Dialog>

      <Dialog open={purchaseOpen} onOpenChange={setPurchaseOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>分批买入</DialogTitle>
            <DialogDescription>
              追加买入已有持仓；尚无持仓时后端自动建仓
            </DialogDescription>
          </DialogHeader>
          <TradeForm mode="purchase" onDone={setPurchaseOpen} />
        </DialogContent>
      </Dialog>

      <Dialog
        open={redeemTarget != null}
        onOpenChange={(open) => {
          if (!open) setRedeemTarget(null);
        }}
      >
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>赎回持仓</DialogTitle>
            <DialogDescription>
              按份额赎回；赎回净值由后端按赎回日自动获取
            </DialogDescription>
          </DialogHeader>
          {redeemTarget && (
            <RedeemForm
              position={redeemTarget}
              onSubmit={setPendingRedeem}
              onDone={() => setRedeemTarget(null)}
            />
          )}
        </DialogContent>
      </Dialog>

      {/* ===== 重建持仓:修复性重操作非删除,走中性变体(先例见快照页「重建快照」) ===== */}
      <DeleteConfirmDialog
        open={rebuildOpen}
        onOpenChange={setRebuildOpen}
        title="确认从交易记录重建持仓？"
        description="将清空当前持仓头表，并按日期顺序重放全部交易记录重建（记录的份额与金额不变，仅重新绑定持仓）。适用于清空持仓后的恢复或头表数据存疑时的修复，可反复执行。"
        pending={rebuildPositions.isPending}
        confirmText="确认重建"
        destructive={false}
        icon={<RefreshCwIcon />}
        onConfirm={() =>
          rebuildPositions.mutate(undefined, {
            onSettled: () => setRebuildOpen(false),
          })
        }
      />

      {/* ===== 二级清空:物理删持仓 + 清快照,买卖流水保留(历史收益仍可追溯) ===== */}
      <DeleteConfirmDialog
        open={clearOpen}
        onOpenChange={setClearOpen}
        title="确认清空全部持仓？"
        description="将物理删除全部持仓，并连带清空历史持仓记录与现金流。买卖流水保留，历史收益与累计投入仍可查询；之后可用「重建持仓」从流水恢复持仓。"
        pending={clearAll.isPending}
        confirmText="确认清空"
        onConfirm={() =>
          clearAll.mutate(undefined, { onSettled: () => setClearOpen(false) })
        }
      />
    </div>
  );
}

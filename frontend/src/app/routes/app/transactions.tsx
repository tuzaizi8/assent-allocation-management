// 交易记录页 —— 独立菜单(与持仓页剥离):买入/赎回两个 Tab 切换查看
// 只读视角:流水含已清仓持仓的历史交易,后端已按日期倒序排好,前端不再排序
// 类型筛选走服务端(txType 直用后端直出的中文 '买入'/'赎回',非字典非编码),切 Tab 回第一页
import {
  columnVisibilityFeature,
  tableFeatures,
  type ColumnDef,
} from '@tanstack/react-table';
import { ClockIcon, DownloadIcon, Loader2, Trash2Icon } from 'lucide-react';
import { useMemo, useState } from 'react';

import {
  Tabs,
  TabsList,
  TabsTrigger,
} from '@/components/animate-ui/components/radix/tabs';
import { ColumnVisibilityDropdown } from '@/components/shared/column-visibility-dropdown';
import { DataTablePagination } from '@/components/shared/data-table-pagination';
import { DataTableShell } from '@/components/shared/data-table-shell';
import { DeleteConfirmDialog } from '@/components/shared/delete-confirm-dialog';
import { EntityCell } from '@/components/shared/entity-cell';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  useDeleteAllTransactions,
  useDeleteTransaction,
  useExportTransactions,
  useTransactions,
  type PositionTransaction,
} from '@/features/positions/api/get-positions';
import { useDataTable } from '@/hooks/use-data-table';
import { formatMoney, formatNumber, formatUnitPrice } from '@/utils/format';

// v9 显式注册表格特性:只用列显隐(流水纯只读,不需要行选择)
const features = tableFeatures({
  columnVisibilityFeature,
});

// 稳定空数组兜底(v9 要求 data 引用稳定,避免每次渲染新建 [] 导致行模型失效)
const EMPTY_TRANSACTIONS: PositionTransaction[] = [];

const TRANSACTION_COLUMN_LABELS: Record<string, string> = {
  date: '日期',
  type: '类型',
  shares: '份额',
  price: '单价',
  amount: '金额',
  remark: '备注',
};

// 右对齐数字在默认 p-2 下几乎贴容器右缘,统一补右侧呼吸边距,表头与数据同距对齐
const AMOUNT_CELL = 'text-right tabular-nums pr-4';

/** 待确认占位徽章:所选日期净值未公布,份额/单价/金额依赖该净值故不可知 */
function PendingBadge() {
  return (
    <div className={AMOUNT_CELL}>
      <Badge className="border-amber-500 text-amber-600" variant="outline">
        <ClockIcon className="size-3" />
        待确认
      </Badge>
    </div>
  );
}

/** 数值列表头右对齐,与单元格的 tabular-nums 右对齐保持同一阅读轴 */
const rightHeader = (label: string) => {
  const Header = () => <div className="text-right pr-4">{label}</div>;
  return Header;
};

export default function TransactionsRoute() {
  const [txType, setTxType] = useState('买入');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [clearOpen, setClearOpen] = useState(false);
  /** 行级删除目标:null 时弹窗关闭;删除是不可恢复的硬删除,须逐行二次确认 */
  const [deleteTarget, setDeleteTarget] = useState<PositionTransaction | null>(
    null,
  );

  const { data, isLoading } = useTransactions(page, pageSize, txType);
  const clearAll = useDeleteAllTransactions();
  const deleteTx = useDeleteTransaction();
  const exportTx = useExportTransactions();

  const rows = data?.data ?? EMPTY_TRANSACTIONS;
  const meta = data?.meta;

  const columns = useMemo<ColumnDef<typeof features, PositionTransaction>[]>(
    () => [
      { accessorKey: 'date', header: '日期' },
      {
        accessorKey: 'fundName',
        header: '基金名称',
        cell: ({ row }) => {
          // 交易行没有 fundType,方块改为表达买卖方向:买=红、赎=绿,与导入预览的语义一致
          const isRedeem = row.original.type === '赎回';
          const isBuy = row.original.type === '买入';
          return (
            <EntityCell
              title={row.original.fundName}
              subtitle={row.original.fundCode}
              monoSubtitle
              initial={
                isRedeem ? '赎' : isBuy ? '买' : row.original.type.slice(0, 1)
              }
              leadingClassName={
                isRedeem
                  ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400'
                  : isBuy
                    ? 'bg-destructive/10 text-destructive dark:bg-destructive/20'
                    : undefined
              }
            />
          );
        },
        enableHiding: false,
      },
      {
        accessorKey: 'shares',
        header: rightHeader('份额'),
        cell: ({ row }) =>
          row.original.status === '0' ? (
            <PendingBadge />
          ) : (
            <div className={AMOUNT_CELL}>
              {formatNumber(row.original.shares)}
            </div>
          ),
      },
      {
        accessorKey: 'price',
        header: rightHeader('单价'),
        cell: ({ row }) =>
          row.original.status === '0' ? (
            <PendingBadge />
          ) : (
            <div className={`${AMOUNT_CELL} text-muted-foreground`}>
              {formatUnitPrice(row.original.price)}
            </div>
          ),
      },
      {
        accessorKey: 'amount',
        header: rightHeader('金额'),
        // 买入的金额在录入时就确定了(用户输入),待确认也照常显示;
        // 赎回的到账金额 = 份额 × 未发布净值,确实未定 → 待确认徽章
        cell: ({ row }) => (
          <div className={`${AMOUNT_CELL} font-semibold`}>
            {row.original.status === '0' && row.original.type === '赎回' ? (
              <PendingBadge />
            ) : (
              formatMoney(row.original.amount)
            )}
          </div>
        ),
      },
      {
        accessorKey: 'remark',
        header: '备注',
        cell: ({ row }) => row.original.remark ?? '-',
      },
      {
        // 行级硬删除:只有一个操作,不占表头文字;红色垃圾桶一眼识别,点击后仍走二次确认
        id: 'actions',
        enableHiding: false,
        cell: ({ row }) => (
          <Button
            variant="ghost"
            size="icon"
            className="text-destructive hover:bg-destructive/10 hover:text-destructive size-7"
            aria-label="删除记录"
            disabled={deleteTx.isPending}
            onClick={() => setDeleteTarget(row.original)}
          >
            <Trash2Icon />
          </Button>
        ),
      },
    ],
    [deleteTx.isPending],
  );

  const table = useDataTable({
    features,
    data: rows,
    columns,
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {/* Tab 即筛选:买入/赎回两档直传服务端,无「全部」档 */}
        <Tabs
          value={txType}
          onValueChange={(value) => {
            setTxType(value);
            setPage(1);
          }}
        >
          <TabsList>
            <TabsTrigger value="买入">买入</TabsTrigger>
            <TabsTrigger value="赎回">赎回</TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="flex flex-wrap items-center gap-2">
          <ColumnVisibilityDropdown
            table={table.table}
            columnLabels={TRANSACTION_COLUMN_LABELS}
          />
          {/* 导出与导入模板同列形:导出的文件可直接在交易导入页回导 */}
          <Button
            variant="outline"
            size="sm"
            disabled={exportTx.isPending}
            onClick={() => exportTx.mutate()}
          >
            {exportTx.isPending ? (
              <Loader2 className="animate-spin" />
            ) : (
              <DownloadIcon />
            )}
            导出
          </Button>
          {/* 一级清空:流水是份额与快照的唯一来源,删了整条链都失去依据,故置于右组最末 */}
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
            清空流水
          </Button>
        </div>
      </div>

      <DataTableShell
        table={table.table}
        columnCount={columns.length}
        isLoading={isLoading}
        emptyText={`暂无${txType}记录`}
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
        leftLabel={<>共 {meta?.totalItems ?? 0} 条记录</>}
        idPrefix="transaction-rows-per-page"
      />

      {/* ===== 行级删除:硬删除单条流水,后端连带快照全量重建,不可恢复 ===== */}
      <DeleteConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
        title={`确认删除这条${deleteTarget?.type ?? ''}记录？`}
        description={`将物理删除 ${deleteTarget?.date ?? ''} ${
          deleteTarget?.fundName ?? ''
        } 的这条记录，并触发历史持仓记录全量重算；该持仓如已无任何记录会被一并清理。此操作不可恢复。`}
        pending={deleteTx.isPending}
        confirmText="确认删除"
        onConfirm={() => {
          if (!deleteTarget) return;
          deleteTx.mutate(
            { source: deleteTarget.source, recordId: deleteTarget.recordId },
            { onSettled: () => setDeleteTarget(null) },
          );
        }}
      />

      {/* ===== 一级清空:物理删流水 + 持仓 + 快照,不可恢复(最高危险级) ===== */}
      <DeleteConfirmDialog
        open={clearOpen}
        onOpenChange={setClearOpen}
        title="确认清空全部交易记录？"
        description="将物理删除全部买入与赎回记录，并连带清空持仓、历史持仓记录与现金流。交易流水是份额与收益的唯一来源，此操作不可恢复。"
        pending={clearAll.isPending}
        confirmText="确认清空"
        onConfirm={() =>
          clearAll.mutate(undefined, { onSettled: () => setClearOpen(false) })
        }
      />
    </div>
  );
}

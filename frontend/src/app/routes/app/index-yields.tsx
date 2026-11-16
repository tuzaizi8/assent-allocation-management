// src/app/routes/app/index-yields.tsx —— 指数收益率管理页
// 设计语言照 funds.tsx(dashboard-01 表格范式 + components/shared/ 公共件),三处刻意差异:
// ① 无新增/编辑——行情只能从外部接口拿,自行新增得不到历史数据,新增位置由「同步」取代
// ② 无权限守卫——指数行情是公共数据(与 /fund/chart/* 一致),页面与端点都不做权限控制
// ③ 不分页——集合固定为内置指数(BENCHMARK_INDICES),省略分页条
// 同步是强制回源(绕过缓存新鲜度);删除是物理清缓存(可恢复,重新同步/访问图表即重拉)
import {
  columnVisibilityFeature,
  rowSelectionFeature,
  tableFeatures,
  type ColumnDef,
} from '@tanstack/react-table';
import {
  CircleAlertIcon,
  EllipsisVerticalIcon,
  Loader2,
  RefreshCwIcon,
} from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';

import { BatchDeleteButton } from '@/components/shared/batch-delete-button';
import { ColumnVisibilityDropdown } from '@/components/shared/column-visibility-dropdown';
import { DataTableShell } from '@/components/shared/data-table-shell';
import { DeleteConfirmDialog } from '@/components/shared/delete-confirm-dialog';
import { DetailDrawer, DetailField } from '@/components/shared/detail-drawer';
import { EntityCell } from '@/components/shared/entity-cell';
import { SearchInput } from '@/components/shared/search-input';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useDict } from '@/features/dict/api/get-dict';
import { StatusBadge } from '@/features/dict/components/status-badge';
import {
  useDeleteIndices,
  useIndexDetail,
  useIndices,
  useSyncAllIndices,
  useSyncIndex,
  type IndexItem,
} from '@/features/indices/api/get-indices';
import { useDataTable } from '@/hooks/use-data-table';
import { profitClass, signedPct, formatNumber } from '@/utils/format';

// v9 显式注册表格特性:行选择 / 列显隐(状态筛选走服务端,无需列过滤特性)
const features = tableFeatures({
  rowSelectionFeature,
  columnVisibilityFeature,
});

// 稳定空数组兜底(v9 要求 data 引用稳定,避免每次渲染新建 [] 导致行模型失效)
const EMPTY_INDICES: IndexItem[] = [];

// 列显隐下拉的中文名(列 id → 标签;select/指数名称/操作 三列 enableHiding=false 不出现)
const COLUMN_LABELS: Record<string, string> = {
  syncStatus: '同步状态',
  latestClose: '最新点位',
  dailyYield: '日涨跌幅',
  latestDate: '最新数据日期',
  recordCount: '记录数',
  updateTime: '更新时间',
};

// 涨跌幅配色与文案:A 股惯例红涨绿跌,零/空值不着色;实现走 utils/format 统一口径
const yieldClass = (value: number | null | undefined) =>
  value == null ? '' : profitClass(value);

const yieldText = (value: number | null | undefined) =>
  value == null ? '-' : signedPct(value);

export default function IndexYieldsRoute() {
  // 搜索(输入态/查询态分离)+ 同步状态筛选(均走服务端,集合固定 5 条)
  const [searchInput, setSearchInput] = useState('');
  const [keyword, setKeyword] = useState<string | undefined>(undefined);
  const [syncStatusFilter, setSyncStatusFilter] = useState('all');
  const { data, isLoading } = useIndices(
    keyword,
    syncStatusFilter === 'all' ? undefined : syncStatusFilter,
  );
  const syncAll = useSyncAllIndices();
  const syncIndex = useSyncIndex();
  const deleteIndices = useDeleteIndices();
  // 同步状态筛选选项(字典驱动,logs 页同构;dictValue '1'/'0'/'2' 直穿过滤参数)
  const syncStatusDict = useDict('sys_index_sync_status');

  const rows = data ?? EMPTY_INDICES;

  // 详情抽屉(按需单查:区间收益率 + 最近 10 个交易日)
  const [viewing, setViewing] = useState<IndexItem | null>(null);
  const { data: detail, isLoading: detailLoading } = useIndexDetail(
    viewing?.indexCode ?? null,
  );

  // 同步 pending 按行区分:点一行只让那一行转圈
  const [syncingCode, setSyncingCode] = useState<string | null>(null);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<
    { mode: 'single'; item: IndexItem } | { mode: 'batch' } | null
  >(null);

  const handleView = useCallback((item: IndexItem) => setViewing(item), []);

  const handleRowSync = useCallback(
    (item: IndexItem) => {
      setSyncingCode(item.indexCode);
      syncIndex.mutate(item.indexCode, {
        onSettled: () => setSyncingCode(null),
      });
    },
    [syncIndex],
  );

  const handleRowDelete = useCallback((item: IndexItem) => {
    setDeleteTarget({ mode: 'single', item });
    setDeleteConfirmOpen(true);
  }, []);

  // 列定义(useMemo 保持引用稳定;处理函数已 useCallback,setState 本身稳定)
  const columns = useMemo<ColumnDef<typeof features, IndexItem>[]>(
    () => [
      // ① 复选框列(全选/半选/行选)
      {
        id: 'select',
        header: ({ table }) => (
          <div className="flex items-center justify-center">
            <Checkbox
              checked={
                table.getIsAllPageRowsSelected()
                  ? true
                  : table.getIsSomePageRowsSelected()
                    ? 'indeterminate'
                    : false
              }
              onCheckedChange={(value) =>
                table.toggleAllPageRowsSelected(!!value)
              }
              aria-label="全选"
            />
          </div>
        ),
        cell: ({ row }) => (
          <div className="flex items-center justify-center">
            <Checkbox
              checked={row.getIsSelected()}
              onCheckedChange={(value) => row.toggleSelected(!!value)}
              aria-label="选择该行"
            />
          </div>
        ),
        enableHiding: false,
      },
      // ② 主列:指数名称 + 代码两行,点击打开详情抽屉
      {
        accessorKey: 'indexName',
        header: '指数名称',
        cell: ({ row }) => (
          <EntityCell
            title={row.original.indexName}
            subtitle={row.original.indexCode}
            monoSubtitle
            // 指数管理页不需要首字方块:指数名称首字没有语义,去掉后行更清爽
            hideLeading
            onTitleClick={() => handleView(row.original)}
          />
        ),
        enableHiding: false,
      },
      // ③ 同步状态(字典驱动 StatusBadge 三态:'1'已同步=绿勾/'0'未同步=灰禁用/'2'已过期=琥珀警示)
      {
        accessorKey: 'syncStatus',
        header: '同步状态',
        cell: ({ row }) => (
          <StatusBadge
            dictType="sys_index_sync_status"
            value={row.original.syncStatus}
            successValue="1"
            failureValue="0"
            icons={{
              unknown: <CircleAlertIcon className="text-amber-500" />,
            }}
          />
        ),
      },
      {
        accessorKey: 'latestClose',
        header: '最新点位',
        cell: ({ row }) =>
          row.original.latestClose == null
            ? '-'
            : formatNumber(row.original.latestClose),
      },
      {
        accessorKey: 'dailyYield',
        header: '日涨跌幅',
        cell: ({ row }) => (
          <span className={yieldClass(row.original.dailyYield)}>
            {yieldText(row.original.dailyYield)}
          </span>
        ),
      },
      {
        accessorKey: 'latestDate',
        header: '最新数据日期',
        cell: ({ row }) => row.original.latestDate ?? '-',
      },
      { accessorKey: 'recordCount', header: '记录数' },
      { accessorKey: 'updateTime', header: '更新时间' },
      // ④ 操作列(actions:详情 → 同步 → 分隔线 → 删除;无编辑——行情不可手工维护)
      {
        id: 'actions',
        cell: ({ row }) => (
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
              <DropdownMenuItem onSelect={() => handleView(row.original)}>
                详情
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={syncIndex.isPending}
                onSelect={() => handleRowSync(row.original)}
              >
                {syncingCode === row.original.indexCode &&
                  syncIndex.isPending && <Loader2 className="animate-spin" />}
                同步
              </DropdownMenuItem>
              {/* 危险操作与普通项之间用横线隔离 */}
              <DropdownMenuSeparator />
              <DropdownMenuItem
                variant="destructive"
                onSelect={() => handleRowDelete(row.original)}
              >
                删除
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ),
        enableHiding: false,
      },
    ],
    [
      handleView,
      handleRowSync,
      handleRowDelete,
      syncingCode,
      syncIndex.isPending,
    ],
  );

  // 表格装配(行选择;筛选条件变化时清空选择)
  const { table, setRowSelection } = useDataTable({
    features,
    data: rows,
    columns,
    getRowId: (row) => row.indexCode,
    enableRowSelection: true,
    resetSelectionOn: [keyword, syncStatusFilter],
  });

  const selectedCount = table.getFilteredSelectedRowModel().rows.length;
  const selectedCodes = table
    .getSelectedRowModel()
    .rows.map((row) => row.original.indexCode);

  // 筛选走服务端(集合虽小,语义与基金页保持一致)
  const handleStatusFilter = (value: string) => setSyncStatusFilter(value);

  const handleSearch = () => {
    setKeyword(searchInput.trim() || undefined);
  };
  const handleReset = () => {
    setSearchInput('');
    setKeyword(undefined);
  };

  // 删除确认(单删/批删共用一个受控弹窗;物理删除,后端连带清 Redis)
  const handleConfirmDelete = () => {
    if (!deleteTarget) return;
    const codes =
      deleteTarget.mode === 'single'
        ? [deleteTarget.item.indexCode]
        : selectedCodes;
    deleteIndices.mutate(codes, {
      onSuccess: () => {
        setDeleteConfirmOpen(false);
        setDeleteTarget(null);
        setRowSelection({});
      },
    });
  };

  return (
    <div className="flex flex-col gap-4">
      {/* ===== 工具栏(左:搜索 + 同步状态筛选 | 右:批量删除 + 列显隐 + 同步全部) ===== */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <SearchInput
            value={searchInput}
            onValueChange={setSearchInput}
            onSubmit={handleSearch}
            onReset={handleReset}
            placeholder="搜索指数名称或代码"
            className="w-44 pl-8"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* 批量删除(物理清缓存) */}
          {selectedCount > 0 && (
            <BatchDeleteButton
              selectedCount={selectedCount}
              pending={deleteIndices.isPending}
              onClick={() => {
                setDeleteTarget({ mode: 'batch' });
                setDeleteConfirmOpen(true);
              }}
            />
          )}
          {/* 列显隐下拉(公共组件:COLUMN_LABELS 参数化) */}
          <ColumnVisibilityDropdown
            table={table}
            columnLabels={COLUMN_LABELS}
          />
          {/* 同步状态(字典驱动选项,字典值直穿过滤——logs 页同款位置与写法) */}
          <Select value={syncStatusFilter} onValueChange={handleStatusFilter}>
            <SelectTrigger size="sm" className="w-26">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="all">全部状态</SelectItem>
                {syncStatusDict.map((d) => (
                  <SelectItem key={d.dictValue} value={d.dictValue}>
                    {d.dictLabel}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          {/* 主操作:同步全部(强制回源,取代基金页的新增按钮) */}
          <Button
            variant="outline"
            size="sm"
            disabled={syncAll.isPending}
            onClick={() => syncAll.mutate()}
          >
            {syncAll.isPending ? (
              <Loader2 className="animate-spin" />
            ) : (
              <RefreshCwIcon />
            )}
            同步全部
          </Button>
        </div>
      </div>

      {/* ===== 表格(骨架组件:圆角边框容器 + bg-muted 表头 + 状态行) ===== */}
      <DataTableShell
        table={table}
        columnCount={columns.length}
        isLoading={isLoading}
        selectable
      />

      {/* ===== 不渲染分页条:集合固定为内置指数,无服务端分页 ===== */}

      {/* ===== 详情抽屉(元数据 + 区间收益率 + 最近 10 个交易日;按需单查) ===== */}
      <DetailDrawer
        open={!!viewing}
        onOpenChange={(open) => {
          if (!open) setViewing(null);
        }}
        title={viewing?.indexName}
        description="指数行情缓存详情"
        loading={detailLoading}
      >
        <DetailField label="指数代码" value={detail?.indexCode} />
        <DetailField
          label="同步状态"
          value={
            detail ? (
              <StatusBadge
                dictType="sys_index_sync_status"
                value={detail.syncStatus}
                successValue="1"
                failureValue="0"
                icons={{
                  unknown: <CircleAlertIcon className="text-amber-500" />,
                }}
              />
            ) : undefined
          }
        />
        <DetailField label="最新点位" value={detail?.latestClose} />
        <DetailField
          label="日涨跌幅"
          value={
            detail?.dailyYield == null
              ? undefined
              : yieldText(detail.dailyYield)
          }
        />
        <DetailField label="最新数据日期" value={detail?.latestDate} />
        <DetailField label="记录数" value={detail?.recordCount} />
        <DetailField label="数据来源" value={detail?.source} />
        <DetailField label="更新时间" value={detail?.updateTime} />
        {/* 区间收益率:与图表接口同口径(区间首日收盘为基准),红涨绿跌 */}
        <div className="col-span-2 flex flex-col gap-1">
          <span className="text-muted-foreground">区间收益率</span>
          <div className="flex flex-wrap gap-2">
            {(detail?.yields ?? []).map((item) => (
              <div
                key={item.period}
                className="bg-muted flex min-w-24 flex-col items-center rounded-md p-2"
              >
                <span className="text-muted-foreground text-xs">
                  {item.period}
                </span>
                <span
                  className={`text-sm font-medium ${yieldClass(item.yieldPct)}`}
                >
                  {item.yieldPct == null ? '-' : yieldText(item.yieldPct)}
                </span>
              </div>
            ))}
          </div>
        </div>
        {/* 最近 10 个交易日:等宽块,形态与 logs 页 JSON 展示一致 */}
        <div className="col-span-2 flex flex-col gap-1">
          <span className="text-muted-foreground">最近 10 个交易日</span>
          <pre className="bg-muted max-h-40 overflow-auto rounded-md p-2 font-mono text-xs whitespace-pre-wrap">
            {(detail?.recent ?? []).length
              ? (detail?.recent ?? [])
                  .map(
                    (record) =>
                      `${record.navDate}  收盘 ${record.close}  涨跌幅 ${yieldText(record.dailyYield)}`,
                  )
                  .join('\n')
              : '-'}
          </pre>
        </div>
      </DetailDrawer>

      {/* ===== 删除确认(单删/批删共用;物理删除,后端连带清 Redis) ===== */}
      <DeleteConfirmDialog
        open={deleteConfirmOpen}
        onOpenChange={(open) => {
          setDeleteConfirmOpen(open);
          if (!open) setDeleteTarget(null);
        }}
        title={
          deleteTarget?.mode === 'batch' ? '批量清除指数缓存' : '清除指数缓存'
        }
        description={
          deleteTarget?.mode === 'batch'
            ? `确认清除所选 ${selectedCodes.length} 个指数的历史缓存吗？此操作为物理删除；下次同步或访问图表时会自动重新拉取。`
            : `确认清除指数「${deleteTarget?.mode === 'single' ? deleteTarget.item.indexName : ''}」的历史缓存吗？此操作为物理删除；下次同步或访问图表时会自动重新拉取。`
        }
        pending={deleteIndices.isPending}
        onConfirm={handleConfirmDelete}
      />
    </div>
  );
}

// src/app/routes/app/fund-navs.tsx —— 基金净值管理页
// 设计语言照 funds.tsx 表格范式,表格骨架/页脚/列显隐/搜索走 components/shared/
// 状态下拉照 logs 页(工具栏右侧 Select + useDict 字典驱动,字典值直穿过滤)
// 同步策略:按需——行内"同步净值"按钮(单只调七接口),搜索的基金代码无结果时空态提供同步入口,
// 绝不全量跑 fund 表(全市场两万多只,绝大多数永远不会被查看)
// 列表行来自 fund_nav_history(已同步过的基金),搜索未同步的代码 → 空态入口负责转化
import {
  columnVisibilityFeature,
  tableFeatures,
  type ColumnDef,
} from '@tanstack/react-table';
import {
  DatabaseIcon,
  LandmarkIcon,
  Loader2,
  PlusIcon,
  RefreshCwIcon,
  ShieldXIcon,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { ColumnVisibilityDropdown } from '@/components/shared/column-visibility-dropdown';
import { DataTablePagination } from '@/components/shared/data-table-pagination';
import { DataTableShell } from '@/components/shared/data-table-shell';
import { EntityCell } from '@/components/shared/entity-cell';
import { SearchInput } from '@/components/shared/search-input';
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
  useFundNavs,
  useSyncFundNav,
  type FundNavRow,
} from '@/features/funds/api/get-fund-navs';
import { type Fund } from '@/features/funds/api/get-funds';
import { FundCombobox } from '@/features/funds/components/fund-combobox';
import { useDataTable } from '@/hooks/use-data-table';
import { useHasPermission } from '@/lib/authorization';
import { formatDate } from '@/utils/format';

// v9 显式注册表格特性:仅列显隐(无行选择/删除,状态过滤走服务端)
const features = tableFeatures({
  columnVisibilityFeature,
});

// 稳定空数组兜底(v9 要求 data 引用稳定,避免每次渲染新建 [] 导致行模型失效)
const EMPTY_NAVS: FundNavRow[] = [];

// 列显隐下拉的中文名(代码/操作两列 enableHiding=false 不出现)
const COLUMN_LABELS: Record<string, string> = {
  fundName: '基金名称',
  recordCount: '记录数',
  latestDate: '最新净值日',
  updateTime: '更新时间',
};

export default function FundNavsRoute() {
  // ===== 服务端分页与筛选条件(契约对齐后端 FundNavQueryModel) =====
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  // 搜索(输入态/查询态分离——避免逐字发请求)
  const [searchInput, setSearchInput] = useState('');
  const [keyword, setKeyword] = useState<string | undefined>(undefined);
  const [syncStatusFilter, setSyncStatusFilter] = useState('all');
  const { data, isLoading } = useFundNavs(
    page,
    pageSize,
    keyword,
    syncStatusFilter === 'all' ? undefined : syncStatusFilter,
  );
  const syncNav = useSyncFundNav();
  // 页面级权限闸门(redirectTo 误回跳时整页降级为无权限空态,见下方早返回)
  const canList = useHasPermission('fund:nav:list');
  // 行内同步按钮的权限级守卫
  const canSync = useHasPermission('fund:nav:sync');
  // 添加净值弹窗(搜索 fund 表选基金 → 确定即调七接口同步)
  const [addDialogOpen, setAddDialogOpen] = useState(false);

  const rows = data?.data ?? EMPTY_NAVS;
  const meta = data?.meta;

  // 状态下拉文案字典驱动(与指数页同一字典:已同步/未同步/已过期)
  const syncStatusDict = useDict('sys_index_sync_status');
  // ===== 表格状态(列显隐由 useDataTable 托管) =====

  // 列定义(useMemo 保持引用稳定)
  const columns = useMemo<ColumnDef<typeof features, FundNavRow>[]>(
    () => [
      // 主列:名称 + 代码两行(名称缺失时以代码兜底),代码不再单独占列
      {
        accessorKey: 'fundName',
        header: '基金名称',
        cell: ({ row }) => (
          <EntityCell
            title={row.original.fundName || row.original.fundCode}
            subtitle={row.original.fundCode}
            monoSubtitle
            // 净值行没有 fundType,类型首字无从谈起;用基金图标占位,不再拿名称首字凑数
            leading={<LandmarkIcon className="size-3.5" />}
          />
        ),
        enableHiding: false,
      },
      {
        accessorKey: 'recordCount',
        header: '记录数',
        cell: ({ row }) => row.original.recordCount ?? '-',
      },
      // ② 最新净值日(冗余列直出 yyyy-MM-dd,无需格式化)
      {
        accessorKey: 'latestDate',
        header: '最新净值日',
        cell: ({ row }) => row.original.latestDate ?? '-',
      },
      // ③ 同步状态(三态:'1'已同步绿勾 / '0'未同步灰禁用 / '2'已过期琥珀)
      {
        accessorKey: 'syncStatusVirtual',
        header: '同步状态',
        cell: ({ row }) => (
          <StatusBadge
            dictType="sys_index_sync_status"
            value={computeSyncStatus(row.original)}
            successValue="1"
          />
        ),
      },
      {
        accessorKey: 'updateTime',
        header: '更新时间',
        cell: ({ row }) =>
          row.original.updateTime ? formatDate(row.original.updateTime) : '-',
      },
      // ④ 操作列(按需同步:单只调七接口,不做批量——全市场两万多只,绝大多数不会被查看)
      {
        id: 'actions',
        cell: ({ row }) =>
          canSync ? (
            <Button
              variant="ghost"
              size="sm"
              className="h-8 px-2 text-xs"
              disabled={syncNav.isPending}
              onClick={() => syncNav.mutate(row.original.fundCode)}
            >
              {syncNav.isPending &&
              syncNav.variables === row.original.fundCode ? (
                <Loader2 className="animate-spin" />
              ) : (
                <RefreshCwIcon />
              )}
              同步净值
            </Button>
          ) : null,
        enableHiding: false,
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [canSync, syncNav.isPending, syncNav.variables],
  );

  // 表格装配(仅列显隐,无行选择)
  const { table } = useDataTable({
    features,
    data: rows,
    columns,
  });

  // 搜索提交(关键词由 useFundNavs 按形态分流为代码或名称;回到第一页)
  const handleSearch = () => {
    setKeyword(searchInput.trim() || undefined);
    setPage(1);
  };
  // 重置:清搜索词回全量
  const handleReset = () => {
    setSearchInput('');
    setKeyword(undefined);
    setPage(1);
  };
  const handleStatusFilter = (value: string) => {
    setSyncStatusFilter(value);
    setPage(1);
  };

  // 空态同步入口:按代码搜索无结果(且不在加载中)→ 该基金尚未同步,提供同步入口
  // ("看哪只同步哪只"的转化闭环;非纯数字的名称搜索无结果只是真的没有匹配)
  const trimmedKeyword = keyword?.trim() ?? '';
  const showSyncEmpty =
    !isLoading && rows.length === 0 && /^\d+$/.test(trimmedKeyword);

  // 无 fund:nav:list 权限(换账号后 redirectTo 误回跳本页):渲染无权限空态
  if (!canList) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-2 text-center">
        <ShieldXIcon className="text-muted-foreground size-10" />
        <p className="text-lg font-medium">无访问权限</p>
        <p className="text-muted-foreground text-sm">
          当前账号没有基金净值的访问权限,请联系管理员分配
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* ===== 工具栏(搜索 | 状态下拉[logs 页同款位置,字典驱动]) ===== */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <SearchInput
            value={searchInput}
            onValueChange={setSearchInput}
            onSubmit={handleSearch}
            onReset={handleReset}
            placeholder="搜索基金代码或名称"
            className="h-8 w-44 pl-8"
          />
        </div>
        <div className="flex items-center gap-2">
          {/* 添加净值:主动入口,按代码/名称模糊搜 fund 表后同步(空态入口只覆盖纯数字代码场景) */}
          {canSync && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setAddDialogOpen(true)}
            >
              <PlusIcon />
              添加净值
            </Button>
          )}
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
          {/* 列显隐下拉(公共组件:COLUMN_LABELS 参数化) */}
          <ColumnVisibilityDropdown
            table={table}
            columnLabels={COLUMN_LABELS}
          />
        </div>
      </div>

      {/* ===== 表格 / 空态同步入口 ===== */}
      {showSyncEmpty ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-lg border py-16 text-center">
          <DatabaseIcon className="text-muted-foreground size-10" />
          <p className="text-lg font-medium">
            基金「{trimmedKeyword}」尚未同步净值
          </p>
          <p className="text-muted-foreground text-sm">
            同步后将积累该基金的完整净值序列,作为收益率曲线与净值走势的数据源
          </p>
          {canSync && (
            <Button
              variant="outline"
              size="sm"
              disabled={syncNav.isPending}
              onClick={() => syncNav.mutate(trimmedKeyword)}
            >
              {syncNav.isPending ? (
                <Loader2 className="animate-spin" />
              ) : (
                <RefreshCwIcon />
              )}
              同步该基金
            </Button>
          )}
        </div>
      ) : (
        <>
          {/* 表格骨架(自动处理加载/空态;无行选择不传 selectable) */}
          <DataTableShell
            table={table}
            columnCount={columns.length}
            isLoading={isLoading}
          />

          {/* 页脚(公共分页条组件:服务端分页状态直绑;leftLabel 左侧占位使控件靠右,与 users/logs/roles 统一) */}
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
            leftLabel={meta ? <>共 {meta.totalItems} 条净值</> : undefined}
            idPrefix="fund-navs-rows-per-page"
          />
        </>
      )}

      {/* 添加净值弹窗(组件契约见 AddNavDialog) */}
      <AddNavDialog open={addDialogOpen} onOpenChange={setAddDialogOpen} />
    </div>
  );
}

/**
 * 三态同步状态判定(与后端 SQL 谓词/is_nav_stale 同口径,双窗口失效):
 * 已有今天的净值 → '1';否则看上次回源时间是否在当前窗口起点(每天 00:00/22:00 两个失效点,
 * 22 点后窗口起点为当天 22:00)之内,在内 → '1',早于起点 → '2' 已过期。
 * ('0' 未同步的基金不在净值表,列表行不会出现)
 */
function computeSyncStatus(row: FundNavRow): '1' | '2' {
  if (!row.latestDate) {
    return '2';
  }
  const now = new Date();
  const latest = new Date(`${row.latestDate}T00:00:00`).getTime();
  if (latest >= new Date(now.toDateString()).getTime()) {
    return '1';
  }
  if (!row.updateTime) {
    return '2';
  }
  const windowStart = new Date(now.toDateString());
  if (now.getHours() >= 22) {
    windowStart.setHours(22, 0, 0, 0);
  }
  return new Date(row.updateTime).getTime() >= windowStart.getTime()
    ? '1'
    : '2';
}

/**
 * 添加净值弹窗:输入代码或名称模糊搜 fund 表(候选走 FundCombobox),
 * 选中一只后"确定"即调七接口同步入库并关弹窗。已同步的基金再同步 = upsert 覆盖,无害。
 */
function AddNavDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [selected, setSelected] = useState<Fund | null>(null);
  const syncNav = useSyncFundNav();

  // 每次打开重置上次的选中项:弹窗常驻挂载,不清会带着上次的基金进来(组件内部的关键词/选中
  // 由 FundCombobox 自己的 active effect 清)
  useEffect(() => {
    if (open) {
      setSelected(null);
    }
  }, [open]);

  const handleConfirm = () => {
    if (!selected) {
      return;
    }
    // per-mutation onSuccess:hook 内的全局 onSuccess(toast + 失效列表)之后关弹窗
    syncNav.mutate(selected.code, { onSuccess: () => onOpenChange(false) });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>添加基金净值</DialogTitle>
          <DialogDescription>
            搜索基金并同步其净值序列,已同步的基金将覆盖更新
          </DialogDescription>
        </DialogHeader>
        <FundCombobox
          active={open}
          onChange={setSelected}
          placeholder="输入基金代码或名称模糊搜索"
          listClassName="max-h-64"
        />
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button
            onClick={handleConfirm}
            disabled={!selected || syncNav.isPending}
          >
            {syncNav.isPending ? (
              <Loader2 className="animate-spin" />
            ) : (
              <DatabaseIcon />
            )}
            确定同步
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

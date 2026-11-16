// src/app/routes/app/fund-info-management.tsx —— 基金信息管理页
// 管理 fund_info 缓存表(档案数据 DB 命中后不再回源,本页是唯一的人工刷新入口)。
// 范式完全对齐 funds.tsx:工具栏(搜索 | 列显隐 + 同步 + 新增,HasPermission 包裹) /
// 表格(代码/名称 link 开详情抽屉 + 操作列下拉) / 页脚(服务端分页) / 无权限空态。
// 差异:无行选择与批量删除(本域无批量端点)、无状态 Tabs 与类型筛选(fund_info 无状态字段)。
import { zodResolver } from '@hookform/resolvers/zod';
import {
  columnVisibilityFeature,
  tableFeatures,
  type ColumnDef,
} from '@tanstack/react-table';
import {
  EllipsisVerticalIcon,
  Loader2,
  PlusIcon,
  RefreshCwIcon,
  ShieldXIcon,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { ColumnVisibilityDropdown } from '@/components/shared/column-visibility-dropdown';
import { DataTablePagination } from '@/components/shared/data-table-pagination';
import { DataTableShell } from '@/components/shared/data-table-shell';
import { DeleteConfirmDialog } from '@/components/shared/delete-confirm-dialog';
import { EntityCell } from '@/components/shared/entity-cell';
import {
  FundTypeBadge,
  getFundTypeVisual,
} from '@/components/shared/fund-type-badge';
import { SearchInput } from '@/components/shared/search-input';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
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
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import {
  useAddFundInfo,
  useDeleteFundInfo,
  useFundInfoList,
  useSyncAllFundInfos,
  useSyncFundInfo,
  type FundInfoRow,
} from '@/features/fund-info-admin/api/get-fund-info-admin';
import { FundInfoDrawer } from '@/features/funds/components/fund-info-drawer';
import { useDataTable } from '@/hooks/use-data-table';
import { HasPermission, useHasPermission } from '@/lib/authorization';
import { formatDate } from '@/utils/format';

// v9 显式注册表格特性:列显隐(无行选择——本域无批量删除端点)
const features = tableFeatures({ columnVisibilityFeature });

// 稳定空数组兜底(v9 要求 data 引用稳定)
const EMPTY_ROWS: FundInfoRow[] = [];

// 列显隐下拉的中文名(代码/操作列 enableHiding=false 不出现)
const COLUMN_LABELS: Record<string, string> = {
  fundName: '基金名称',
  fundType: '基金类型',
  updateTime: '更新时间',
};

// 新增表单校验:仅需基金代码(档案由同花顺回源抓取)
const addFundInfoSchema = z.object({
  fundCode: z.string().min(1, '请输入基金代码').max(20, '基金代码过长'),
});

type AddFundInfoValues = z.infer<typeof addFundInfoSchema>;

export default function FundInfoManagementRoute() {
  // ===== 服务端分页与搜索(契约对齐后端 FundInfoPageQueryModel) =====
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  // 搜索(输入态/查询态分离,对齐 funds 页模式)
  const [searchInput, setSearchInput] = useState('');
  const [keyword, setKeyword] = useState<string | undefined>(undefined);

  const { data, isLoading } = useFundInfoList(page, pageSize, keyword ?? '');
  const syncAll = useSyncAllFundInfos();
  const syncOne = useSyncFundInfo();
  const deleteFundInfo = useDeleteFundInfo();
  // 页面级权限闸门(误回跳时整页降级为无权限空态)
  const canList = useHasPermission('fund:info:list');
  // 行内同步按钮的权限级守卫
  const canSync = useHasPermission('fund:info:sync');
  // 操作列删除项的权限级守卫
  const canRemove = useHasPermission('fund:info:remove');

  const rows = data?.data ?? EMPTY_ROWS;
  const meta = data?.meta;

  // 基金详情抽屉(同花顺档案,复用基金管理页同款):null = 关闭
  const [infoFundCode, setInfoFundCode] = useState<string | null>(null);
  // 新增弹窗与删除确认
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<FundInfoRow | null>(null);

  // 列定义(引用组件状态,useMemo 保持引用稳定)
  const columns = useMemo<ColumnDef<typeof features, FundInfoRow>[]>(
    () => [
      // ① 主列:名称 + 代码两行,点击打开基金详情档案抽屉
      {
        accessorKey: 'fundName',
        header: '基金名称',
        cell: ({ row }) => {
          const visual = getFundTypeVisual(row.original.fundType);
          const fallback = row.original.fundName ?? row.original.fundCode;
          return (
            <EntityCell
              title={fallback}
              subtitle={row.original.fundCode}
              monoSubtitle
              initial={visual?.char ?? fallback?.slice(0, 1)}
              leadingClassName={visual?.blockClass}
              onTitleClick={() => setInfoFundCode(row.original.fundCode)}
            />
          );
        },
        enableHiding: false,
      },
      {
        accessorKey: 'fundType',
        header: '基金类型',
        cell: ({ row }) => <FundTypeBadge type={row.original.fundType} />,
      },
      // ③ 更新时间列(判断档案新旧的主要依据)
      {
        accessorKey: 'updateTime',
        header: '更新时间',
        cell: ({ row }) =>
          row.original.updateTime ? formatDate(row.original.updateTime) : '-',
      },
      // ④ 操作列(EllipsisVertical 下拉:详情 → 同步 → 分隔线 → 删除)
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
              <DropdownMenuItem
                onSelect={() => setInfoFundCode(row.original.fundCode)}
              >
                详情
              </DropdownMenuItem>
              {canSync && (
                <DropdownMenuItem
                  disabled={syncOne.isPending || syncAll.isPending}
                  onSelect={() => syncOne.mutate(row.original.fundCode)}
                >
                  同步
                </DropdownMenuItem>
              )}
              {canRemove && (
                <>
                  {/* 危险操作与普通项之间用横线隔离 */}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    variant="destructive"
                    onSelect={() => {
                      setDeleteTarget(row.original);
                      setDeleteConfirmOpen(true);
                    }}
                  >
                    删除
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        ),
        enableHiding: false,
      },
    ],
    [canRemove, canSync, syncOne, syncAll.isPending],
  );

  // 表格装配(无行选择;列显隐由 useDataTable 托管)
  const { table } = useDataTable({
    features,
    data: rows,
    columns,
    getRowId: (row) => row.fundInfoId.toString(),
  });

  // 搜索提交(回到第一页)
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

  // 无 fund:info:list 权限:渲染无权限空态而非发注定 403 的请求
  if (!canList) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-2 text-center">
        <ShieldXIcon className="text-muted-foreground size-10" />
        <p className="text-lg font-medium">无访问权限</p>
        <p className="text-muted-foreground text-sm">
          当前账号没有基金信息管理的访问权限,请联系管理员分配
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* ===== 工具栏(搜索 | 列显隐 + 同步 + 新增) ===== */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {/* 搜索(仅代码模糊匹配) */}
          <SearchInput
            value={searchInput}
            onValueChange={setSearchInput}
            onSubmit={handleSearch}
            onReset={handleReset}
            placeholder="搜索基金代码"
            className="h-8 w-44 pl-8"
          />
        </div>
        <div className="flex items-center gap-2">
          {/* 列显隐下拉(公共组件:COLUMN_LABELS 参数化) */}
          <ColumnVisibilityDropdown
            table={table}
            columnLabels={COLUMN_LABELS}
          />
          {/* 全量同步(限流 5 次/小时,逐只回源耗时长;独立 pending) */}
          <HasPermission perm="fund:info:sync">
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
              <span className="hidden lg:inline">同步基金信息</span>
            </Button>
          </HasPermission>
          {/* 新增(权限级守卫:无 fund:info:add 时按钮不存在于 DOM) */}
          <HasPermission perm="fund:info:add">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setDialogOpen(true)}
            >
              <PlusIcon />
              <span className="hidden lg:inline">新增基金信息</span>
            </Button>
          </HasPermission>
        </div>
      </div>

      {/* ===== 表格(骨架组件:圆角边框容器 + bg-muted 表头 + 状态行) ===== */}
      <DataTableShell
        table={table}
        columnCount={columns.length}
        isLoading={isLoading}
      />

      {/* ===== 页脚(公共分页条组件:服务端分页状态直绑) ===== */}
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
      />

      {/* ===== 基金详情抽屉(同花顺档案,代码/名称列与下拉「详情」共用) ===== */}
      <FundInfoDrawer
        fundCode={infoFundCode}
        onOpenChange={(open) => {
          if (!open) setInfoFundCode(null);
        }}
      />

      {/* ===== 删除确认(物理删缓存行,详情接口会重新回源,可随时恢复) ===== */}
      <DeleteConfirmDialog
        open={deleteConfirmOpen}
        onOpenChange={(open) => {
          setDeleteConfirmOpen(open);
          if (!open) setDeleteTarget(null);
        }}
        title="删除基金信息"
        description={`确认删除基金「${deleteTarget?.fundCode ?? ''}」的详细信息缓存吗？删除后访问详情会重新回源同花顺，可随时恢复。`}
        pending={deleteFundInfo.isPending}
        onConfirm={() => {
          if (!deleteTarget) return;
          deleteFundInfo.mutate(deleteTarget.fundCode, {
            onSuccess: () => {
              setDeleteConfirmOpen(false);
              setDeleteTarget(null);
            },
          });
        }}
      />

      {/* ===== 新增基金信息弹窗(仅需基金代码,档案由同花顺回源) ===== */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>新增基金信息</DialogTitle>
          </DialogHeader>
          <AddFundInfoForm onDone={setDialogOpen} />
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ===== 新增基金信息表单(官方 FormField 范式,与基金管理新增弹窗一致) =====
function AddFundInfoForm({ onDone }: { onDone: (open: boolean) => void }) {
  const addFundInfo = useAddFundInfo();
  const form = useForm<AddFundInfoValues>({
    resolver: zodResolver(addFundInfoSchema),
    defaultValues: { fundCode: '' },
  });

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit((values) => {
          addFundInfo.mutate(values.fundCode.trim(), {
            onSuccess: () => onDone(false),
          });
        })}
        className="space-y-4"
      >
        <FormField
          control={form.control}
          name="fundCode"
          render={({ field }) => (
            <FormItem>
              <FormLabel>基金代码</FormLabel>
              <FormControl>
                <Input {...field} placeholder="如 000001" />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <Button
          type="submit"
          className="w-full"
          disabled={addFundInfo.isPending}
        >
          {addFundInfo.isPending ? <Loader2 className="animate-spin" /> : null}
          确认新增
        </Button>
      </form>
    </Form>
  );
}

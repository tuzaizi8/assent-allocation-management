// src/app/routes/app/funds.tsx —— 基金管理页
// 设计语言照 users.tsx:工具栏(状态 Tabs + 搜索 + 类型筛选 + 批量删除 + 列显隐 + 同步 + 新增)
// / 表格(主列 link 开详情抽屉 + 操作列下拉) / 页脚(服务端分页)
// (表格骨架/页脚/列显隐/loading 与空态行走 components/shared/ 公共组件,
//  表格状态编排走 hooks/use-data-table,页内零重复实现)
// 与 users 页的一处差异:状态与类型筛选都在服务端有精确匹配参数,故走服务端筛选
// (切档即回第一页),而非 users 页那样只过滤当前页
import { zodResolver } from '@hookform/resolvers/zod';
import {
  columnVisibilityFeature,
  rowSelectionFeature,
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

import { BatchDeleteButton } from '@/components/shared/batch-delete-button';
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
import { StatusFilterTabs } from '@/components/shared/status-filter-tabs';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
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
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useDict } from '@/features/dict/api/get-dict';
import { DictSelect } from '@/features/dict/components/dict-select';
import { StatusBadge } from '@/features/dict/components/status-badge';
import {
  addFundSchema,
  editFundSchema,
  useAddFund,
  useDeleteFund,
  useEditFund,
  useFundTypes,
  useFunds,
  useSyncFunds,
  type Fund,
} from '@/features/funds/api/get-funds';
import { FundInfoDrawer } from '@/features/funds/components/fund-info-drawer';
import { useDataTable } from '@/hooks/use-data-table';
import { HasPermission, useHasPermission } from '@/lib/authorization';
import { formatDate } from '@/utils/format';

// v9 显式注册表格特性:行选择 / 列显隐
// (不注册列过滤——状态与类型筛选都走服务端精确匹配,前端不再做列过滤)
const features = tableFeatures({
  rowSelectionFeature,
  columnVisibilityFeature,
});

// 稳定空数组兜底(v9 要求 data 引用稳定,避免每次渲染新建 [] 导致行模型失效)
const EMPTY_FUNDS: Fund[] = [];

// 列显隐下拉的中文名(列 id → 标签;select/代码/操作 三列 enableHiding=false 不出现)
const COLUMN_LABELS: Record<string, string> = {
  name: '基金名称',
  fundType: '基金类型',
  status: '状态',
  createTime: '创建时间',
};

export default function FundsRoute() {
  // ===== 服务端分页与筛选条件(契约对齐后端 FundPageQueryModel) =====
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  // 搜索(输入态/查询态分离——对齐 users 页模式,避免逐字发请求)
  const [searchInput, setSearchInput] = useState('');
  const [keyword, setKeyword] = useState<string | undefined>(undefined);
  const [fundTypeFilter, setFundTypeFilter] = useState<string | undefined>(
    undefined,
  );
  const [statusFilter, setStatusFilter] = useState('all'); // Tabs: all / '0' / '1'
  const { data, isLoading } = useFunds(
    page,
    pageSize,
    keyword,
    fundTypeFilter,
    statusFilter === 'all' ? undefined : statusFilter,
  );
  const deleteFund = useDeleteFund();
  const syncFunds = useSyncFunds();
  // 页面级权限闸门(redirectTo 误回跳时整页降级为无权限空态,见下方早返回)
  const canList = useHasPermission('fund:fund:list');
  // 操作列编辑项的权限级守卫(ADMIN 的 *:*:* 通配放行)
  const canEdit = useHasPermission('fund:fund:edit');
  // 操作列删除项 / 批量删除按钮的权限级守卫
  const canRemove = useHasPermission('fund:fund:remove');

  const rows = data?.data ?? EMPTY_FUNDS;
  const meta = data?.meta;

  // 状态 Tabs 文案字典驱动(sys_normal_disable——运营改字典这里即时变)
  const statusDict = useDict('sys_normal_disable');
  // 类型选项由后端按库内实际存在的值聚合(集合随同步增长,不写死常量)
  const { data: fundTypes } = useFundTypes();
  // ===== 表格状态(列显隐/行选择由 useDataTable 托管) =====
  // 基金详情抽屉(同花顺档案):null = 关闭,非 null = 展示该 code 的详情
  const [infoFundCode, setInfoFundCode] = useState<string | null>(null);
  // 新增/编辑共用弹窗:editingFund=null 表示新增,非 null 表示编辑(行数据回显,无需拉详情)
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingFund, setEditingFund] = useState<Fund | null>(null);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<
    { mode: 'single'; fund: Fund } | { mode: 'batch' } | null
  >(null);

  // 列定义(引用组件状态,useMemo 保持引用稳定;setState 函数本身稳定无需入 deps)
  const columns = useMemo<ColumnDef<typeof features, Fund>[]>(
    () => [
      // ① 复选框列(select 列:全选/半选/行选)
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
      // ② 主列:名称 + 代码两行,点击打开基金详情档案抽屉
      {
        accessorKey: 'name',
        header: '基金名称',
        cell: ({ row }) => {
          const visual = getFundTypeVisual(row.original.fundType);
          return (
            <EntityCell
              title={row.original.name}
              subtitle={row.original.code}
              monoSubtitle
              initial={visual?.char ?? row.original.name?.slice(0, 1)}
              leadingClassName={visual?.blockClass}
              onTitleClick={() => setInfoFundCode(row.original.code)}
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
      // ③ 状态列(Status 视觉:outline Badge + 前置图标;文案走字典)
      {
        accessorKey: 'status',
        header: '状态',
        cell: ({ row }) => (
          <StatusBadge
            dictType="sys_normal_disable"
            value={row.original.status}
          />
        ),
      },
      // ④ 创建时间列
      {
        accessorKey: 'createTime',
        header: '创建时间',
        cell: ({ row }) =>
          row.original.createTime ? formatDate(row.original.createTime) : '-',
      },
      // ⑤ 操作列(actions:EllipsisVertical 下拉菜单)
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
                onSelect={() => setInfoFundCode(row.original.code)}
              >
                详情
              </DropdownMenuItem>
              {canEdit && (
                <DropdownMenuItem
                  onSelect={() => {
                    setEditingFund(row.original);
                    setDialogOpen(true);
                  }}
                >
                  编辑
                </DropdownMenuItem>
              )}
              {canRemove && (
                <>
                  {/* 危险操作与普通项之间用横线隔离 */}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    variant="destructive"
                    onSelect={() => {
                      setDeleteTarget({ mode: 'single', fund: row.original });
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
    [canEdit, canRemove],
  );

  // 表格装配(行选择 + 翻页/换每页条数清空选择由 useDataTable 编排)
  const { table, setRowSelection } = useDataTable({
    features,
    data: rows,
    columns,
    getRowId: (row) => row.fundId.toString(),
    enableRowSelection: true,
    resetSelectionOn: [page, pageSize],
  });

  const selectedCount = table.getFilteredSelectedRowModel().rows.length;
  const selectedIds = table
    .getSelectedRowModel()
    .rows.map((row) => row.original.fundId);

  // 状态/类型筛选走服务端(后端有精确匹配参数),切档即回第一页
  const handleStatusFilter = (value: string) => {
    setStatusFilter(value);
    setPage(1);
  };
  const handleFundTypeFilter = (value: string) => {
    setFundTypeFilter(value === 'all' ? undefined : value);
    setPage(1);
  };

  // 删除确认(单删/批删共用一个受控弹窗;后端为逻辑删除,被持仓引用时 601 拒删)
  const handleConfirmDelete = () => {
    if (!deleteTarget) return;
    const ids =
      deleteTarget.mode === 'single' ? [deleteTarget.fund.fundId] : selectedIds;
    deleteFund.mutate(ids, {
      onSuccess: () => {
        setDeleteConfirmOpen(false);
        setDeleteTarget(null);
        setRowSelection({});
      },
    });
  };

  // 搜索提交(关键词由 useFunds 按形态分流为 code 或 name;回到第一页)
  const handleSearch = () => {
    setKeyword(searchInput.trim() || undefined);
    setPage(1);
  };
  // 重置:清搜索词回全量(输入框清空 + 查询态清空)
  const handleReset = () => {
    setSearchInput('');
    setKeyword(undefined);
    setPage(1);
  };

  // 新增/编辑弹窗开合:关闭时清空编辑态(防止下次点新增仍显示编辑表单)
  const openAdd = () => {
    setEditingFund(null);
    setDialogOpen(true);
  };
  const handleDialogOpenChange = (open: boolean) => {
    setDialogOpen(open);
    if (!open) setEditingFund(null);
  };

  // 无 fund:fund:list 权限(换账号后 redirectTo 误回跳本页):渲染无权限空态
  // 而非发注定 403 的请求(查询已在 useFunds/useFundTypes 内被 enabled 闸门拦下,
  // 这里兜底整页 UI,避免"登录即弹无此接口权限 toast")
  if (!canList) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-2 text-center">
        <ShieldXIcon className="text-muted-foreground size-10" />
        <p className="text-lg font-medium">无访问权限</p>
        <p className="text-muted-foreground text-sm">
          当前账号没有基金管理的访问权限,请联系管理员分配
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* ===== 工具栏(状态 Tabs + 搜索 + 类型筛选 | 批量删除 + 列显隐 + 同步 + 新增) ===== */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {/* 状态 Tabs(公共组件:字典标签由本页传入,计数由公共件从 rows 自算) */}
          <StatusFilterTabs
            value={statusFilter}
            onValueChange={handleStatusFilter}
            items={rows}
            dict={statusDict}
          />
          {/* 搜索(纯数字查代码、其余查名称;分流逻辑见 useFunds) */}
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
          {/* 批量删除(权限判断在本页把关,共享件不引入 RBAC 概念) */}
          {selectedCount > 0 && canRemove && (
            <BatchDeleteButton
              selectedCount={selectedCount}
              pending={deleteFund.isPending}
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
          {/* 基金类型(后端为普通字符串字段、精确匹配,故不走字典) */}
          <Select
            value={fundTypeFilter ?? 'all'}
            onValueChange={handleFundTypeFilter}
          >
            <SelectTrigger size="sm" className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="all">全部类型</SelectItem>
                {(fundTypes ?? []).map((type) => (
                  <SelectItem key={type} value={type}>
                    {type}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          {/* 全量同步(限流 4 次/小时,耗时长;独立 pending 不与删除态混用) */}
          <HasPermission perm="fund:fund:sync">
            <Button
              variant="outline"
              size="sm"
              disabled={syncFunds.isPending}
              onClick={() => syncFunds.mutate()}
            >
              {syncFunds.isPending ? (
                <Loader2 className="animate-spin" />
              ) : (
                <RefreshCwIcon />
              )}
              <span className="hidden lg:inline">同步基金</span>
            </Button>
          </HasPermission>
          {/* 新增基金(权限级守卫:无 fund:fund:add 时按钮不存在于 DOM) */}
          <HasPermission perm="fund:fund:add">
            <Button variant="outline" size="sm" onClick={openAdd}>
              <PlusIcon />
              <span className="hidden lg:inline">新增基金</span>
            </Button>
          </HasPermission>
        </div>
      </div>

      {/* ===== 表格(骨架组件:圆角边框容器 + bg-muted 表头 + 状态行) ===== */}
      <DataTableShell
        table={table}
        columnCount={columns.length}
        isLoading={isLoading}
        selectable
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
        leftLabel={
          <>
            已选择 {selectedCount} / {rows.length} 行
          </>
        }
      />

      {/* ===== 基金详情抽屉(同花顺档案,代码/名称列与下拉「详情」共用) ===== */}
      <FundInfoDrawer
        fundCode={infoFundCode}
        onOpenChange={(open) => {
          if (!open) setInfoFundCode(null);
        }}
      />

      {/* ===== 删除确认(单删/批删共用,AlertDialog Destructive 官方范式) ===== */}
      <DeleteConfirmDialog
        open={deleteConfirmOpen}
        onOpenChange={(open) => {
          setDeleteConfirmOpen(open);
          if (!open) setDeleteTarget(null);
        }}
        title={deleteTarget?.mode === 'batch' ? '批量删除基金' : '删除基金'}
        description={
          deleteTarget?.mode === 'batch'
            ? `确认删除所选 ${selectedIds.length} 只基金吗？此操作为逻辑删除（数据保留），已被持仓引用的基金后端会拒绝删除。`
            : `确认删除基金「${deleteTarget?.mode === 'single' ? deleteTarget.fund.name : ''}」吗？此操作为逻辑删除（数据保留），已被持仓引用时后端会拒绝删除。`
        }
        pending={deleteFund.isPending}
        onConfirm={handleConfirmDelete}
      />

      {/* ===== 新增/编辑基金弹窗(条件渲染两套表单,切换即重挂载天然无残留) ===== */}
      <Dialog open={dialogOpen} onOpenChange={handleDialogOpenChange}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{editingFund ? '编辑基金' : '新增基金'}</DialogTitle>
          </DialogHeader>
          {editingFund ? (
            <EditFundForm fund={editingFund} onDone={handleDialogOpenChange} />
          ) : (
            <AddFundForm onDone={handleDialogOpenChange} />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ===== 新增基金表单(官方 FormField 范式;状态默认正常,避免入库 NULL) =====
function AddFundForm({ onDone }: { onDone: (open: boolean) => void }) {
  const addFund = useAddFund();
  // 表单仅在弹窗打开时挂载 = 类型选项惰性请求
  const { data: fundTypes } = useFundTypes();
  const form = useForm<z.infer<typeof addFundSchema>>({
    resolver: zodResolver(addFundSchema),
    defaultValues: {
      code: '',
      name: '',
      fundType: '',
      status: '0',
      remark: '',
    },
  });

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit((values) => {
          addFund.mutate(values, {
            onSuccess: () => onDone(false),
          });
        })}
        className="space-y-4"
      >
        <FormField
          control={form.control}
          name="code"
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
        <FormField
          control={form.control}
          name="name"
          render={({ field }) => (
            <FormItem>
              <FormLabel>基金名称</FormLabel>
              <FormControl>
                <Input {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        {/* 类型:后端为普通字符串字段(精确匹配),故用固定四项的 Select 而非字典 */}
        <FormField
          control={form.control}
          name="fundType"
          render={({ field }) => (
            <FormItem>
              <FormLabel>基金类型(选填)</FormLabel>
              <Select onValueChange={field.onChange} value={field.value}>
                <FormControl>
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="请选择" />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  <SelectGroup>
                    {(fundTypes ?? []).map((type) => (
                      <SelectItem key={type} value={type}>
                        {type}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="status"
          render={({ field }) => (
            <FormItem>
              <FormLabel>状态</FormLabel>
              <FormControl>
                <DictSelect
                  dictType="sys_normal_disable"
                  value={field.value}
                  onChange={field.onChange}
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="remark"
          render={({ field }) => (
            <FormItem>
              <FormLabel>备注(选填)</FormLabel>
              <FormControl>
                <Textarea {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <DialogFooter>
          <Button type="submit" className="flex-1" disabled={addFund.isPending}>
            {addFund.isPending && <Loader2 className="animate-spin" />}
            创建
          </Button>
          {/* 取消(白色 outline):不提交直接关窗;请求进行中也禁用(防误关丢失提交反馈) */}
          <Button
            type="button"
            variant="outline"
            className="flex-1"
            disabled={addFund.isPending}
            onClick={() => onDone(false)}
          >
            取消
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}

// ===== 编辑基金表单(行数据回显;携带 fundId 供后端定位) =====
function EditFundForm({
  fund,
  onDone,
}: {
  fund: Fund;
  onDone: (open: boolean) => void;
}) {
  const editFund = useEditFund();
  const { data: fundTypes } = useFundTypes();
  const form = useForm<z.infer<typeof editFundSchema>>({
    resolver: zodResolver(editFundSchema),
    defaultValues: {
      fundId: fund.fundId,
      code: fund.code,
      name: fund.name,
      fundType: fund.fundType ?? '',
      status: (fund.status as '0' | '1') ?? '0',
      remark: fund.remark ?? '',
    },
  });

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit((values) => {
          editFund.mutate(values, {
            onSuccess: () => onDone(false),
          });
        })}
        className="space-y-4"
      >
        <FormField
          control={form.control}
          name="code"
          render={({ field }) => (
            <FormItem>
              <FormLabel>基金代码</FormLabel>
              <FormControl>
                <Input {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="name"
          render={({ field }) => (
            <FormItem>
              <FormLabel>基金名称</FormLabel>
              <FormControl>
                <Input {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="fundType"
          render={({ field }) => (
            <FormItem>
              <FormLabel>基金类型(选填)</FormLabel>
              <Select onValueChange={field.onChange} value={field.value}>
                <FormControl>
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="请选择" />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  <SelectGroup>
                    {(fundTypes ?? []).map((type) => (
                      <SelectItem key={type} value={type}>
                        {type}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="status"
          render={({ field }) => (
            <FormItem>
              <FormLabel>状态</FormLabel>
              <FormControl>
                <DictSelect
                  dictType="sys_normal_disable"
                  value={field.value}
                  onChange={field.onChange}
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="remark"
          render={({ field }) => (
            <FormItem>
              <FormLabel>备注(选填)</FormLabel>
              <FormControl>
                <Textarea {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <DialogFooter>
          <Button
            type="submit"
            className="flex-1"
            disabled={editFund.isPending}
          >
            {editFund.isPending && <Loader2 className="animate-spin" />}
            保存
          </Button>
          {/* 取消(白色 outline):不提交直接关窗;请求进行中也禁用 */}
          <Button
            type="button"
            variant="outline"
            className="flex-1"
            disabled={editFund.isPending}
            onClick={() => onDone(false)}
          >
            取消
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}

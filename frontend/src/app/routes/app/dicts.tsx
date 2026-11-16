// src/app/routes/app/dicts.tsx —— 字典管理页(字典类型列表)
// 表格设计移植自 shadcn dashboard-01 的 data-table.tsx(对齐用户管理页范式):
// 工具栏(搜索 + 状态 Tabs 过滤 + 列显隐下拉 + 新增/批量删除) / 复选框行选择 /
// 操作列下拉菜单(数据→编辑→分隔线→删除) / 页脚(每页条数 + 首上末下分页)
// 分页保持服务端契约(useDictTypes(page, pageSize)),页脚视觉绑服务端状态
// (表格骨架/页脚/列显隐/loading 与空态行已抽取为 components/shared/ 公共组件,
//  表格状态编排抽为 hooks/use-data-table)
// 点操作列「数据」进入字典数据子页(/app/system/dicts/data?dictType=xxx)
import { zodResolver } from '@hookform/resolvers/zod';
import {
  columnFilteringFeature,
  columnVisibilityFeature,
  createFilteredRowModel,
  filterFn_equalsString,
  rowSelectionFeature,
  tableFeatures,
  type ColumnDef,
} from '@tanstack/react-table';
import { EllipsisVerticalIcon, Loader2, PlusIcon } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate } from 'react-router';
import { z } from 'zod';

import { BatchDeleteButton } from '@/components/shared/batch-delete-button';
import { ColumnVisibilityDropdown } from '@/components/shared/column-visibility-dropdown';
import { DataTablePagination } from '@/components/shared/data-table-pagination';
import { DataTableShell } from '@/components/shared/data-table-shell';
import { DeleteConfirmDialog } from '@/components/shared/delete-confirm-dialog';
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
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { paths } from '@/config/paths';
import { useDict } from '@/features/dict/api/get-dict';
import { DictSelect } from '@/features/dict/components/dict-select';
import { StatusBadge } from '@/features/dict/components/status-badge';
import {
  addDictTypeSchema,
  editDictTypeSchema,
  useAddDictType,
  useDeleteDictType,
  useDictTypes,
  useEditDictType,
  type SystemDictType,
} from '@/features/dict-admin/api/get-dicts';
import { useDataTable } from '@/hooks/use-data-table';
import { HasPermission, useHasPermission } from '@/lib/authorization';
import { formatDate } from '@/utils/format';

// v9 显式注册表格特性:行选择 / 列显隐 / 列过滤(状态 Tabs 过滤用)
const features = tableFeatures({
  rowSelectionFeature,
  columnVisibilityFeature,
  columnFilteringFeature,
  filteredRowModel: createFilteredRowModel(),
  filterFns: { equalsString: filterFn_equalsString },
});

// 稳定空数组兜底(v9 要求 data 引用稳定,避免每次渲染新建 [] 导致行模型失效)
const EMPTY_DICT_TYPES: SystemDictType[] = [];

// 列显隐下拉的中文名(列 id → 标签;select/字典名称/操作 三列 enableHiding=false 不出现)
const COLUMN_LABELS: Record<string, string> = {
  dictId: 'ID',
  dictType: '字典类型',
  status: '状态',
  createTime: '创建时间',
};

// 内置种子类型(后端禁删禁改标识,前端给徽标提示)
const SEED_DICT_IDS = new Set([1, 2, 3]);

export default function DictsRoute() {
  const navigate = useNavigate();
  // ===== 服务端分页(契约同用户管理) =====
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  // 搜索:输入框受控,提交后才进查询(避免逐字发请求)
  const [searchInput, setSearchInput] = useState('');
  const [dictName, setDictName] = useState('');
  const { data, isLoading } = useDictTypes(page, pageSize, dictName);
  const deleteDictType = useDeleteDictType();
  // 操作列编辑项/批量删除的权限级守卫(ADMIN 的 *:*:* 通配放行)
  const canEdit = useHasPermission('system:dict:edit');
  const canRemove = useHasPermission('system:dict:remove');

  const rows = data?.data ?? EMPTY_DICT_TYPES;
  const meta = data?.meta;

  // 状态 Tabs 文案字典驱动(sys_normal_disable)
  const statusDict = useDict('sys_normal_disable');
  // ===== 表格状态(列显隐/行选择/列过滤由 useDataTable 托管) =====
  const [statusFilter, setStatusFilter] = useState('all'); // Tabs: all / '0' 正常 / '1' 停用
  // 新增/编辑共用弹窗:editingType=null 表示新增,非 null 表示编辑(行数据回显,无需拉详情)
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingType, setEditingType] = useState<SystemDictType | null>(null);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<
    { mode: 'single'; type: SystemDictType } | { mode: 'batch' } | null
  >(null);

  // 列定义(引用组件状态,useMemo 保持引用稳定;setState 函数本身稳定无需入 deps)
  const columns = useMemo<ColumnDef<typeof features, SystemDictType>[]>(
    () => [
      // ① 复选框列(内置种子类型禁选——后端禁删,选中也没有意义)
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
              disabled={SEED_DICT_IDS.has(row.original.dictId)}
              aria-label="选择该行"
            />
          </div>
        ),
        enableHiding: false,
      },
      { accessorKey: 'dictId', header: 'ID' },
      // ② 字典名称列(主列:link 按钮 → 进入字典数据子页)
      {
        accessorKey: 'dictName',
        header: '字典名称',
        cell: ({ row }) => (
          <Button
            variant="link"
            className="text-foreground w-fit px-0 text-left"
            onClick={() =>
              navigate(paths.app.system.dictData.getHref(row.original.dictType))
            }
          >
            {row.original.dictName}
          </Button>
        ),
        enableHiding: false,
      },
      // ③ 字典类型列(接口标识,等宽字体)
      {
        accessorKey: 'dictType',
        header: '字典类型',
        cell: ({ row }) => (
          <span className="font-mono text-sm">{row.original.dictType}</span>
        ),
      },
      // ④ 状态列(dashboard-01 Status 视觉:outline Badge + 前置图标;filterFn 供状态 Tabs 精确过滤)
      {
        accessorKey: 'status',
        header: '状态',
        cell: ({ row }) => (
          <StatusBadge
            dictType="sys_normal_disable"
            value={row.original.status}
          />
        ),
        filterFn: 'equalsString',
      },
      // ⑤ 创建时间列
      {
        accessorKey: 'createTime',
        header: '创建时间',
        cell: ({ row }) =>
          row.original.createTime ? formatDate(row.original.createTime) : '-',
      },
      // ⑥ 操作列(dashboard-01 actions:EllipsisVertical 下拉菜单)
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
                onSelect={() =>
                  navigate(
                    paths.app.system.dictData.getHref(row.original.dictType),
                  )
                }
              >
                数据
              </DropdownMenuItem>
              {canEdit && (
                <DropdownMenuItem
                  onSelect={() => {
                    setEditingType(row.original);
                    setDialogOpen(true);
                  }}
                >
                  编辑
                </DropdownMenuItem>
              )}
              {canRemove && !SEED_DICT_IDS.has(row.original.dictId) && (
                <>
                  {/* dashboard-01 范式:危险操作与普通项之间用横线隔离 */}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    variant="destructive"
                    onSelect={() => {
                      setDeleteTarget({ mode: 'single', type: row.original });
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
    [canEdit, canRemove, navigate],
  );

  // 表格装配(行选择 + 翻页/换每页条数/搜索后清空选择由 useDataTable 编排)
  const { table, setRowSelection } = useDataTable({
    features,
    data: rows,
    columns,
    getRowId: (row) => row.dictId.toString(),
    enableRowSelection: (row) => !SEED_DICT_IDS.has(row.original.dictId),
    resetSelectionOn: [page, pageSize, dictName],
  });

  const selectedCount = table.getFilteredSelectedRowModel().rows.length;
  const selectedIds = table
    .getSelectedRowModel()
    .rows.map((row) => row.original.dictId);

  // 状态 Tabs 过滤(客户端过滤当前页行——后端 list 接口不收 status 参数)
  // 计数不再在此派生:StatusFilterTabs 公共件内部从 items 自算
  const handleStatusFilter = (value: string) => {
    setStatusFilter(value);
    table
      .getColumn('status')
      ?.setFilterValue(value === 'all' ? undefined : value);
  };

  // 搜索提交(服务端模糊,回到第一页)
  const handleSearch = () => {
    setDictName(searchInput.trim());
    setPage(1);
  };
  // 重置:清搜索词回全量(输入框清空 + 查询态清空)
  const handleReset = () => {
    setSearchInput('');
    setDictName('');
    setPage(1);
  };

  // 删除确认(单删/批删共用一个受控弹窗;物理删除不可恢复)
  const handleConfirmDelete = () => {
    if (!deleteTarget) return;
    const ids =
      deleteTarget.mode === 'single' ? [deleteTarget.type.dictId] : selectedIds;
    deleteDictType.mutate(ids, {
      onSuccess: () => {
        setDeleteConfirmOpen(false);
        setDeleteTarget(null);
        setRowSelection({});
      },
    });
  };

  // 新增/编辑弹窗开合:关闭时清空编辑态(防止下次点新增仍显示编辑表单)
  const openAdd = () => {
    setEditingType(null);
    setDialogOpen(true);
  };
  const handleDialogOpenChange = (open: boolean) => {
    setDialogOpen(open);
    if (!open) setEditingType(null);
  };

  return (
    <div className="flex flex-col gap-4">
      {/* ===== 工具栏(dashboard-01:状态 Tabs + 搜索 | 批量删除 + 列显隐 + 新增) ===== */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {/* 状态 Tabs(公共组件:字典标签由本页传入,计数由公共件从 rows 自算) */}
          <StatusFilterTabs
            value={statusFilter}
            onValueChange={handleStatusFilter}
            items={rows}
            dict={statusDict}
          />
          {/* 搜索(服务端模糊:字典名称) */}
          <SearchInput
            value={searchInput}
            onValueChange={setSearchInput}
            onSubmit={handleSearch}
            onReset={handleReset}
            placeholder="搜索字典名称"
            className="w-44 pl-8"
          />
        </div>
        <div className="flex items-center gap-2">
          {/* 批量删除(权限判断在本页把关,共享件不引入 RBAC 概念) */}
          {selectedCount > 0 && canRemove && (
            <BatchDeleteButton
              selectedCount={selectedCount}
              pending={deleteDictType.isPending}
              onClick={() => {
                setDeleteTarget({ mode: 'batch' });
                setDeleteConfirmOpen(true);
              }}
            />
          )}
          {/* 列显隐下拉(dashboard-01 Columns3) */}
          <ColumnVisibilityDropdown
            table={table}
            columnLabels={COLUMN_LABELS}
          />
          {/* 新增字典类型(权限级守卫:无 system:dict:add → 按钮不存在于 DOM) */}
          <HasPermission perm="system:dict:add">
            <Button variant="outline" size="sm" onClick={openAdd}>
              <PlusIcon />
              <span className="hidden lg:inline">新增类型</span>
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

      {/* ===== 页脚(公共分页条组件) ===== */}
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

      {/* ===== 删除确认(单删/批删共用,AlertDialog Destructive 官方范式) ===== */}
      <DeleteConfirmDialog
        open={deleteConfirmOpen}
        onOpenChange={(open) => {
          setDeleteConfirmOpen(open);
          if (!open) setDeleteTarget(null);
        }}
        title={
          deleteTarget?.mode === 'batch' ? '批量删除字典类型' : '删除字典类型'
        }
        description={
          deleteTarget?.mode === 'batch'
            ? `确认删除所选 ${selectedIds.length} 个字典类型吗？物理删除，不可恢复。`
            : `确认删除字典类型「${deleteTarget?.mode === 'single' ? deleteTarget.type.dictName : ''}」吗？物理删除，不可恢复。`
        }
        pending={deleteDictType.isPending}
        onConfirm={handleConfirmDelete}
      />

      {/* ===== 新增/编辑字典类型弹窗(条件渲染两套表单,切换即重挂载天然无残留) ===== */}
      <Dialog open={dialogOpen} onOpenChange={handleDialogOpenChange}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>
              {editingType ? '编辑字典类型' : '新增字典类型'}
            </DialogTitle>
          </DialogHeader>
          {editingType ? (
            <EditDictTypeForm
              type={editingType}
              onDone={handleDialogOpenChange}
            />
          ) : (
            <AddDictTypeForm onDone={handleDialogOpenChange} />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ===== 新增字典类型表单(官方 FormField 范式) =====
function AddDictTypeForm({ onDone }: { onDone: (open: boolean) => void }) {
  const addDictType = useAddDictType();
  const form = useForm<z.infer<typeof addDictTypeSchema>>({
    resolver: zodResolver(addDictTypeSchema),
    defaultValues: {
      dictName: '',
      dictType: '',
      status: '0',
    },
  });

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit((values) => {
          addDictType.mutate(values, {
            onSuccess: () => onDone(false),
          });
        })}
        className="space-y-4"
      >
        <FormField
          control={form.control}
          name="dictName"
          render={({ field }) => (
            <FormItem>
              <FormLabel>字典名称</FormLabel>
              <FormControl>
                <Input placeholder="如 订单状态" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="dictType"
          render={({ field }) => (
            <FormItem>
              <FormLabel>字典类型</FormLabel>
              <FormControl>
                <Input placeholder="如 sys_order_status" {...field} />
              </FormControl>
              <FormDescription>唯一标识,前端按此键消费字典</FormDescription>
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
        <DialogFooter>
          <Button
            type="submit"
            className="flex-1"
            disabled={addDictType.isPending}
          >
            {addDictType.isPending && <Loader2 className="animate-spin" />}
            创建
          </Button>
          {/* 取消(白色 outline):不提交直接关窗;请求进行中也禁用 */}
          <Button
            type="button"
            variant="outline"
            className="flex-1"
            disabled={addDictType.isPending}
            onClick={() => onDone(false)}
          >
            取消
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}

// ===== 编辑字典类型表单(行数据回显;内置类型的标识禁改由后端兜底) =====
function EditDictTypeForm({
  type,
  onDone,
}: {
  type: SystemDictType;
  onDone: (open: boolean) => void;
}) {
  const editDictType = useEditDictType();
  const isSeed = SEED_DICT_IDS.has(type.dictId);
  const form = useForm<z.infer<typeof editDictTypeSchema>>({
    resolver: zodResolver(editDictTypeSchema),
    defaultValues: {
      dictId: type.dictId,
      dictName: type.dictName,
      dictType: type.dictType,
      status: (type.status as '0' | '1') ?? '0',
    },
  });

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit((values) => {
          editDictType.mutate(values, {
            onSuccess: () => onDone(false),
          });
        })}
        className="space-y-4"
      >
        <FormField
          control={form.control}
          name="dictName"
          render={({ field }) => (
            <FormItem>
              <FormLabel>字典名称</FormLabel>
              <FormControl>
                <Input {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="dictType"
          render={({ field }) => (
            <FormItem>
              <FormLabel>字典类型</FormLabel>
              <FormControl>
                {/* 内置类型的标识是前端消费契约,禁改(后端同样兜底) */}
                <Input {...field} disabled={isSeed} />
              </FormControl>
              {isSeed && (
                <FormDescription>内置字典类型的标识不允许修改</FormDescription>
              )}
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
        <DialogFooter>
          <Button
            type="submit"
            className="flex-1"
            disabled={editDictType.isPending}
          >
            {editDictType.isPending && <Loader2 className="animate-spin" />}
            保存
          </Button>
          {/* 取消(白色 outline):不提交直接关窗;请求进行中也禁用 */}
          <Button
            type="button"
            variant="outline"
            className="flex-1"
            disabled={editDictType.isPending}
            onClick={() => onDone(false)}
          >
            取消
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}

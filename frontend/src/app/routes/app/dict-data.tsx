// src/app/routes/app/dict-data.tsx —— 字典数据子页(两级页面第二级)
// 由字典类型页「数据」入口进入:/app/system/dicts/data?dictType=xxx
// 表格沿用 dashboard-01 范式(复选框行选择/列显隐/操作下拉/删除确认),
// 数据按类型全量返回不分页(后端按 dict_sort 排序,对齐菜单管理不分页的理由)
import { zodResolver } from '@hookform/resolvers/zod';
import {
  columnVisibilityFeature,
  rowSelectionFeature,
  tableFeatures,
  type ColumnDef,
} from '@tanstack/react-table';
import {
  ArrowLeftIcon,
  EllipsisVerticalIcon,
  Loader2,
  PlusIcon,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate, useSearchParams } from 'react-router';
import { z } from 'zod';

import { BatchDeleteButton } from '@/components/shared/batch-delete-button';
import { ColumnVisibilityDropdown } from '@/components/shared/column-visibility-dropdown';
import { DataTableShell } from '@/components/shared/data-table-shell';
import { DeleteConfirmDialog } from '@/components/shared/delete-confirm-dialog';
import { SearchInput } from '@/components/shared/search-input';
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
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { paths } from '@/config/paths';
import { DictSelect } from '@/features/dict/components/dict-select';
import { DictTag } from '@/features/dict/components/dict-tag';
import { StatusBadge } from '@/features/dict/components/status-badge';
import {
  addDictDataSchema,
  editDictDataSchema,
  useAddDictData,
  useDeleteDictData,
  useDictDataList,
  useEditDictData,
  type SystemDictData,
} from '@/features/dict-admin/api/get-dicts';
import { useDataTable } from '@/hooks/use-data-table';
import { HasPermission, useHasPermission } from '@/lib/authorization';
import { formatDate } from '@/utils/format';

// v9 显式注册表格特性:行选择 / 列显隐(数据量小,不注册过滤特性)
const features = tableFeatures({
  rowSelectionFeature,
  columnVisibilityFeature,
});

// 稳定空数组兜底(v9 要求 data 引用稳定)
const EMPTY_DICT_DATA: SystemDictData[] = [];

// 列显隐下拉的中文名(列 id → 标签;select/标签/操作 三列 enableHiding=false 不出现)
const COLUMN_LABELS: Record<string, string> = {
  dictSort: '排序',
  dictValue: '键值',
  cssClass: '样式',
  status: '状态',
  createTime: '创建时间',
};

// cssClass 选项(与前端 index.css 的 tag-* 类一一对应,07 第五节契约)
const CSS_CLASS_OPTIONS = [
  { value: '', label: '无样式' },
  { value: 'tag-primary', label: 'tag-primary' },
  { value: 'tag-success', label: 'tag-success' },
  { value: 'tag-danger', label: 'tag-danger' },
  { value: 'tag-warning', label: 'tag-warning' },
  { value: 'tag-info', label: 'tag-info' },
  { value: 'tag-default', label: 'tag-default' },
];

// 内置种子数据编码(后端禁删,前端给禁用提示)
const SEED_DICT_CODES = new Set([1, 2, 3, 4, 5, 6, 7]);

export default function DictDataRoute() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const dictType = searchParams.get('dictType') ?? '';

  // 无 dictType 参数直接回类型页(防裸进/参数丢失)
  useEffect(() => {
    if (!dictType) {
      navigate(paths.app.system.dicts.getHref(), { replace: true });
    }
  }, [dictType, navigate]);

  const { data, isLoading } = useDictDataList(dictType);
  const deleteDictData = useDeleteDictData();
  const canEdit = useHasPermission('system:dict:edit');
  const canRemove = useHasPermission('system:dict:remove');

  // 搜索(前端过滤:标签 dictLabel;单类型数据量小,输入态/查询态分离)
  const [searchInput, setSearchInput] = useState('');
  const [labelQuery, setLabelQuery] = useState('');
  const searchedRows = useMemo(
    () =>
      labelQuery
        ? (data ?? EMPTY_DICT_DATA).filter((r) =>
            r.dictLabel.includes(labelQuery),
          )
        : (data ?? EMPTY_DICT_DATA),
    [data, labelQuery],
  );

  const rows = searchedRows;

  // 搜索提交(前端过滤)
  const handleSearch = () => setLabelQuery(searchInput.trim());
  // 重置:清搜索词回全量
  const handleReset = () => {
    setSearchInput('');
    setLabelQuery('');
  };

  // ===== 表格状态(列显隐/行选择由 useDataTable 托管;全量数据无翻页清空需求) =====
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingData, setEditingData] = useState<SystemDictData | null>(null);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<
    { mode: 'single'; item: SystemDictData } | { mode: 'batch' } | null
  >(null);

  const columns = useMemo<ColumnDef<typeof features, SystemDictData>[]>(
    () => [
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
              disabled={SEED_DICT_CODES.has(row.original.dictCode)}
              aria-label="选择该行"
            />
          </div>
        ),
        enableHiding: false,
      },
      { accessorKey: 'dictSort', header: '排序' },
      // 标签列(主列,不可隐藏)
      {
        accessorKey: 'dictLabel',
        header: '标签',
        enableHiding: false,
      },
      {
        accessorKey: 'dictValue',
        header: '键值',
        cell: ({ row }) => (
          <span className="font-mono text-sm">{row.original.dictValue}</span>
        ),
      },
      // 样式列:有 cssClass 时用 DictTag 渲染预览(所见即所得),无则 -
      {
        accessorKey: 'cssClass',
        header: '样式',
        cell: ({ row }) =>
          row.original.cssClass ? (
            <DictTag
              dictType={dictType}
              value={row.original.dictValue}
              fallback="-"
            />
          ) : (
            '-'
          ),
      },
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
      {
        accessorKey: 'createTime',
        header: '创建时间',
        cell: ({ row }) =>
          row.original.createTime ? formatDate(row.original.createTime) : '-',
      },
      // 操作列(编辑 → 分隔线 → 删除)
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
              {canEdit && (
                <DropdownMenuItem
                  onSelect={() => {
                    setEditingData(row.original);
                    setDialogOpen(true);
                  }}
                >
                  编辑
                </DropdownMenuItem>
              )}
              {canRemove && !SEED_DICT_CODES.has(row.original.dictCode) && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    variant="destructive"
                    onSelect={() => {
                      setDeleteTarget({ mode: 'single', item: row.original });
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
    [canEdit, canRemove, dictType],
  );

  // 表格装配(行选择由 useDataTable 编排;不分页故无 resetSelectionOn)
  const { table, setRowSelection } = useDataTable({
    features,
    data: rows,
    columns,
    getRowId: (row) => row.dictCode.toString(),
    enableRowSelection: (row) => !SEED_DICT_CODES.has(row.original.dictCode),
  });

  const selectedCount = table.getFilteredSelectedRowModel().rows.length;
  const selectedIds = table
    .getSelectedRowModel()
    .rows.map((row) => row.original.dictCode);

  const handleConfirmDelete = () => {
    if (!deleteTarget) return;
    const ids =
      deleteTarget.mode === 'single'
        ? [deleteTarget.item.dictCode]
        : selectedIds;
    deleteDictData.mutate(ids, {
      onSuccess: () => {
        setDeleteConfirmOpen(false);
        setDeleteTarget(null);
        setRowSelection({});
      },
    });
  };

  const openAdd = () => {
    setEditingData(null);
    setDialogOpen(true);
  };
  const handleDialogOpenChange = (open: boolean) => {
    setDialogOpen(open);
    if (!open) setEditingData(null);
  };

  if (!dictType) return null;

  return (
    <div className="flex flex-col gap-4">
      {/* ===== 头部:返回 + 搜索/重置 | 工具栏(批量删除 + 列显隐 + 新增) ===== */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate(paths.app.system.dicts.getHref())}
          >
            <ArrowLeftIcon />
            返回
          </Button>
          {/* 搜索(前端过滤:标签) */}
          <SearchInput
            value={searchInput}
            onValueChange={setSearchInput}
            onSubmit={handleSearch}
            onReset={handleReset}
            placeholder="搜索标签"
            className="h-8 w-44 pl-8"
          />
        </div>
        {/* ===== 工具栏(批量删除 + 列显隐 + 新增) ===== */}
        <div className="flex items-center justify-end gap-2">
          {/* 批量删除(权限判断在本页把关,共享件不引入 RBAC 概念) */}
          {selectedCount > 0 && canRemove && (
            <BatchDeleteButton
              selectedCount={selectedCount}
              pending={deleteDictData.isPending}
              onClick={() => {
                setDeleteTarget({ mode: 'batch' });
                setDeleteConfirmOpen(true);
              }}
            />
          )}
          <ColumnVisibilityDropdown
            table={table}
            columnLabels={COLUMN_LABELS}
          />
          <HasPermission perm="system:dict:add">
            <Button variant="outline" size="sm" onClick={openAdd}>
              <PlusIcon />
              <span className="hidden lg:inline">新增数据</span>
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

      {/* ===== 删除确认(单删/批删共用,物理删除) ===== */}
      <DeleteConfirmDialog
        open={deleteConfirmOpen}
        onOpenChange={(open) => {
          setDeleteConfirmOpen(open);
          if (!open) setDeleteTarget(null);
        }}
        title={
          deleteTarget?.mode === 'batch' ? '批量删除字典数据' : '删除字典数据'
        }
        description={
          deleteTarget?.mode === 'batch'
            ? `确认删除所选 ${selectedIds.length} 条字典数据吗？物理删除，不可恢复。`
            : `确认删除字典数据「${deleteTarget?.mode === 'single' ? deleteTarget.item.dictLabel : ''}」吗？物理删除，不可恢复。`
        }
        pending={deleteDictData.isPending}
        onConfirm={handleConfirmDelete}
      />

      {/* ===== 新增/编辑字典数据弹窗(条件渲染两套表单) ===== */}
      <Dialog open={dialogOpen} onOpenChange={handleDialogOpenChange}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>
              {editingData ? '编辑字典数据' : '新增字典数据'}
            </DialogTitle>
          </DialogHeader>
          {editingData ? (
            <EditDictDataForm
              item={editingData}
              dictType={dictType}
              onDone={handleDialogOpenChange}
            />
          ) : (
            <AddDictDataForm
              dictType={dictType}
              onDone={handleDialogOpenChange}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ===== cssClass 选择字段(两个表单共用,07 第五节契约类名集合) =====
function CssClassField({ control }: { control: any }) {
  return (
    <FormField
      control={control}
      name="cssClass"
      render={({ field }) => (
        <FormItem>
          <FormLabel>样式类(选填)</FormLabel>
          <Select value={field.value ?? ''} onValueChange={field.onChange}>
            <FormControl>
              <SelectTrigger>
                <SelectValue placeholder="无样式" />
              </SelectTrigger>
            </FormControl>
            <SelectContent>
              <SelectGroup>
                {CSS_CLASS_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          <FormDescription>新类名需先在 index.css 定义</FormDescription>
          <FormMessage />
        </FormItem>
      )}
    />
  );
}

// ===== 新增字典数据表单 =====
function AddDictDataForm({
  dictType,
  onDone,
}: {
  dictType: string;
  onDone: (open: boolean) => void;
}) {
  const addDictData = useAddDictData(dictType);
  const form = useForm<z.infer<typeof addDictDataSchema>>({
    resolver: zodResolver(addDictDataSchema),
    defaultValues: {
      dictLabel: '',
      dictValue: '',
      dictSort: 0,
      cssClass: '',
      status: '0',
    },
  });

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit((values) => {
          addDictData.mutate(values, {
            onSuccess: () => onDone(false),
          });
        })}
        className="space-y-4"
      >
        <FormField
          control={form.control}
          name="dictLabel"
          render={({ field }) => (
            <FormItem>
              <FormLabel>标签</FormLabel>
              <FormControl>
                <Input placeholder="如 男" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="dictValue"
          render={({ field }) => (
            <FormItem>
              <FormLabel>键值</FormLabel>
              <FormControl>
                <Input placeholder="如 0" {...field} />
              </FormControl>
              <FormDescription>同类型内唯一,恒为字符串</FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="dictSort"
          render={({ field }) => (
            <FormItem>
              <FormLabel>排序</FormLabel>
              <FormControl>
                <Input type="number" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <CssClassField control={form.control} />
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
            disabled={addDictData.isPending}
          >
            {addDictData.isPending && <Loader2 className="animate-spin" />}
            创建
          </Button>
          {/* 取消(白色 outline):不提交直接关窗;请求进行中也禁用 */}
          <Button
            type="button"
            variant="outline"
            className="flex-1"
            disabled={addDictData.isPending}
            onClick={() => onDone(false)}
          >
            取消
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}

// ===== 编辑字典数据表单(行数据回显;所属类型锁定不可改) =====
function EditDictDataForm({
  item,
  dictType,
  onDone,
}: {
  item: SystemDictData;
  dictType: string;
  onDone: (open: boolean) => void;
}) {
  const editDictData = useEditDictData(dictType);
  const form = useForm<z.infer<typeof editDictDataSchema>>({
    resolver: zodResolver(editDictDataSchema),
    defaultValues: {
      dictCode: item.dictCode,
      dictLabel: item.dictLabel,
      dictValue: item.dictValue,
      dictSort: item.dictSort ?? 0,
      cssClass: item.cssClass ?? '',
      status: (item.status as '0' | '1') ?? '0',
    },
  });

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit((values) => {
          editDictData.mutate(values, {
            onSuccess: () => onDone(false),
          });
        })}
        className="space-y-4"
      >
        <FormField
          control={form.control}
          name="dictLabel"
          render={({ field }) => (
            <FormItem>
              <FormLabel>标签</FormLabel>
              <FormControl>
                <Input {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="dictValue"
          render={({ field }) => (
            <FormItem>
              <FormLabel>键值</FormLabel>
              <FormControl>
                <Input {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="dictSort"
          render={({ field }) => (
            <FormItem>
              <FormLabel>排序</FormLabel>
              <FormControl>
                <Input type="number" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <CssClassField control={form.control} />
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
            disabled={editDictData.isPending}
          >
            {editDictData.isPending && <Loader2 className="animate-spin" />}
            保存
          </Button>
          {/* 取消(白色 outline):不提交直接关窗;请求进行中也禁用 */}
          <Button
            type="button"
            variant="outline"
            className="flex-1"
            disabled={editDictData.isPending}
            onClick={() => onDone(false)}
          >
            取消
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}

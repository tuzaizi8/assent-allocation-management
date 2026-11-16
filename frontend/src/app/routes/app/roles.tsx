// src/app/routes/app/roles.tsx —— 角色管理页(系统管理界面 02)
import { zodResolver } from '@hookform/resolvers/zod';
import {
  columnVisibilityFeature,
  columnFilteringFeature,
  createFilteredRowModel,
  filterFn_equalsString,
  tableFeatures,
  type ColumnDef,
} from '@tanstack/react-table';
import { EllipsisVerticalIcon, Loader2, PlusIcon } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';

import { ColumnVisibilityDropdown } from '@/components/shared/column-visibility-dropdown';
import { DataTablePagination } from '@/components/shared/data-table-pagination';
import { DataTableShell } from '@/components/shared/data-table-shell';
import { DeleteConfirmDialog } from '@/components/shared/delete-confirm-dialog';
import { SearchInput } from '@/components/shared/search-input';
import { StatusFilterTabs } from '@/components/shared/status-filter-tabs';
import { Button } from '@/components/ui/button';
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
import { Skeleton } from '@/components/ui/skeleton';
import { Spinner } from '@/components/ui/spinner';
import { useDict } from '@/features/dict/api/get-dict';
import { DictSelect } from '@/features/dict/components/dict-select';
import { StatusBadge } from '@/features/dict/components/status-badge';
import { useAdminMenus } from '@/features/menu-admin/api/get-admin-menus';
import {
  RoleFormInput,
  roleFormSchema,
  type SystemRole,
  useAddRole,
  useDeleteRole,
  useEditRole,
  useRole,
  useRoles,
} from '@/features/roles/api/get-roles';
import { MenuTreeCheckbox } from '@/features/roles/components/menu-tree-checkbox';
import { useDataTable } from '@/hooks/use-data-table';
import { HasPermission, useHasPermission } from '@/lib/authorization';
import { formatDate } from '@/utils/format';

// v9 显式注册表格特性:列显隐 + 列过滤(状态 Tabs 客户端过滤当前页用)
const features = tableFeatures({
  columnVisibilityFeature,
  columnFilteringFeature,
  filteredRowModel: createFilteredRowModel(),
  filterFns: { equalsString: filterFn_equalsString },
});

// 稳定空数组兜底(v9 要求 data 引用稳定)
const EMPTY_ROLES: SystemRole[] = [];

// 列显隐下拉的中文名(列 id → 标签;roleName/操作 两列 enableHiding=false 不出现)
const COLUMN_LABELS: Record<string, string> = {
  roleId: 'ID',
  roleKey: '权限字符',
  roleSort: '排序',
  status: '状态',
  createTime: '创建时间',
};

const addDefaults: RoleFormInput = {
  roleName: '',
  roleKey: '',
  roleSort: 0,
  status: '0',
  remark: '',
};

export default function RolesRoute() {
  // ===== 服务端分页(契约同用户管理;pageSize state 化供页脚切换) =====
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  // 搜索(输入态/查询态分离——对齐 dicts 页模式;空=全量)
  const [searchInput, setSearchInput] = useState('');
  const [roleNameQuery, setRoleNameQuery] = useState<string | undefined>(
    undefined,
  );
  const { data, isLoading } = useRoles(page, pageSize, roleNameQuery);
  const addRole = useAddRole();
  const editRole = useEditRole();
  const deleteRole = useDeleteRole();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  // 操作列删除项 / 删除确认弹窗(dashboard-01 AlertDialog Destructive 范式)
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<SystemRole | null>(null);
  // 状态 Tabs 客户端过滤(后端 list 无 status 参数,过滤当前页——同 users 页已知边界)
  const [statusFilter, setStatusFilter] = useState('all');
  const statusDict = useDict('sys_normal_disable');
  // 菜单勾选集(独立于 zod 表单——MenuTreeCheckbox 是受控组件,非 RHF 注册字段)
  const [menuIds, setMenuIds] = useState<number[]>([]);

  // 菜单树数据(复用菜单管理域的全量列表接口)——惰性加载:仅编辑弹窗打开时请求。
  // 只有 system:role:list 的账号进列表页不发此请求,避免 403 toast(弹窗才需要勾选树)
  const { data: menus, isError: menusError } = useAdminMenus(dialogOpen);
  // 编辑时拉详情(含 menuIds 回显)
  const { data: roleDetail, isLoading: detailLoading } = useRole(
    dialogOpen ? editingId : null,
  );

  useEffect(() => {
    if (roleDetail) {
      setMenuIds(roleDetail.menuIds);
    }
  }, [roleDetail]);

  const openAdd = () => {
    setEditingId(null);
    setMenuIds([]);
    setDialogOpen(true);
  };
  const openEdit = (roleId: number) => {
    setEditingId(roleId);
    setMenuIds([]);
    setDialogOpen(true);
  };

  const rows = data?.data ?? EMPTY_ROLES;
  const meta = data?.meta;

  // 状态 Tabs 过滤(计数由 StatusFilterTabs 公共件内部从 rows 自算,不再在此派生)

  // 操作列编辑项的权限级守卫
  const canEdit = useHasPermission('system:role:edit');
  const canRemove = useHasPermission('system:role:remove');

  // 列定义(dashboard-01 范式:主列 + StatusBadge + EllipsisVertical 操作列)
  const columns = useMemo<ColumnDef<typeof features, SystemRole>[]>(
    () => [
      {
        accessorKey: 'roleName',
        header: '角色名称',
        cell: ({ row }) => (
          <span className="font-medium">{row.original.roleName}</span>
        ),
        enableHiding: false,
      },
      { accessorKey: 'roleId', header: 'ID' },
      { accessorKey: 'roleKey', header: '权限字符' },
      { accessorKey: 'roleSort', header: '排序' },
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
      {
        accessorKey: 'createTime',
        header: '创建时间',
        cell: ({ row }) =>
          row.original.createTime ? formatDate(row.original.createTime) : '-',
      },
      // 操作列(dashboard-01 actions:EllipsisVertical 下拉,危险操作横线隔离)
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
                  onSelect={() => openEdit(row.original.roleId)}
                >
                  编辑
                </DropdownMenuItem>
              )}
              {/* 内置 admin 角色前端隐藏删除(后端 delete_role_services 双保险) */}
              {canRemove && row.original.roleId !== 1 && (
                <>
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
    [canEdit, canRemove],
  );

  // 表格装配(状态 Tabs 列过滤由 useDataTable 编排;无行选择)
  const { table } = useDataTable({
    features,
    data: rows,
    columns,
    getRowId: (row) => row.roleId.toString(),
  });

  // 状态 Tabs 过滤(客户端过滤当前页行)
  const handleStatusFilter = (value: string) => {
    setStatusFilter(value);
    table
      .getColumn('status')
      ?.setFilterValue(value === 'all' ? undefined : value);
  };

  const editDefaults = useMemo<RoleFormInput>(
    () =>
      roleDetail
        ? {
            roleId: roleDetail.roleId,
            roleName: roleDetail.roleName,
            roleKey: roleDetail.roleKey,
            roleSort: roleDetail.roleSort,
            status: (roleDetail.status as '0' | '1') ?? '0',
            remark: roleDetail.remark ?? '',
          }
        : addDefaults,
    [roleDetail],
  );

  const form = useForm<RoleFormInput>({
    resolver: zodResolver(roleFormSchema),
    defaultValues: editDefaults,
  });

  // 弹窗打开时同步表单默认值:新增→空表单;编辑→详情到达后回显
  // (useForm 的 defaultValues 仅首次初始化生效,异步 roleDetail 需 reset 注入,
  //  对齐旧版 Form 组件"挂载即新建表单"的重置语义)
  useEffect(() => {
    if (!dialogOpen) return;
    form.reset(editDefaults);
  }, [dialogOpen, editDefaults, form]);

  // 搜索提交(服务端模糊:角色名称,回到第一页)
  const handleSearch = () => {
    setRoleNameQuery(searchInput.trim() || undefined);
    setPage(1);
  };
  // 重置:清搜索词回全量
  const handleReset = () => {
    setSearchInput('');
    setRoleNameQuery(undefined);
    setPage(1);
  };

  // 删除确认(操作列下拉触发,受控 AlertDialog Destructive 官方范式)
  const handleConfirmDelete = () => {
    if (!deleteTarget) return;
    deleteRole.mutate(deleteTarget.roleId, {
      onSuccess: () => {
        setDeleteConfirmOpen(false);
        setDeleteTarget(null);
      },
    });
  };

  return (
    <div className="flex flex-col gap-4">
      {/* ===== 工具栏(dashboard-01:状态 Tabs 过滤 | 列显隐 + 新增) ===== */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {/* 状态 Tabs(公共组件:字典标签由本页传入,计数由公共件从 rows 自算) */}
          <StatusFilterTabs
            value={statusFilter}
            onValueChange={handleStatusFilter}
            items={rows}
            dict={statusDict}
          />
          {/* 搜索(服务端模糊:角色名称) */}
          <SearchInput
            value={searchInput}
            onValueChange={setSearchInput}
            onSubmit={handleSearch}
            onReset={handleReset}
            placeholder="搜索角色名称"
            className="w-44 pl-8"
          />
        </div>
        <div className="flex items-center gap-2">
          {/* 列显隐下拉(公共组件,与 users/dicts 等页统一) */}
          <ColumnVisibilityDropdown
            table={table}
            columnLabels={COLUMN_LABELS}
          />
          {/* 新增角色(权限级守卫) */}
          <HasPermission perm="system:role:add">
            <Button variant="outline" size="sm" onClick={openAdd}>
              <PlusIcon />
              <span className="hidden lg:inline">新增角色</span>
            </Button>
          </HasPermission>
        </div>
      </div>

      {/* ===== 表格(骨架组件:圆角边框容器 + bg-muted 表头 + 状态行,与各管理页统一) ===== */}
      <DataTableShell
        table={table}
        columnCount={columns.length}
        isLoading={isLoading}
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
        leftLabel={meta ? <>共 {meta.totalItems} 条</> : undefined}
        idPrefix="roles-rows-per-page"
      />

      {/* ===== 删除确认(AlertDialog Destructive 官方范式) ===== */}
      <DeleteConfirmDialog
        open={deleteConfirmOpen}
        onOpenChange={(open) => {
          setDeleteConfirmOpen(open);
          if (!open) setDeleteTarget(null);
        }}
        title="删除角色"
        description={
          <>
            确认删除角色「{deleteTarget?.roleName}
            」吗?(将同时解绑其菜单与用户关联)
          </>
        }
        pending={deleteRole.isPending}
        onConfirm={handleConfirmDelete}
      />

      {/* 新增/编辑弹窗:双栏(左基础字段/右菜单权限)+ 中部滚动区 + footer 固定底部
          (修复:单栏 5 字段 + 勾选树总高超出视口,小屏漏内容——弹窗高度由滚动区钳制) */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[720px]">
          <DialogHeader>
            <DialogTitle>{editingId ? '编辑角色' : '新增角色'}</DialogTitle>
          </DialogHeader>
          {editingId && detailLoading ? (
            // 编辑详情按需单查:骨架按表单字段铺,加载完不跳版
            <div className="flex flex-col gap-4 px-1 py-2">
              {Array.from({ length: 4 }).map((_, index) => (
                <div key={index} className="flex flex-col gap-2">
                  <Skeleton className="h-3 w-16" />
                  <Skeleton className="h-9 w-full" />
                </div>
              ))}
              <Spinner className="sr-only" />
            </div>
          ) : (
            // 中部滚动区:视口高度不足时仅此区域滚动,header/footer 始终可见
            // px-1/pb-1:焦点环(ring=box-shadow)绘制在元素外约 3px,滚动容器贴边不加
            // padding 会把 w-full 字段左侧/底部的焦点环裁掉(2026-08-23 实测踩坑)
            <div className="max-h-[60vh] overflow-y-auto px-1 pb-1">
              <Form {...form} key={editingId ?? 'new'}>
                <form
                  id="role-form"
                  onSubmit={form.handleSubmit((values) => {
                    const payload = { ...values, menuIds };
                    if (editingId) {
                      editRole.mutate(payload, {
                        onSuccess: () => setDialogOpen(false),
                      });
                    } else {
                      addRole.mutate(payload, {
                        onSuccess: () => setDialogOpen(false),
                      });
                    }
                  })}
                >
                  <div className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
                    {/* 左栏:基础字段 */}
                    <div className="space-y-4">
                      <FormField
                        control={form.control}
                        name="roleName"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>角色名称</FormLabel>
                            <FormControl>
                              <Input {...field} />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name="roleKey"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>权限字符(如 editor)</FormLabel>
                            <FormControl>
                              <Input {...field} />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name="roleSort"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>显示排序</FormLabel>
                            <FormControl>
                              <Input type="number" {...field} />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      <FormField
                        control={form.control}
                        name="status"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>角色状态</FormLabel>
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
                              <Input {...field} />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      <p className="text-xs text-muted-foreground">
                        内置 admin 角色的权限字符不允许修改(后端保护)。
                      </p>
                    </div>
                    {/* 右栏:菜单权限勾选树(树体自身 320px 内滚动,双弹窗滚动互不嵌套) */}
                    <div className="space-y-2">
                      <p className="text-sm font-medium">菜单权限</p>
                      {menusError ? (
                        // 无 system:menu:list 权限(或菜单服务异常):弹窗内文案提示,
                        // 不弹全局 error toast——可保存基础字段,菜单绑定保持原样不动
                        <div className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
                          无菜单查看权限,无法调整菜单绑定(基础字段仍可编辑保存)
                        </div>
                      ) : (
                        <MenuTreeCheckbox
                          menus={menus ?? []}
                          checked={menuIds}
                          onChange={setMenuIds}
                        />
                      )}
                      <p className="text-xs text-muted-foreground">
                        勾选父级会同时勾选其全部子孙;提交后按勾选全集全量替换。
                        权限变更对已登录用户的按钮显隐需其重新登录后生效(permissions
                        是登录时的快照)。
                      </p>
                    </div>
                  </div>
                </form>
              </Form>
            </div>
          )}
          {/* footer 固定在滚动区外:通过 form 属性关联表单(原生 HTML 特性),提交按钮不随内容滚走 */}
          <DialogFooter>
            <Button
              type="submit"
              form="role-form"
              className="flex-1"
              disabled={addRole.isPending || editRole.isPending}
            >
              {(addRole.isPending || editRole.isPending) && (
                <Loader2 className="animate-spin" />
              )}
              {editingId ? '保存' : '创建'}
            </Button>
            {/* 取消(白色 outline):不提交直接关窗;请求进行中也禁用 */}
            <Button
              type="button"
              variant="outline"
              className="flex-1"
              disabled={addRole.isPending || editRole.isPending}
              onClick={() => setDialogOpen(false)}
            >
              取消
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

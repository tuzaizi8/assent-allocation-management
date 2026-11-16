// src/app/routes/app/users.tsx —— 用户管理页
// 表格设计移植自 shadcn dashboard-01 的 data-table.tsx:
// 工具栏(状态 Tabs 过滤 + 列显隐下拉 + 新增/批量删除) / 复选框行选择 /
// 账号列详情抽屉(Drawer) / 操作列下拉菜单 / 页脚(每页条数 + 首上末下分页)
// 分页保持服务端契约(useUsers(page, pageSize)),页脚视觉绑服务端状态
// (表格骨架/页脚/列显隐/loading 与空态行已抽取为 components/shared/ 公共组件,
//  表格状态编排抽为 hooks/use-data-table)
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
import { useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { BatchDeleteButton } from '@/components/shared/batch-delete-button';
import { ColumnVisibilityDropdown } from '@/components/shared/column-visibility-dropdown';
import { DataTablePagination } from '@/components/shared/data-table-pagination';
import { DataTableShell } from '@/components/shared/data-table-shell';
import { DeleteConfirmDialog } from '@/components/shared/delete-confirm-dialog';
import { DetailDrawer, DetailField } from '@/components/shared/detail-drawer';
import { EntityCell } from '@/components/shared/entity-cell';
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
import { Label } from '@/components/ui/label';
import { Spinner } from '@/components/ui/spinner';
import { useDict } from '@/features/dict/api/get-dict';
import { DictSelect } from '@/features/dict/components/dict-select';
import { StatusBadge } from '@/features/dict/components/status-badge';
import { useRoleOptions } from '@/features/roles/api/get-roles';
import {
  addUserSchema,
  editUserSchema,
  useAddUser,
  useDeleteUser,
  useEditUser,
  useUserDetail,
  useUsers,
  type SystemUser,
} from '@/features/users/api/get-users';
import { RoleRadioGroup } from '@/features/users/components/role-radio-group';
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
const EMPTY_USERS: SystemUser[] = [];

// 列显隐下拉的中文名(列 id → 标签;select/账号/操作 三列 enableHiding=false 不出现)
const COLUMN_LABELS: Record<string, string> = {
  email: '邮箱',
  status: '状态',
  createTime: '创建时间',
};

export default function UsersRoute() {
  // ===== 服务端分页(契约不变) =====
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  // 搜索(输入态/查询态分离——对齐 dicts 页模式,避免逐字发请求;空=全量)
  const [searchInput, setSearchInput] = useState('');
  const [userNameQuery, setUserNameQuery] = useState<string | undefined>(
    undefined,
  );
  const { data, isLoading } = useUsers(page, pageSize, userNameQuery);
  const deleteUser = useDeleteUser();
  // 操作列编辑项的权限级守卫(ADMIN 的 *:*:* 通配放行)
  const canEdit = useHasPermission('system:user:edit');
  // 操作列删除项 / 批量删除按钮的权限级守卫(ADMIN 的 *:*:* 通配放行)
  const canRemove = useHasPermission('system:user:remove');

  const rows = data?.data ?? EMPTY_USERS;
  const meta = data?.meta;

  // 状态 Tabs 文案字典驱动(sys_normal_disable——运营改字典这里即时变)
  const statusDict = useDict('sys_normal_disable');
  // ===== 表格状态(列显隐/行选择/列过滤由 useDataTable 托管) =====
  const [statusFilter, setStatusFilter] = useState('all'); // Tabs: all / '0' 正常 / '1' 停用
  const [viewingUser, setViewingUser] = useState<SystemUser | null>(null); // 详情抽屉
  // 新增/编辑共用弹窗:editingUser=null 表示新增,非 null 表示编辑(行数据回显,无需拉详情)
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<SystemUser | null>(null);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<
    { mode: 'single'; user: SystemUser } | { mode: 'batch' } | null
  >(null);

  // 列定义(引用组件状态,useMemo 保持引用稳定;setState 函数本身稳定无需入 deps)
  const columns = useMemo<ColumnDef<typeof features, SystemUser>[]>(
    () => [
      // ① 复选框列(dashboard-01 select 列:全选/半选/行选)
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
      // ② 账号主列:账号 + 昵称两行(昵称不再单独占列),点击打开详情抽屉
      {
        accessorKey: 'userName',
        header: '账号',
        cell: ({ row }) => (
          <EntityCell
            title={row.original.userName}
            subtitle={row.original.nickName || '未设置昵称'}
            initial={(row.original.nickName || row.original.userName)?.slice(
              0,
              1,
            )}
            onTitleClick={() => setViewingUser(row.original)}
          />
        ),
        enableHiding: false,
      },
      {
        accessorKey: 'email',
        header: '邮箱',
        cell: ({ row }) => row.original.email ?? '-',
      },
      // ③ 状态列(dashboard-01 Status 视觉:outline Badge + 前置图标;filterFn 供状态 Tabs 精确过滤)
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
      // ④ 创建时间列
      {
        accessorKey: 'createTime',
        header: '创建时间',
        cell: ({ row }) =>
          row.original.createTime ? formatDate(row.original.createTime) : '-',
      },
      // ⑤ 操作列(dashboard-01 actions:EllipsisVertical 下拉菜单)
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
              <DropdownMenuItem onSelect={() => setViewingUser(row.original)}>
                详情
              </DropdownMenuItem>
              {canEdit && (
                <DropdownMenuItem
                  onSelect={() => {
                    setEditingUser(row.original);
                    setDialogOpen(true);
                  }}
                >
                  编辑
                </DropdownMenuItem>
              )}
              {canRemove && (
                <>
                  {/* dashboard-01 范式:危险操作与普通项之间用横线隔离 */}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    variant="destructive"
                    onSelect={() => {
                      setDeleteTarget({ mode: 'single', user: row.original });
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
    getRowId: (row) => row.userId.toString(),
    enableRowSelection: true,
    resetSelectionOn: [page, pageSize],
  });

  const selectedCount = table.getFilteredSelectedRowModel().rows.length;
  const selectedIds = table
    .getSelectedRowModel()
    .rows.map((row) => row.original.userId);

  // 状态 Tabs 过滤(客户端过滤当前页行——后端 list 接口只收 pageNum/pageSize)
  // 计数不再在此派生:StatusFilterTabs 公共件内部从 items 自算
  const handleStatusFilter = (value: string) => {
    setStatusFilter(value);
    table
      .getColumn('status')
      ?.setFilterValue(value === 'all' ? undefined : value);
  };

  // 删除确认(单删/批删共用一个受控弹窗)
  const handleConfirmDelete = () => {
    if (!deleteTarget) return;
    const ids =
      deleteTarget.mode === 'single' ? [deleteTarget.user.userId] : selectedIds;
    deleteUser.mutate(ids, {
      onSuccess: () => {
        setDeleteConfirmOpen(false);
        setDeleteTarget(null);
        setRowSelection({});
      },
    });
  };

  // 搜索提交(服务端模糊,回到第一页)
  const handleSearch = () => {
    setUserNameQuery(searchInput.trim() || undefined);
    setPage(1);
  };
  // 重置:清搜索词回全量(输入框清空 + 查询态清空)
  const handleReset = () => {
    setSearchInput('');
    setUserNameQuery(undefined);
    setPage(1);
  };

  // 新增/编辑弹窗开合:关闭时清空编辑态(防止下次点新增仍显示编辑表单)
  const openAdd = () => {
    setEditingUser(null);
    setDialogOpen(true);
  };
  const handleDialogOpenChange = (open: boolean) => {
    setDialogOpen(open);
    if (!open) setEditingUser(null);
  };

  return (
    <div className="flex flex-col gap-4">
      {/* ===== 工具栏(dashboard-01:状态 Tabs 过滤 | 批量删除 + 列显隐 + 新增) ===== */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {/* 状态 Tabs(公共组件:字典标签由本页传入,计数由公共件从 rows 自算) */}
          <StatusFilterTabs
            value={statusFilter}
            onValueChange={handleStatusFilter}
            items={rows}
            dict={statusDict}
          />
          {/* 搜索(服务端模糊:账号) */}
          <SearchInput
            value={searchInput}
            onValueChange={setSearchInput}
            onSubmit={handleSearch}
            onReset={handleReset}
            placeholder="搜索账号"
            className="w-44 pl-8"
          />
        </div>
        <div className="flex items-center gap-2">
          {/* 批量删除(权限判断在本页把关,共享件不引入 RBAC 概念) */}
          {selectedCount > 0 && canRemove && (
            <BatchDeleteButton
              selectedCount={selectedCount}
              pending={deleteUser.isPending}
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
          {/* 新增用户(权限级守卫:ADMIN(*:*:*) 通配可见;common 角色无此 perm → 按钮不存在于 DOM) */}
          <HasPermission perm="system:user:add">
            <Button variant="outline" size="sm" onClick={openAdd}>
              <PlusIcon />
              <span className="hidden lg:inline">新增用户</span>
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

      {/* ===== 用户详情抽屉(dashboard-01 TableCellViewer 适配:展示字段,无图表) ===== */}
      <DetailDrawer
        open={!!viewingUser}
        onOpenChange={(open) => {
          if (!open) setViewingUser(null);
        }}
        title={viewingUser?.nickName}
        description="用户详情"
      >
        <DetailField label="账号" value={viewingUser?.userName} />
        <DetailField label="昵称" value={viewingUser?.nickName} />
        <DetailField label="邮箱" value={viewingUser?.email} />
        <DetailField label="手机号" value={viewingUser?.phonenumber} />
        <DetailField
          label="状态"
          value={
            <StatusBadge
              dictType="sys_normal_disable"
              value={viewingUser?.status}
            />
          }
        />
        <DetailField
          label="创建时间"
          value={
            viewingUser?.createTime
              ? formatDate(viewingUser.createTime)
              : undefined
          }
        />
        <DetailField label="用户 ID" value={viewingUser?.userId} />
      </DetailDrawer>

      {/* ===== 删除确认(单删/批删共用,AlertDialog Destructive 官方范式) ===== */}
      <DeleteConfirmDialog
        open={deleteConfirmOpen}
        onOpenChange={(open) => {
          setDeleteConfirmOpen(open);
          if (!open) setDeleteTarget(null);
        }}
        title={deleteTarget?.mode === 'batch' ? '批量删除用户' : '删除用户'}
        description={
          deleteTarget?.mode === 'batch'
            ? `确认删除所选 ${selectedIds.length} 个用户吗？此操作为逻辑删除，可恢复。`
            : `确认删除用户「${deleteTarget?.mode === 'single' ? deleteTarget.user.nickName : ''}」吗？此操作为逻辑删除，可恢复。`
        }
        pending={deleteUser.isPending}
        onConfirm={handleConfirmDelete}
      />

      {/* ===== 新增/编辑用户弹窗(条件渲染两套表单,切换即重挂载天然无残留) ===== */}
      <Dialog open={dialogOpen} onOpenChange={handleDialogOpenChange}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{editingUser ? '编辑用户' : '新增用户'}</DialogTitle>
          </DialogHeader>
          {editingUser ? (
            <EditUserForm user={editingUser} onDone={handleDialogOpenChange} />
          ) : (
            <AddUserForm onDone={handleDialogOpenChange} />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ===== 新增用户表单(官方 FormField 范式;含手机号/状态,status 默认正常避免入库 NULL) =====
function AddUserForm({ onDone }: { onDone: (open: boolean) => void }) {
  const addUser = useAddUser();
  // 角色单选(受控 state,不进 zod 表单——对齐 roles 页 menuIds 模式;提交时合并 payload)
  // 全局单选语义(需求修订 2026-08-27):一个用户要么管理员要么普通角色,二选一互斥
  const [roleId, setRoleId] = useState<number | null>(null);
  const [roleError, setRoleError] = useState<string | null>(null);
  // 角色选项:表单仅在弹窗打开时挂载 = 天然惰性请求(无 system:role:list 权限不触发 403 toast)
  const { data: roleOptions, isError: rolesError } = useRoleOptions();
  const form = useForm<z.infer<typeof addUserSchema>>({
    resolver: zodResolver(addUserSchema),
    defaultValues: {
      userName: '',
      nickName: '',
      password: '',
      email: '',
      phonenumber: '',
      status: '0',
    },
  });

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit((values) => {
          // 必选校验(roleId 不进 zod,受控 state 手动校验)
          if (roleId == null) {
            setRoleError('请选择一个角色');
            return;
          }
          // 提交契约不变:roleIds 数组单元素(后端全量替换兼容)
          addUser.mutate(
            { ...values, roleIds: [roleId] },
            {
              onSuccess: () => onDone(false),
            },
          );
        })}
        className="space-y-4"
      >
        <FormField
          control={form.control}
          name="userName"
          render={({ field }) => (
            <FormItem>
              <FormLabel>账号</FormLabel>
              <FormControl>
                <Input {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="nickName"
          render={({ field }) => (
            <FormItem>
              <FormLabel>昵称</FormLabel>
              <FormControl>
                <Input {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="password"
          render={({ field }) => (
            <FormItem>
              <FormLabel>密码</FormLabel>
              <FormControl>
                <Input type="password" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="email"
          render={({ field }) => (
            <FormItem>
              <FormLabel>邮箱(选填)</FormLabel>
              <FormControl>
                <Input type="email" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="phonenumber"
          render={({ field }) => (
            <FormItem>
              <FormLabel>手机号(选填)</FormLabel>
              <FormControl>
                <Input {...field} />
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
        {/* 角色单选(受控组件;Label 用原生 label——不在 FormField 上下文内不能用 FormLabel) */}
        <div className="space-y-2">
          <Label>角色</Label>
          {rolesError ? (
            <p className="rounded-md border p-3 text-sm text-muted-foreground">
              无角色查看权限(不影响其他字段保存)
            </p>
          ) : (
            <RoleRadioGroup
              roles={roleOptions?.data ?? []}
              value={roleId}
              onChange={(id) => {
                setRoleId(id);
                setRoleError(null);
              }}
            />
          )}
          {roleError && <p className="text-destructive text-sm">{roleError}</p>}
        </div>
        <DialogFooter>
          <Button type="submit" className="flex-1" disabled={addUser.isPending}>
            {addUser.isPending && <Loader2 className="animate-spin" />}
            创建
          </Button>
          {/* 取消(白色 outline):不提交直接关窗;请求进行中也禁用(防误关丢失提交反馈) */}
          <Button
            type="button"
            variant="outline"
            className="flex-1"
            disabled={addUser.isPending}
            onClick={() => onDone(false)}
          >
            取消
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}

// ===== 编辑用户表单(行数据回显;密码留空=不修改,填了=重置) =====
function EditUserForm({
  user,
  onDone,
}: {
  user: SystemUser;
  onDone: (open: boolean) => void;
}) {
  const editUser = useEditUser();
  // 角色选项与详情回显:roleIds 走详情接口(对齐 roles 页 RoleDetail.menuIds 模式),
  // 基础字段仍用行数据回显(不变)
  const { data: roleOptions, isError: rolesError } = useRoleOptions();
  const { data: detail } = useUserDetail(user.userId);
  // 单选语义:回显取第一个绑定(多角色历史数据保存时自然收敛为单角色)
  // null = 详情未到(渲染占位,避免选中闪空)
  const [roleId, setRoleId] = useState<number | null>(null);
  useEffect(() => {
    if (detail) setRoleId(detail.roleIds[0] ?? null);
  }, [detail]);
  const form = useForm<z.infer<typeof editUserSchema>>({
    resolver: zodResolver(editUserSchema),
    defaultValues: {
      userId: user.userId,
      userName: user.userName,
      nickName: user.nickName,
      password: '', // 留空=不修改
      email: user.email ?? '',
      phonenumber: user.phonenumber ?? '',
      status: (user.status as '0' | '1') ?? '0',
    },
  });

  // 空密码时剔除字段(undefined 经 JSON.stringify 丢弃,后端 exclude_unset 不会更新);
  // roleIds 随表单合并提交——后端全量替换语义:提交什么,绑定就是什么
  // 单选语义(需求修订 2026-08-27):提交单元素数组;编辑回显必有值 + RadioGroup 无法清空,恒非空
  const onSubmit = (values: z.infer<typeof editUserSchema>) => {
    const payload = {
      ...(values.password ? values : { ...values, password: undefined }),
      roleIds: roleId != null ? [roleId] : [],
    };
    editUser.mutate(payload, {
      onSuccess: () => onDone(false),
    });
  };

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
        <FormField
          control={form.control}
          name="userName"
          render={({ field }) => (
            <FormItem>
              <FormLabel>账号</FormLabel>
              <FormControl>
                <Input {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="nickName"
          render={({ field }) => (
            <FormItem>
              <FormLabel>昵称</FormLabel>
              <FormControl>
                <Input {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="password"
          render={({ field }) => (
            <FormItem>
              <FormLabel>重置密码(选填,留空不修改)</FormLabel>
              <FormControl>
                <Input type="password" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="email"
          render={({ field }) => (
            <FormItem>
              <FormLabel>邮箱(选填)</FormLabel>
              <FormControl>
                <Input type="email" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="phonenumber"
          render={({ field }) => (
            <FormItem>
              <FormLabel>手机号(选填)</FormLabel>
              <FormControl>
                <Input {...field} />
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
        {/* 角色单选(受控组件;详情未到渲染占位避免选中闪空) */}
        <div className="space-y-2">
          <Label>角色</Label>
          {rolesError ? (
            <p className="rounded-md border p-3 text-sm text-muted-foreground">
              无角色查看权限(不影响其他字段保存)
            </p>
          ) : roleId === null && !detail ? (
            <div className="flex justify-center rounded-md border p-3">
              <Spinner className="size-4" />
            </div>
          ) : (
            <>
              {/* 存量多角色历史数据:保存即全量替换收敛为单角色(一次性提示) */}
              {detail && detail.roleIds.length > 1 && (
                <p className="text-muted-foreground text-xs">
                  该用户当前绑定了多个角色（历史数据），保存后将只保留所选角色
                </p>
              )}
              <RoleRadioGroup
                roles={roleOptions?.data ?? []}
                value={roleId}
                onChange={setRoleId}
              />
            </>
          )}
        </div>
        <DialogFooter>
          <Button
            type="submit"
            className="flex-1"
            disabled={editUser.isPending}
          >
            {editUser.isPending && <Loader2 className="animate-spin" />}
            保存
          </Button>
          {/* 取消(白色 outline):不提交直接关窗;请求进行中也禁用 */}
          <Button
            type="button"
            variant="outline"
            className="flex-1"
            disabled={editUser.isPending}
            onClick={() => onDone(false)}
          >
            取消
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}

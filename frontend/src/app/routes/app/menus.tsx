// src/app/routes/app/menus.tsx —— 菜单管理页(系统管理界面 01)
import { zodResolver } from '@hookform/resolvers/zod';
import {
  columnVisibilityFeature,
  tableFeatures,
  type ColumnDef,
} from '@tanstack/react-table';
import {
  ChevronDownIcon,
  ChevronsDownUpIcon,
  ChevronsUpDownIcon,
  EllipsisVerticalIcon,
  Loader2,
  PlusIcon,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';

import { ColumnVisibilityDropdown } from '@/components/shared/column-visibility-dropdown';
import { DataTableShell } from '@/components/shared/data-table-shell';
import { DeleteConfirmDialog } from '@/components/shared/delete-confirm-dialog';
import { SearchInput } from '@/components/shared/search-input';
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useDictLabel } from '@/features/dict/api/get-dict';
import { DictSelect } from '@/features/dict/components/dict-select';
import { StatusBadge } from '@/features/dict/components/status-badge';
import {
  MenuFormInput,
  SystemMenu,
  menuFormSchema,
  useAddMenu,
  useAdminMenus,
  useDeleteMenu,
  useEditMenu,
} from '@/features/menu-admin/api/get-admin-menus';
import { useDataTable } from '@/hooks/use-data-table';
import { HasPermission, useHasPermission } from '@/lib/authorization';

// v9 显式注册表格特性:仅列显隐(全量树形数据,无行选择/列过滤需求)
const features = tableFeatures({
  columnVisibilityFeature,
});

// 稳定空数组兜底(v9 要求 data 引用稳定)
const EMPTY_FLAT_MENUS: FlatMenu[] = [];

// 列显隐下拉的中文名(列 id → 标签;menuName/操作 两列 enableHiding=false 不出现)
const COLUMN_LABELS: Record<string, string> = {
  menuType: '类型',
  orderNum: '排序',
  path: '路由地址',
  perms: '权限标识',
  visible: '显示',
  status: '状态',
};

/** 平铺列表 → 深度优先拍平(带 depth,树形缩进展示用) */
type FlatMenu = SystemMenu & { depth: number };

function flattenMenus(menus: SystemMenu[]): FlatMenu[] {
  const childrenOf = new Map<number, SystemMenu[]>();
  menus.forEach((m) => {
    const list = childrenOf.get(m.parentId ?? 0) ?? [];
    list.push(m);
    childrenOf.set(m.parentId ?? 0, list);
  });
  const result: FlatMenu[] = [];
  const walk = (parentId: number, depth: number) => {
    (childrenOf.get(parentId) ?? [])
      .sort((a, b) => (a.orderNum ?? 0) - (b.orderNum ?? 0))
      .forEach((m) => {
        result.push({ ...m, depth });
        walk(m.menuId, depth + 1);
      });
  };
  walk(0, 0);
  // 孤儿节点(父不在集合)挂顶层,容错(同后端 _build_tree 语义)
  const walked = new Set(result.map((r) => r.menuId));
  menus
    .filter((m) => !walked.has(m.menuId))
    .forEach((m) => {
      result.push({ ...m, depth: 0 });
    });
  return result;
}

// 类型标签的彩色视觉(前端管颜色;label 文案走 sys_menu_type 字典——模式 B 职责切分)
const menuTypeClassName: Record<SystemMenu['menuType'], string> = {
  M: 'bg-blue-500/15 text-blue-500',
  C: 'bg-emerald-500/15 text-emerald-500',
  F: 'bg-amber-500/15 text-amber-500',
};

const addDefaults: MenuFormInput = {
  parentId: 0,
  menuType: 'M',
  menuName: '',
  orderNum: 0,
  path: '',
  component: '',
  perms: '',
  icon: '',
  visible: '0',
  status: '0',
};

export default function MenusRoute() {
  // 菜单类型/显示状态文案字典驱动(label 走字典,颜色/图标前端管)
  const menuTypeLabel = useDictLabel('sys_menu_type');
  const showHideLabel = useDictLabel('sys_show_hide');
  const { data: menus, isLoading } = useAdminMenus();
  const addMenu = useAddMenu();
  const editMenu = useEditMenu();
  const deleteMenu = useDeleteMenu();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<SystemMenu | null>(null);
  // 删除确认(dashboard-01 AlertDialog Destructive 范式,替代 ConfirmationDialog)
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<FlatMenu | null>(null);
  // 列显隐由 useDataTable 托管
  // 操作列权限级守卫
  const canEdit = useHasPermission('system:menu:edit');
  const canRemove = useHasPermission('system:menu:remove');

  const rows = useMemo(() => flattenMenus(menus ?? []), [menus]);

  // ===== 树形折叠(纯受控状态推导,不引入 TanStack tree API) =====
  // 展开的节点 id 集(默认空 = 全折叠到顶层——解决全量平铺表超长痛点)
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());

  // 搜索(前端过滤特例:全量树+折叠场景,保留树形渲染;输入态/查询态分离)
  const [searchInput, setSearchInput] = useState('');
  const [menuQuery, setMenuQuery] = useState('');

  // 祖先链:每行的全部祖先 id(折叠显隐判断——祖先任一折叠则整条子链隐藏)
  const ancestorsOf = useMemo(() => {
    const byId = new Map(rows.map((r) => [r.menuId, r]));
    const map = new Map<number, number[]>();
    rows.forEach((r) => {
      const chain: number[] = [];
      let p = r.parentId ?? 0;
      while (p !== 0) {
        const node = byId.get(p);
        if (!node) break; // 容错:父不在集合(孤儿已在 flatten 挂顶层)
        chain.push(p);
        p = node.parentId ?? 0;
      }
      map.set(r.menuId, chain);
    });
    return map;
  }, [rows]);

  // 有子节点的 id 集(折叠开关只在这类行显示;凡作为 parentId 出现过的 id 即有子)
  const parentIds = useMemo(() => {
    const set = new Set<number>();
    rows.forEach((r) => {
      const p = r.parentId;
      if (p != null && p !== 0) set.add(p);
    });
    return set;
  }, [rows]);

  // ===== 搜索态折叠目标集(修复:折叠清空展开集致搜索结果全隐藏成空表) =====
  // fullSet(展开目标) = 所有命中行的祖先链并集 —— 全部命中可见
  // minimalSet(折叠目标) = 仅"最上层命中行"的祖先链并集 —— 只显示最上层命中行,其命中的子孙隐藏
  // 最上层命中行 = 不是其它命中行子孙的命中行(如搜"用户"是用户管理;搜"查询"是 4 个叶子按钮自身)
  const { searchFullSet, searchMinimalSet } = useMemo(() => {
    if (!menuQuery) return { searchFullSet: null, searchMinimalSet: null };
    const hits = rows.filter((r) => r.menuName.includes(menuQuery));
    const hitIds = new Set(hits.map((r) => r.menuId));
    const full = new Set<number>();
    const minimal = new Set<number>();
    hits.forEach((r) => {
      const chain = ancestorsOf.get(r.menuId) ?? [];
      chain.forEach((a) => full.add(a));
      // 最上层判定:祖先链里没有命中行(有则说明自己是某命中的子孙)
      const isTopmost = !chain.some((a) => hitIds.has(a));
      if (isTopmost) chain.forEach((a) => minimal.add(a));
    });
    return { searchFullSet: full, searchMinimalSet: minimal };
  }, [rows, ancestorsOf, menuQuery]);

  // 可见行 = 搜索命中 且 祖先链全部展开 的行(纯派生)
  const visibleRows = useMemo(
    () =>
      rows.filter(
        (r) =>
          // 搜索命中(空查询 = 全部)
          (!menuQuery || r.menuName.includes(menuQuery)) &&
          (ancestorsOf.get(r.menuId) ?? []).every((a) => expandedIds.has(a)),
      ),
    [rows, ancestorsOf, expandedIds, menuQuery],
  );

  // 搜索命中自动展开祖先链:折叠状态下命中行会被隐藏——搜索可用性要求
  // (提交查询即重置到"全部命中可见"的规范态 fullSet,丢弃上一轮手工折叠——新搜索本就该重置视图)
  useEffect(() => {
    if (!menuQuery || !searchFullSet) return;
    setExpandedIds(searchFullSet);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [menuQuery]);

  // 搜索提交(前端过滤 + 自动展开命中路径)
  const handleSearch = () => setMenuQuery(searchInput.trim());
  // 重置:清搜索 + 回默认折叠态
  const handleReset = () => {
    setSearchInput('');
    setMenuQuery('');
    setExpandedIds(new Set());
  };
  const tableRows = visibleRows.length ? visibleRows : EMPTY_FLAT_MENUS;

  // 行级折叠开关
  const toggleExpand = (menuId: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(menuId)) {
        next.delete(menuId);
      } else {
        next.add(menuId);
      }
      return next;
    });
  };

  // 全局展开/折叠:搜索态基于命中目标集(折叠=收起到最上层命中行,展开=全部命中);
  // 非搜索态保持全树父节点语义(展开=全部父节点入集;折叠=清空回顶层)
  const allParentIds = useMemo(() => Array.from(parentIds), [parentIds]);
  const allExpanded = searchFullSet
    ? [...searchFullSet].every((id) => expandedIds.has(id))
    : allParentIds.length > 0 &&
      allParentIds.every((id) => expandedIds.has(id));
  const toggleExpandAll = () => {
    if (searchFullSet && searchMinimalSet) {
      setExpandedIds(allExpanded ? searchMinimalSet : searchFullSet);
      return;
    }
    setExpandedIds(allExpanded ? new Set() : new Set(allParentIds));
  };
  // 上级菜单选项:根目录 + M/C(按钮不能当父级;编辑时排除自己——后端还有子孙校验兜底)
  const depthOf = useMemo(() => {
    const map = new Map<number, number>();
    rows.forEach((r) => map.set(r.menuId, r.depth));
    return map;
  }, [rows]);
  const parentOptions = useMemo(
    () => [
      { label: '根目录', value: 0 },
      ...(menus ?? [])
        .filter((m) => m.menuType !== 'F' && m.menuId !== editing?.menuId)
        .map((m) => ({
          label: `${'　'.repeat(depthOf.get(m.menuId) ?? 0)}${m.menuName}`,
          value: m.menuId,
        })),
    ],
    [menus, editing, depthOf],
  );

  const editDefaults = useMemo<MenuFormInput>(
    () =>
      editing
        ? {
            menuId: editing.menuId,
            parentId: editing.parentId ?? 0,
            menuType: editing.menuType,
            menuName: editing.menuName,
            orderNum: editing.orderNum ?? 0,
            path: editing.path ?? '',
            component: editing.component ?? '',
            perms: editing.perms ?? '',
            icon: editing.icon ?? '',
            visible: editing.visible ?? '0',
            status: editing.status ?? '0',
          }
        : addDefaults,
    [editing],
  );

  const form = useForm<MenuFormInput>({
    resolver: zodResolver(menuFormSchema),
    defaultValues: editDefaults,
  });
  const menuType = form.watch('menuType');

  // 弹窗打开时同步表单默认值:编辑回显/新增清空
  // (useForm 的 defaultValues 仅首次初始化生效,editing 变化需 reset 注入,
  //  对齐旧版 Form 组件"挂载即新建表单"的重置语义)
  useEffect(() => {
    if (!dialogOpen) return;
    form.reset(editDefaults);
  }, [dialogOpen, editDefaults, form]);

  const openAdd = () => {
    setEditing(null);
    setDialogOpen(true);
  };
  const openEdit = (row: SystemMenu) => {
    setEditing(row);
    setDialogOpen(true);
  };

  // 列定义(dashboard-01 范式:树形缩进主列 + 类型彩色标签 + EllipsisVertical 操作列)
  const columns = useMemo<ColumnDef<typeof features, FlatMenu>[]>(
    () => [
      {
        accessorKey: 'menuName',
        header: '菜单名称',
        // 树形缩进 + 折叠开关:有子节点的行显示 Chevron(展开朝下/折叠朝右),
        // 叶子/按钮行 w-5 占位对齐——不做占位该行缩进会左错位
        cell: ({ row }) => {
          const { depth, menuId, menuName } = row.original;
          const isParent = parentIds.has(menuId);
          const isExpanded = expandedIds.has(menuId);
          return (
            <span
              className="flex items-center gap-1"
              style={{ paddingLeft: depth * 16 }}
            >
              {isParent ? (
                <button
                  type="button"
                  onClick={() => toggleExpand(menuId)}
                  className="text-muted-foreground hover:bg-muted rounded p-0.5"
                  aria-label={isExpanded ? '折叠' : '展开'}
                  aria-expanded={isExpanded}
                >
                  <ChevronDownIcon
                    className={`size-4 transition-transform ${isExpanded ? '' : '-rotate-90'}`}
                  />
                </button>
              ) : (
                <span className="w-5" />
              )}
              <span>{menuName}</span>
            </span>
          );
        },
        enableHiding: false,
      },
      {
        accessorKey: 'menuType',
        header: '类型',
        cell: ({ row }) => (
          <span
            className={`rounded px-1.5 py-0.5 text-xs ${menuTypeClassName[row.original.menuType]}`}
          >
            {menuTypeLabel(String(row.original.menuType))}
          </span>
        ),
      },
      { accessorKey: 'orderNum', header: '排序' },
      {
        accessorKey: 'path',
        header: '路由地址',
        cell: ({ row }) => row.original.path ?? '-',
      },
      {
        accessorKey: 'perms',
        header: '权限标识',
        cell: ({ row }) => row.original.perms ?? '-',
      },
      {
        accessorKey: 'visible',
        header: '显示',
        cell: ({ row }) => showHideLabel(row.original.visible ?? '0'),
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
                <DropdownMenuItem onSelect={() => openEdit(row.original)}>
                  编辑
                </DropdownMenuItem>
              )}
              {canRemove && (
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
    [
      canEdit,
      canRemove,
      menuTypeLabel,
      showHideLabel,
      parentIds,
      expandedIds,
      toggleExpand,
    ],
  );

  // 表格装配(全量树形数据:无行选择/列过滤;树形折叠已由 visibleRows 预先过滤)
  const { table } = useDataTable({
    features,
    data: tableRows,
    columns,
    getRowId: (row) => row.menuId.toString(),
  });

  // 删除确认(操作列下拉触发)
  const handleConfirmDelete = () => {
    if (!deleteTarget) return;
    deleteMenu.mutate(deleteTarget.menuId, {
      onSuccess: () => {
        setDeleteConfirmOpen(false);
        setDeleteTarget(null);
      },
    });
  };

  return (
    <div className="flex flex-col gap-4">
      {/* ===== 工具栏(左:搜索/重置 | 右:列显隐 + 全局展开/折叠 + 新增) ===== */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {/* 搜索(前端过滤:菜单名称;命中行祖先自动展开) */}
          <SearchInput
            value={searchInput}
            onValueChange={setSearchInput}
            onSubmit={handleSearch}
            onReset={handleReset}
            placeholder="搜索菜单名称"
            className="h-8 w-44 pl-8"
          />
        </div>
        <div className="flex items-center gap-2">
          <ColumnVisibilityDropdown
            table={table}
            columnLabels={COLUMN_LABELS}
          />
          {/* 全局展开/折叠:一键切换全部层级(默认折叠到顶层) */}
          <Button
            variant="outline"
            size="sm"
            onClick={toggleExpandAll}
            disabled={allParentIds.length === 0}
          >
            {allExpanded ? <ChevronsDownUpIcon /> : <ChevronsUpDownIcon />}
            {allExpanded ? '折叠全部' : '展开全部'}
          </Button>
          {/* 新增菜单(权限级守卫) */}
          <HasPermission perm="system:menu:add">
            <Button variant="outline" size="sm" onClick={openAdd}>
              <PlusIcon />
              <span className="hidden lg:inline">新增菜单</span>
            </Button>
          </HasPermission>
        </div>
      </div>

      {/* ===== 表格(骨架组件:圆角边框容器 + bg-muted 表头 + 状态行;全量数据无页脚) ===== */}
      <DataTableShell
        table={table}
        columnCount={columns.length}
        isLoading={isLoading}
      />

      {/* ===== 删除确认(AlertDialog Destructive 官方范式) ===== */}
      <DeleteConfirmDialog
        open={deleteConfirmOpen}
        onOpenChange={(open) => {
          setDeleteConfirmOpen(open);
          if (!open) setDeleteTarget(null);
        }}
        title="删除菜单"
        description={
          <>
            确认删除菜单「{deleteTarget?.menuName}
            」吗?(存在子菜单或已分配角色时后端会拒绝)
          </>
        }
        pending={deleteMenu.isPending}
        onConfirm={handleConfirmDelete}
      />

      {/* 新增/编辑弹窗:menuType 条件字段(C 必路由地址 / F 必权限标识,zod 同款校验) */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle>{editing ? '编辑菜单' : '新增菜单'}</DialogTitle>
          </DialogHeader>
          <Form {...form}>
            <form
              onSubmit={form.handleSubmit((values) => {
                if (editing) {
                  editMenu.mutate(values, {
                    onSuccess: () => setDialogOpen(false),
                  });
                } else {
                  addMenu.mutate(values, {
                    onSuccess: () => setDialogOpen(false),
                  });
                }
              })}
              className="space-y-4"
            >
              <FormField
                control={form.control}
                name="parentId"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>上级菜单</FormLabel>
                    <Select
                      value={String(field.value)}
                      onValueChange={(v) => field.onChange(Number(v))}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {parentOptions.map((opt) => (
                          <SelectItem key={opt.value} value={String(opt.value)}>
                            {opt.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="menuType"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>菜单类型</FormLabel>
                    <FormControl>
                      <DictSelect
                        dictType="sys_menu_type"
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
                name="menuName"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>菜单名称</FormLabel>
                    <FormControl>
                      <Input {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="orderNum"
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
              {menuType !== 'F' && (
                <FormField
                  control={form.control}
                  name="path"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>
                        路由地址(需与前端 paths.ts 已注册路由一致,否则点击 404)
                      </FormLabel>
                      <FormControl>
                        <Input {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}
              {menuType === 'C' && (
                <FormField
                  control={form.control}
                  name="component"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>组件路径(选填)</FormLabel>
                      <FormControl>
                        <Input {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}
              {menuType !== 'M' && (
                <FormField
                  control={form.control}
                  name="perms"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>权限标识(如 system:user:list)</FormLabel>
                      <FormControl>
                        <Input {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}
              {menuType !== 'F' && (
                <FormField
                  control={form.control}
                  name="icon"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>图标(选填)</FormLabel>
                      <FormControl>
                        <Input {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}
              <div className="grid grid-cols-2 gap-4">
                <FormField
                  control={form.control}
                  name="visible"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>显示状态</FormLabel>
                      <FormControl>
                        <DictSelect
                          dictType="sys_show_hide"
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
                  name="status"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>菜单状态</FormLabel>
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
              </div>
              <DialogFooter>
                <Button
                  type="submit"
                  className="flex-1"
                  disabled={addMenu.isPending || editMenu.isPending}
                >
                  {(addMenu.isPending || editMenu.isPending) && (
                    <Loader2 className="animate-spin" />
                  )}
                  {editing ? '保存' : '创建'}
                </Button>
                {/* 取消(白色 outline):不提交直接关窗;请求进行中也禁用 */}
                <Button
                  type="button"
                  variant="outline"
                  className="flex-1"
                  disabled={addMenu.isPending || editMenu.isPending}
                  onClick={() => setDialogOpen(false)}
                >
                  取消
                </Button>
              </DialogFooter>
            </form>
          </Form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

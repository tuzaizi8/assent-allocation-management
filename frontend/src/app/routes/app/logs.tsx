// src/app/routes/app/logs.tsx —— 日志管理页(操作日志 + 登录日志)
// 表格范式对齐 users.tsx(dashboard-01 v9):TanStack Table + ColumnDef,
// 表格装配与骨架由 components/shared/ 的 useDataTable + DataTableShell 统一收口
// 标题/操作人列 link 开详情抽屉 + 操作列 EllipsisVertical 下拉(详情/删除) + AlertDialog 删除确认
// 页内双 Tab(操作日志/登录日志)按 category 切换**查询参数**——
// 与 users 页状态 Tabs 的本质差异:那是客户端列过滤,这是服务端分流(切 Tab 即重取)
// 搜索/日期走受控提交模式(输入态与查询态分离,避免逐字发请求)
// (表格骨架/页脚/列显隐/loading 与空态行为 components/shared/ 公共组件;详情抽屉大字段按需单查)
import {
  columnVisibilityFeature,
  tableFeatures,
  type ColumnDef,
} from '@tanstack/react-table';
import { CircleXIcon, EllipsisVerticalIcon } from 'lucide-react';
import { useMemo, useState } from 'react';

import {
  Tabs,
  TabsList,
  TabsTrigger,
} from '@/components/animate-ui/components/radix/tabs';
import { ColumnVisibilityDropdown } from '@/components/shared/column-visibility-dropdown';
import { DataTablePagination } from '@/components/shared/data-table-pagination';
import { DataTableShell } from '@/components/shared/data-table-shell';
import { DateField } from '@/components/shared/date-field';
import { DeleteConfirmDialog } from '@/components/shared/delete-confirm-dialog';
import { DetailDrawer, DetailField } from '@/components/shared/detail-drawer';
import { SearchInput } from '@/components/shared/search-input';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
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
import { useDict, useDictLabel } from '@/features/dict/api/get-dict';
import { StatusBadge } from '@/features/dict/components/status-badge';
import {
  LOG_CATEGORIES,
  useDeleteOperLog,
  useOperLogDetail,
  useOperLogs,
  type LogCategory,
  type LogFilters,
  type SystemOperLog,
  type SystemOperLogDetail,
} from '@/features/logs/api/get-logs';
import { useDataTable } from '@/hooks/use-data-table';
import { useHasPermission } from '@/lib/authorization';
import { formatDate } from '@/utils/format';

const EMPTY_LOGS: SystemOperLog[] = [];

// v9 显式注册表格特性:仅列显隐(状态过滤走服务端 filters,无行选择/列过滤需求)
const features = tableFeatures({
  columnVisibilityFeature,
});

// 列显隐下拉的中文名(操作/登录两 Tab 共用;主列与操作列 enableHiding=false 不出现)
const COLUMN_LABELS: Record<string, string> = {
  operName: '操作人员',
  operUrl: '请求URL',
  requestMethod: '请求方式',
  operIp: 'IP',
  status: '状态',
  costTime: '耗时',
  operTime: '操作时间',
};

// 业务类型彩色 chip:文案仍走字典,这里只把常见操作映射到语义色,未知值回落中性
const OPER_TYPE_TONES: Record<string, string> = {
  新增: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-400',
  修改: 'border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-400',
  删除: 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-400',
  授权: 'border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-800 dark:bg-violet-950/40 dark:text-violet-400',
  导出: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-400',
  导入: 'border-cyan-200 bg-cyan-50 text-cyan-700 dark:border-cyan-800 dark:bg-cyan-950/40 dark:text-cyan-400',
  强退: 'border-orange-200 bg-orange-50 text-orange-700 dark:border-orange-800 dark:bg-orange-950/40 dark:text-orange-400',
  生成代码:
    'border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-400',
  清空数据:
    'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-400',
};

export default function LogsRoute() {
  // 日志枚举文案字典驱动(sys_oper_status/sys_oper_type)
  const operStatusDict = useDict('sys_oper_status');
  const businessTypeLabel = useDictLabel('sys_oper_type');
  // ===== 服务端分页 + category 分流 =====
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [category, setCategory] = useState<LogCategory>(
    LOG_CATEGORIES.operation,
  );

  // 输入态(受控,提交才进查询——对齐 dicts 页 searchInput/dictName 分离模式)
  const [searchInput, setSearchInput] = useState('');
  const [statusInput, setStatusInput] = useState('all');
  const [beginDate, setBeginDate] = useState('');
  const [endDate, setEndDate] = useState('');

  // 查询态(过滤参数,点「查询」按钮才更新)
  const [filters, setFilters] = useState<LogFilters>({
    category: LOG_CATEGORIES.operation,
  });

  // category 切换:切查询参数并重置到第 1 页(服务端分流,非客户端过滤)
  const handleCategoryChange = (value: string) => {
    const next =
      value === LOG_CATEGORIES.login
        ? LOG_CATEGORIES.login
        : LOG_CATEGORIES.operation;
    setCategory(next);
    setPage(1);
    setFilters((prev) => ({ ...prev, category: next }));
  };

  const { data, isLoading } = useOperLogs(page, pageSize, filters);
  const rows = data?.data ?? EMPTY_LOGS;
  const meta = data?.meta;

  // 行详情抽屉:只记 id(2026-08-30 列表窄字段化——大字段按需单查,不再整行携带)
  const [viewingId, setViewingId] = useState<number | null>(null);
  // 详情按需加载:抽屉打开(enabled)才发请求;窄字段行仍在(标题等即时显示)
  const { data: viewingDetail, isLoading: detailLoading } =
    useOperLogDetail(viewingId);
  const viewingLog: SystemOperLogDetail | null =
    viewingDetail != null ? viewingDetail : null;

  // 列显隐由 useDataTable 托管

  // 删除确认(操作列下拉触发;users 页 deleteTarget 模式——单删形态)
  const deleteLog = useDeleteOperLog();
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<SystemOperLog | null>(null);
  // 操作列删除项的权限级守卫(ADMIN 的 *:*:* 通配放行;common 角色无此 perm → 项不渲染)
  const canRemove = useHasPermission('system:log:remove');

  const applyFilters = () => {
    setPage(1);
    setFilters({
      category,
      // 操作日志 Tab 才有标题过滤;空串剔除(后端动态 SQL 判空跳过)
      ...(category === LOG_CATEGORIES.operation && searchInput.trim()
        ? { title: searchInput.trim() }
        : {}),
      ...(searchInput.trim() && category === LOG_CATEGORIES.login
        ? { operName: searchInput.trim() }
        : {}),
      ...(statusInput !== 'all' ? { status: statusInput } : {}),
      ...(beginDate ? { beginTime: beginDate } : {}),
      ...(endDate ? { endTime: endDate } : {}),
    });
  };

  // 重置:只清搜索回全量(状态/日期过滤保留——只重置搜索语义)
  const handleReset = () => {
    setSearchInput('');
    setFilters((prev) => ({
      ...prev,
      title: undefined,
      operName: undefined,
    }));
    setPage(1);
  };

  // 删除确认(操作列下拉触发 → AlertDialog;物理删除不可恢复)
  const handleConfirmDelete = () => {
    if (!deleteTarget) return;
    deleteLog.mutate([deleteTarget.operId], {
      onSuccess: () => {
        setDeleteConfirmOpen(false);
        setDeleteTarget(null);
      },
    });
  };

  // 表格列按 category 条件生成(v9 ColumnDef,两 Tab 独立列集——menus 页同款模式)
  const isOperation = category === LOG_CATEGORIES.operation;

  // 操作列 cell(两 Tab 共用:EllipsisVertical 下拉,详情 + 删除 destructive + 横线隔离)
  // 单独 memo:仅 canRemove 变化才重建(setState 引用恒定);columns memo 依赖其稳定引用
  const actionsColumn = useMemo<ColumnDef<typeof features, SystemOperLog>>(
    () => ({
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
              onSelect={() => setViewingId(row.original.operId)}
            >
              详情
            </DropdownMenuItem>
            {canRemove && (
              <>
                {/* dashboard-01 范式:危险操作与普通项之间用横线隔离 */}
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
    }),
    [canRemove],
  );

  const columns = useMemo<ColumnDef<typeof features, SystemOperLog>[]>(() => {
    if (isOperation) {
      return [
        // 主列(操作日志):标题 link → 详情抽屉(users 账号列同款) + businessType Badge
        {
          id: 'title',
          header: '标题',
          cell: ({ row }) => {
            const typeLabel = businessTypeLabel(
              String(row.original.businessType),
            );
            return (
              <div className="flex items-center gap-2">
                <Button
                  variant="link"
                  className="text-foreground w-fit px-0 text-left"
                  onClick={() => setViewingId(row.original.operId)}
                >
                  {row.original.title}
                </Button>
                <Badge
                  variant="outline"
                  className={`px-1.5 ${
                    OPER_TYPE_TONES[typeLabel] ?? 'text-muted-foreground'
                  }`}
                >
                  {typeLabel}
                </Badge>
              </div>
            );
          },
          enableHiding: false,
        },
        { accessorKey: 'operName', header: '操作人员' },
        {
          accessorKey: 'operUrl',
          header: '请求URL',
          cell: ({ row }) => (
            <span className="text-muted-foreground max-w-48 truncate">
              {row.original.operUrl}
            </span>
          ),
        },
        { accessorKey: 'requestMethod', header: '请求方式' },
        {
          accessorKey: 'status',
          header: '状态',
          cell: ({ row }) => (
            <StatusBadge
              dictType="sys_oper_status"
              value={row.original.status}
              icons={{
                failure: <CircleXIcon className="text-destructive" />,
                unknown: <CircleXIcon className="text-destructive" />,
              }}
            />
          ),
        },
        {
          accessorKey: 'costTime',
          header: '耗时',
          cell: ({ row }) => (
            <span className="text-muted-foreground">
              {row.original.costTime}ms
            </span>
          ),
        },
        {
          accessorKey: 'operTime',
          header: '操作时间',
          cell: ({ row }) =>
            row.original.operTime ? formatDate(row.original.operTime) : '-',
        },
        actionsColumn,
      ];
    }
    // 登录日志列集(无 title/businessType/costTime;主列 link 落操作人)
    return [
      {
        accessorKey: 'operName',
        header: '操作人员',
        cell: ({ row }) => (
          <Button
            variant="link"
            className="text-foreground w-fit px-0 text-left"
            onClick={() => setViewingId(row.original.operId)}
          >
            {row.original.operName}
          </Button>
        ),
        enableHiding: false,
      },
      {
        accessorKey: 'operUrl',
        header: '请求URL',
        cell: ({ row }) => (
          <span className="text-muted-foreground max-w-48 truncate">
            {row.original.operUrl}
          </span>
        ),
      },
      { accessorKey: 'operIp', header: 'IP' },
      {
        accessorKey: 'status',
        header: '状态',
        cell: ({ row }) => (
          <StatusBadge
            dictType="sys_oper_status"
            value={row.original.status}
            icons={{
              failure: <CircleXIcon className="text-destructive" />,
              unknown: <CircleXIcon className="text-destructive" />,
            }}
          />
        ),
      },
      {
        accessorKey: 'operTime',
        header: '操作时间',
        cell: ({ row }) =>
          row.original.operTime ? formatDate(row.original.operTime) : '-',
      },
      actionsColumn,
    ];
  }, [isOperation, businessTypeLabel, actionsColumn]);

  // 表格装配(两 Tab 列集切换后传入 useDataTable;无行选择/列过滤)
  const { table } = useDataTable({
    features,
    data: rows,
    columns,
    getRowId: (row) => row.operId.toString(),
  });

  return (
    <div className="flex flex-col gap-4">
      {/* ===== category Tab + 搜索/重置(左) | 状态/日期过滤 + 查询(右) ===== */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Tabs value={category} onValueChange={handleCategoryChange}>
            <TabsList>
              <TabsTrigger value={LOG_CATEGORIES.operation}>
                操作日志
              </TabsTrigger>
              <TabsTrigger value={LOG_CATEGORIES.login}>登录日志</TabsTrigger>
            </TabsList>
          </Tabs>
          {/* 搜索框(左侧统一位):操作日志 Tab 搜标题,登录日志 Tab 搜操作人 */}
          <SearchInput
            value={searchInput}
            onValueChange={setSearchInput}
            onSubmit={applyFilters}
            onReset={handleReset}
            placeholder={isOperation ? '搜索标题...' : '搜索操作人...'}
            className="h-8 w-40 pl-8 lg:w-52"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* 列显隐下拉(dashboard-01 Columns3;主列/操作列 enableHiding=false 不出现) */}
          <ColumnVisibilityDropdown
            table={table}
            columnLabels={COLUMN_LABELS}
          />
          {/* 状态过滤(全部/成功/失败) */}
          <Select value={statusInput} onValueChange={setStatusInput}>
            <SelectTrigger size="sm" className="w-26">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="all">全部状态</SelectItem>
                {operStatusDict.map((d) => (
                  <SelectItem key={d.dictValue} value={d.dictValue}>
                    {d.dictLabel}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          {/* 时间范围(shadcn Calendar 日历选择器,Popover 承载;选中即关) */}
          <DateField
            id="logs-begin-date"
            value={beginDate}
            onChange={setBeginDate}
            placeholder="开始日期"
          />
          <span className="text-muted-foreground text-sm">至</span>
          <DateField
            id="logs-end-date"
            value={endDate}
            onChange={setEndDate}
            placeholder="结束日期"
          />
          <Button variant="outline" size="sm" onClick={applyFilters}>
            查询
          </Button>
        </div>
      </div>

      {/* ===== 表格(骨架组件:圆角边框容器 + bg-muted 表头 + 状态行) ===== */}
      <DataTableShell
        table={table}
        columnCount={columns.length}
        isLoading={isLoading}
      />

      {/* ===== 页脚分页(公共分页条组件) ===== */}
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
        leftLabel={meta ? <>共 {meta.totalItems} 条日志</> : undefined}
        idPrefix="logs-rows-per-page"
      />

      {/* ===== 日志详情抽屉(全字段;JSON 字段等宽展示;大字段按需单查) ===== */}
      <DetailDrawer
        open={viewingId != null}
        onOpenChange={(open) => {
          if (!open) setViewingId(null);
        }}
        title={viewingLog?.title ?? '日志详情'}
        description={
          viewingLog?.category === LOG_CATEGORIES.login
            ? '登录日志详情'
            : '操作日志详情'
        }
        loading={detailLoading}
        scroll
      >
        <DetailField label="模块标题" value={viewingLog?.title} />
        <DetailField
          label="业务类型"
          value={
            viewingLog
              ? businessTypeLabel(String(viewingLog.businessType))
              : '-'
          }
        />
        <DetailField label="操作人员" value={viewingLog?.operName} />
        <DetailField
          label="请求方式"
          value={viewingLog?.requestMethod ?? '-'}
        />
        <DetailField label="请求URL" value={viewingLog?.operUrl} />
        <DetailField label="操作IP" value={viewingLog?.operIp} />
        <DetailField
          label="耗时"
          value={viewingLog ? `${viewingLog.costTime}ms` : '-'}
        />
        <DetailField
          label="操作时间"
          value={viewingLog?.operTime ? formatDate(viewingLog.operTime) : '-'}
        />
        {/* JSON 字段:等宽字体 + pretty 尝试;参数/响应左右并排(各占一列) */}
        <div className="col-span-1 flex flex-col gap-1">
          <span className="text-muted-foreground">请求参数</span>
          <pre className="bg-muted max-h-40 overflow-auto rounded-md p-2 font-mono text-xs whitespace-pre-wrap">
            {prettyJson(viewingLog?.operParam)}
          </pre>
        </div>
        <div className="col-span-1 flex flex-col gap-1">
          <span className="text-muted-foreground">返回结果</span>
          <pre className="bg-muted max-h-40 overflow-auto rounded-md p-2 font-mono text-xs whitespace-pre-wrap">
            {prettyJson(viewingLog?.jsonResult)}
          </pre>
        </div>
        {viewingLog?.errorMsg && (
          <div className="col-span-2 flex flex-col gap-1">
            <span className="text-muted-foreground">错误消息</span>
            <pre className="bg-destructive/10 text-destructive max-h-40 overflow-auto rounded-md p-2 font-mono text-xs whitespace-pre-wrap">
              {viewingLog.errorMsg}
            </pre>
          </div>
        )}
        <DetailField label="方法名称" value={viewingLog?.method ?? '-'} />
      </DetailDrawer>

      {/* ===== 删除确认(操作列下拉触发,AlertDialog Destructive 官方范式;物理删除不可恢复) ===== */}
      <DeleteConfirmDialog
        open={deleteConfirmOpen}
        onOpenChange={(open) => {
          setDeleteConfirmOpen(open);
          if (!open) setDeleteTarget(null);
        }}
        title="删除日志"
        description="确认删除该条日志吗？此操作为物理删除，不可恢复。"
        pending={deleteLog.isPending}
        onConfirm={handleConfirmDelete}
      />
    </div>
  );
}

/** JSON 字段 pretty 展示:尝试 parse 缩进,失败原样(截断的响应体) */
function prettyJson(raw?: string | null): string {
  if (!raw) return '-';
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

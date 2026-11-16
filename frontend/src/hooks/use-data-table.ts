// src/hooks/use-data-table.ts —— 系统管理页表格状态编排
// 收口六页重复的 useTable 装配:列显隐/行选择/列过滤三个状态切片与其回调在此统一管理,
// 页面只传按需注册的 features 与 columns/data,分页契约与工具栏差异仍归页面
// 内部 as unknown as 的原因:features 按页组合不同,泛型未定时 v9 的 options 交叉类型
// (features: TFeatures & ValidateFeatureSlots)无法从展开字面量直接满足;
// 页面侧入参仍受 TableOptions 全量约束,类型放宽仅此一处
import {
  useTable,
  type ColumnFiltersState,
  type ColumnVisibilityState,
  type RowData,
  type RowSelectionState,
  type TableFeatures,
  type TableOptions,
} from '@tanstack/react-table';
import { useEffect, useState } from 'react';

type UseDataTableOptions<
  TFeatures extends TableFeatures,
  TData extends RowData,
> = TableOptions<TFeatures, TData> & {
  /** 依赖变化时清空行选择:服务端分页/搜索传 [page, pageSize, 查询词];全量数据页不传 */
  resetSelectionOn?: unknown[];
};

export function useDataTable<
  TFeatures extends TableFeatures,
  TData extends RowData,
>(options: UseDataTableOptions<TFeatures, TData>) {
  const [columnVisibility, setColumnVisibility] =
    useState<ColumnVisibilityState>({});
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);

  const { resetSelectionOn, ...tableOptions } = options;
  // 能力开关按 features 实际注册情况开启:未注册特性的 state 切片传入 v9 会被拒绝
  const hasRowSelection = 'rowSelectionFeature' in tableOptions.features;
  const hasColumnFiltering = 'columnFilteringFeature' in tableOptions.features;

  useEffect(() => {
    // 仅当调用方显式传入依赖时才清空;未传的页面(全量数据/树形)不重置,
    // 且避免 resetSelectionOn 缺省时每次渲染生成新 [] 触发无意义的反复重置
    if (resetSelectionOn) setRowSelection({});
    // 依赖由调用方按需传入(如 [page, pageSize]),规则无法静态核验变量数组
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, resetSelectionOn ?? []);

  const table = useTable({
    ...tableOptions,
    state: {
      ...tableOptions.state,
      columnVisibility,
      ...(hasRowSelection ? { rowSelection } : {}),
      ...(hasColumnFiltering ? { columnFilters } : {}),
    },
    onColumnVisibilityChange: setColumnVisibility,
    ...(hasRowSelection ? { onRowSelectionChange: setRowSelection } : {}),
    ...(hasColumnFiltering ? { onColumnFiltersChange: setColumnFilters } : {}),
  } as unknown as TableOptions<TFeatures, TData>);

  return {
    table,
    columnVisibility,
    setColumnVisibility,
    rowSelection,
    setRowSelection,
    columnFilters,
    setColumnFilters,
  };
}

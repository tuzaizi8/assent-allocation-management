// src/components/shared/data-table-shell.tsx —— 表格骨架(容器 + 表头 + 表体 + 状态行)
// 系统管理页逐字重复的 TableHeader/TableBody 渲染块统一收口;视觉与交互结果与页内实现一致
// 表实例走结构化类型(沿用 column-visibility-dropdown 的 duck typing 先例):
// v9 的 TFeatures 逐页不同,泛型直接建在 TFeatures 上会让 Row/Core 的 feature 方法解析失败,
// 故只对渲染上下文做泛型透传,flexRender 的 TProps 由 getContext() 返回类型推断,全程零 any
import { flexRender, type Renderable } from '@tanstack/react-table';
import { motion, useReducedMotion } from 'motion/react';

import {
  TableEmptyRow,
  TableLoadingRow,
} from '@/components/shared/table-body-states';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { cn } from '@/utils/cn';

type ShellHeader<THeaderCtx extends object> = {
  id: string;
  colSpan: number;
  isPlaceholder: boolean;
  getContext: () => THeaderCtx;
  column: { columnDef: { header?: Renderable<THeaderCtx> | undefined } };
};

type ShellCell<TCellCtx extends object> = {
  id: string;
  getContext: () => TCellCtx;
  column: { columnDef: { cell?: Renderable<TCellCtx> | undefined } };
};

// getIsSelected 可选:未注册行选择特性的表实例上不存在该方法
// original 可选:仅行级 className 按业务数据着色的页面需要透传
type ShellRow<TCellCtx extends object> = {
  id: string;
  getIsSelected?: () => boolean;
  getVisibleCells: () => ShellCell<TCellCtx>[];
  original?: unknown;
};

export type DataTableShellProps<
  THeaderCtx extends object,
  TCellCtx extends object,
> = {
  /** useTable 返回的表实例(任意 features 组合均可结构化匹配) */
  table: {
    getHeaderGroups: () => Array<{
      id: string;
      headers: ShellHeader<THeaderCtx>[];
    }>;
    getRowModel: () => { rows: ShellRow<TCellCtx>[] };
  };
  /** 状态行的 colSpan,沿用页面 columns.length(与既有行为一致) */
  columnCount: number;
  isLoading?: boolean;
  /** 行选择开启时渲染行选中高亮(data-state=selected);未开启的页面不传 */
  selectable?: boolean;
  /** 空态文案(引导型页面可覆盖默认的「暂无数据」,如持仓页的「暂无持仓,点击建仓开始记录」) */
  emptyText?: string;
  /** 行级 className(按行业务数据着色,如明细页对已全部赎回的持仓整行弱化);不传零开销 */
  rowClassName?: (row: { original?: unknown }) => string | undefined;
  /** 行进场淡入(翻页/筛选后新行依次出现);默认开启,无动画需求的页面可显式关掉 */
  animateRows?: boolean;
};

export function DataTableShell<
  THeaderCtx extends object,
  TCellCtx extends object,
>({
  table,
  columnCount,
  isLoading = false,
  selectable = false,
  emptyText,
  rowClassName,
  animateRows = true,
}: DataTableShellProps<THeaderCtx, TCellCtx>) {
  const rows = table.getRowModel().rows;
  const reduceMotion = useReducedMotion();
  return (
    <div className="overflow-hidden rounded-lg border">
      <Table>
        <TableHeader className="bg-muted">
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <TableHead key={header.id} colSpan={header.colSpan}>
                  {header.isPlaceholder
                    ? null
                    : flexRender(
                        header.column.columnDef.header,
                        header.getContext(),
                      )}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <TableLoadingRow colSpan={columnCount} />
          ) : rows.length ? (
            rows.map((row, index) => (
              // layout:排序/删除后同一批行换位置时平滑滑动,不再瞬间跳序;
              // 进场仍由 CSS 淡入负责(只动 opacity,不和 layout 的 transform 抢)
              <motion.tr
                key={row.id}
                layout={!reduceMotion}
                transition={{ layout: { duration: 0.2, ease: 'easeOut' } }}
                data-state={
                  selectable && row.getIsSelected?.() ? 'selected' : undefined
                }
                className={cn(
                  'border-b transition-colors hover:bg-muted/50 has-aria-expanded:bg-muted/50 data-[state=selected]:bg-muted',
                  animateRows &&
                    'animate-in fade-in-0 fill-mode-both duration-150 motion-reduce:animate-none',
                  rowClassName?.(row),
                )}
                // 延迟封顶:几十行时不让最后一行等太久(20ms × 最多 8 行)
                style={
                  animateRows
                    ? { animationDelay: `${Math.min(index, 8) * 20}ms` }
                    : undefined
                }
              >
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </motion.tr>
            ))
          ) : (
            <TableEmptyRow colSpan={columnCount} text={emptyText} />
          )}
        </TableBody>
      </Table>
    </div>
  );
}

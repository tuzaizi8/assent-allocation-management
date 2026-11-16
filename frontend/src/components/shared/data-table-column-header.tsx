// src/components/shared/data-table-column-header.tsx —— 可排序表头(项目自研公共组件)
//
// 两层导出,一份实现两处复用:
//   SortableHeaderButton  与 tanstack 解耦,任何列表(含纯 shadcn Table,如持仓简况页)都能用
//   DataTableColumnHeader 适配 tanstack 列,内部复用前者(持仓明细页用它)
// 三态:未排序 ArrowUpDown、升序 ArrowUp、降序 ArrowDown;首次点击按降序(金额类列先看大的)。
//
// 放 shared/ 而不是 ui/:后者是 shadcn CLI 管辖层(官方命令增删、项目禁手改),见脚手架指引
// 《04-公共能力清单》的「硬编码甄别分层原则」。
import type { Column, RowData, TableFeatures } from '@tanstack/react-table';
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { cn } from '@/utils/cn';

const SORT_ICONS = { asc: ArrowUp, desc: ArrowDown } as const;

/** false = 未排序(双箭头);'asc' / 'desc' = 当前方向 */
export type SortDirection = false | 'asc' | 'desc';

/** 左对齐(树形/文本列) / 居中(简况页三列) / 右对齐(数值列,与单元格 tabular-nums 同一阅读轴) */
const ALIGN_CLASS = {
  left: '',
  center: 'justify-center',
  right: 'justify-end pr-2',
} as const;

export type SortableHeaderButtonProps = {
  title: string;
  direction: SortDirection;
  onToggle: () => void;
  align?: keyof typeof ALIGN_CLASS;
};

export function SortableHeaderButton({
  title,
  direction,
  onToggle,
  align = 'left',
}: SortableHeaderButtonProps) {
  const Icon = direction ? SORT_ICONS[direction] : ArrowUpDown;

  return (
    <div className={cn('flex', ALIGN_CLASS[align])}>
      <Button
        variant="ghost"
        size="sm"
        // 居中时补 -ml-2 会把内容整体推偏,故只在左/右对齐时抵掉按钮的左内边距
        className={cn(
          'h-8 gap-1 px-2 font-medium',
          align !== 'center' && '-ml-2',
        )}
        onClick={onToggle}
      >
        {title}
        <Icon
          // 排序状态对屏幕阅读器与测试可见(单测按 testid 断言,避免从 DOM 里扒 class)
          data-testid={`sort-icon-${direction || 'none'}`}
          className={cn(
            'size-3.5',
            direction ? 'text-foreground' : 'text-muted-foreground',
          )}
        />
      </Button>
    </div>
  );
}

/** 只用到排序能力这一小块列 API(调用方的 features 必须注册 rowSortingFeature) */
type SortableColumnApi = {
  getIsSorted: () => SortDirection;
  toggleSorting: (desc?: boolean) => void;
};

type DataTableColumnHeaderProps<
  TFeatures extends TableFeatures,
  TData extends RowData,
  TValue,
> = {
  column: Column<TFeatures, TData, TValue>;
  title: string;
  align?: SortableHeaderButtonProps['align'];
};

export function DataTableColumnHeader<
  TFeatures extends TableFeatures,
  TData extends RowData,
  TValue,
>({
  column,
  title,
  align = 'left',
}: DataTableColumnHeaderProps<TFeatures, TData, TValue>) {
  // 泛型未定时 v9 的 Column 是「注册了 / 没注册该特性」的联合类型,故收窄一次
  // (与 useDataTable 内部放宽类型同一手法);真实类型安全由调用方的 features 声明保证。
  //
  // **不要把这两个方法解构出来**:v9 的列方法是原型方法、内部读 `this.table`,摘成裸函数后
  // `this` 变成 undefined(2026-09-22 实测:渲染即崩在 column_getIsSorted 读 table)。
  // 必须经列对象调用,让 this 保持在列上。
  const sortable = column as unknown as SortableColumnApi;

  return (
    <SortableHeaderButton
      title={title}
      align={align}
      direction={sortable.getIsSorted()}
      // 未排序 → 首次点降序;已升序 → 转降序
      onToggle={() => sortable.toggleSorting(sortable.getIsSorted() === 'asc')}
    />
  );
}

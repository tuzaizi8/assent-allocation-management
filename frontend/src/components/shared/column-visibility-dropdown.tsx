// src/components/shared/column-visibility-dropdown.tsx —— 列显隐下拉
// 6 个系统管理页工具栏 Columns3 按钮块抽取(COLUMN_LABELS 参数化)
import { ChevronDownIcon, Columns3Icon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

type ColumnVisibilityDropdownProps = {
  /** tanstack table 实例(duck typing:any features 装配的 useTable 返回值) */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  table: { getAllColumns: () => any[] };
  /** 列 id → 中文标签(缺省回落 column.id) */
  columnLabels: Record<string, string>;
};

export function ColumnVisibilityDropdown({
  table,
  columnLabels,
}: ColumnVisibilityDropdownProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm">
          <Columns3Icon />
          列显示
          <ChevronDownIcon />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-32">
        {table
          .getAllColumns()
          .filter((column) => column.getCanHide())
          .map((column) => (
            <DropdownMenuCheckboxItem
              key={column.id}
              checked={column.getIsVisible()}
              onCheckedChange={(value) => column.toggleVisibility(!!value)}
            >
              {columnLabels[column.id] ?? column.id}
            </DropdownMenuCheckboxItem>
          ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

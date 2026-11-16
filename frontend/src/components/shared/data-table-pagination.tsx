// src/components/shared/data-table-pagination.tsx —— 系统管理页公共分页条
// 从 users/logs/dicts/roles 四页 ~75 行雷同 JSX 抽取(仅 leftLabel/idPrefix 参数差)
// 服务端分页契约:page/pageSize 由调用方持有 state,组件只编排 onChange
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  ChevronsLeftIcon,
  ChevronsRightIcon,
} from 'lucide-react';
import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { Meta } from '@/types/api';

export const PAGE_SIZE_OPTIONS = [10, 20, 30, 40, 50];

type DataTablePaginationProps = {
  /** 后端分页元数据;null/undefined 或 totalItems=0 时整块不渲染 */
  meta?: Meta | null;
  page: number;
  pageSize: number;
  isLoading?: boolean;
  /** 页码变化(翻页按钮);组件内部不做额外副作用 */
  onPageChange: (page: number) => void;
  /** 每页条数变化;重置第 1 页由组件内部编排(setPageSize 时联动 setPage(1)) */
  onPageSizeChange: (size: number) => void;
  /** 左侧文案(已选择 X 行 / 共 X 条等):不传则该区域不占位 */
  leftLabel?: React.ReactNode;
  /** 每页条数 Select 的 id 前缀(页级唯一即可),默认 'rows-per-page' */
  idPrefix?: string;
};

export function DataTablePagination({
  meta,
  page,
  pageSize,
  isLoading,
  onPageChange,
  onPageSizeChange,
  leftLabel,
  idPrefix = 'rows-per-page',
}: DataTablePaginationProps) {
  if (!meta || meta.totalItems <= 0) return null;
  return (
    <div className="flex items-center justify-between">
      {leftLabel !== undefined ? (
        <div className="text-muted-foreground hidden flex-1 text-sm lg:flex">
          {leftLabel}
        </div>
      ) : null}
      <div className="flex w-full items-center gap-8 lg:w-fit">
        <div className="hidden items-center gap-2 lg:flex">
          <Label htmlFor={idPrefix} className="text-sm font-medium">
            每页条数
          </Label>
          <Select
            value={`${pageSize}`}
            onValueChange={(value) => onPageSizeChange(Number(value))}
          >
            <SelectTrigger size="sm" className="w-20" id={idPrefix}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent side="top">
              <SelectGroup>
                {PAGE_SIZE_OPTIONS.map((size) => (
                  <SelectItem key={size} value={`${size}`}>
                    {size}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>
        <div className="flex w-fit items-center justify-center text-sm font-medium">
          第 {meta.currentPage} / {meta.totalPages} 页
        </div>
        <div className="ml-auto flex items-center gap-2 lg:ml-0">
          <Button
            variant="outline"
            className="hidden h-8 w-8 p-0 lg:flex"
            onClick={() => onPageChange(1)}
            disabled={page <= 1}
          >
            <ChevronsLeftIcon />
            <span className="sr-only">首页</span>
          </Button>
          <Button
            variant="outline"
            size="icon"
            className="size-8"
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1 || isLoading}
          >
            <ChevronLeftIcon />
            <span className="sr-only">上一页</span>
          </Button>
          <Button
            variant="outline"
            size="icon"
            className="size-8"
            onClick={() => onPageChange(page + 1)}
            disabled={page >= meta.totalPages || isLoading}
          >
            <ChevronRightIcon />
            <span className="sr-only">下一页</span>
          </Button>
          <Button
            variant="outline"
            className="hidden h-8 w-8 p-0 lg:flex"
            onClick={() => onPageChange(meta.totalPages)}
            disabled={page >= meta.totalPages}
          >
            <ChevronsRightIcon />
            <span className="sr-only">末页</span>
          </Button>
        </div>
      </div>
    </div>
  );
}

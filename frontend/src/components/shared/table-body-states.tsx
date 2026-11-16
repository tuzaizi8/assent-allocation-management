// src/components/shared/table-body-states.tsx —— 表格 loading/空态行
// 6 个系统管理页 TableBody 三元两分支抽取(结构零差异)
import { EmptyStateArt } from '@/components/shared/empty-state-art';
import { Skeleton } from '@/components/ui/skeleton';
import { Spinner } from '@/components/ui/spinner';
import { TableRow, TableCell } from '@/components/ui/table';
import { cn } from '@/utils/cn';

/** 骨架行数:与常见一页条数对齐,加载态不塌成一条 spinner 行 */
const SKELETON_ROWS = 5;

/**
 * 加载行:按列铺骨架块,让加载态直接继承真实表格的列宽节奏。
 * 首格保留一个 sr-only 的 Spinner(role=status),读屏仍能播报「加载中」。
 */
export function TableLoadingRow({ colSpan }: { colSpan: number }) {
  return (
    <>
      {Array.from({ length: SKELETON_ROWS }).map((_, rowIndex) => (
        <TableRow key={rowIndex} className="hover:bg-transparent">
          {Array.from({ length: colSpan }).map((_, columnIndex) => (
            <TableCell key={columnIndex} className="h-12">
              <Skeleton
                className={cn(
                  'h-4',
                  // 首列通常是名称/主键,给宽一点;其余列交替宽窄,避免一眼看成色带
                  columnIndex === 0
                    ? 'w-3/4'
                    : columnIndex % 2 === 0
                      ? 'w-1/2'
                      : 'w-2/3',
                )}
              />
              {rowIndex === 0 && columnIndex === 0 && (
                <Spinner className="sr-only" />
              )}
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

/** 空态行:插画 + 居中文案(默认"暂无数据") */
export function TableEmptyRow({
  colSpan,
  text = '暂无数据',
}: {
  colSpan: number;
  text?: string;
}) {
  return (
    <TableRow className="hover:bg-transparent">
      <TableCell colSpan={colSpan} className="py-8">
        <div className="flex flex-col items-center gap-1.5">
          <EmptyStateArt />
          <span className="text-muted-foreground text-sm">{text}</span>
        </div>
      </TableCell>
    </TableRow>
  );
}

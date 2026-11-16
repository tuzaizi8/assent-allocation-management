import { EmptyStateArt } from '@/components/shared/empty-state-art';
import { cn } from '@/utils/cn';

/**
 * 图表空态:小尺寸插画 + 文案,用内联高度与图表等高。
 * 分析页多图可能同时为空,插画刻意比表格空态小一档并降低不透明度,避免整页都是图案。
 */
export function ChartEmpty({
  text,
  height = 230,
  className,
}: {
  text: string;
  height?: number;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'text-muted-foreground flex flex-col items-center justify-center gap-1.5 text-sm',
        className,
      )}
      style={{ height }}
    >
      <EmptyStateArt className="h-9 w-16 opacity-80" />
      <span>{text}</span>
    </div>
  );
}

import type { ReactNode } from 'react';

import { Button } from '@/components/ui/button';
import { cn } from '@/utils/cn';

/**
 * 表格主列的两行身份单元格:28px 首字/图标方块 + 主标题 + 副标题。
 * 首字优先表达业务类型(基金取类型首字,交易取买入/赎回),没有类型信息时可传图标或隐藏;
 * 副标题传代码时用等宽字体(monoSubtitle),与 fintech 的 symbol 芯片同一读法。
 */
export function EntityCell({
  title,
  subtitle,
  initial,
  leading,
  hideLeading = false,
  leadingClassName,
  onTitleClick,
  monoSubtitle = false,
  className,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  /** 首字方块文案;不传显示 ? */
  initial?: string;
  /** 自定义方块内容(图标等),优先于 initial */
  leading?: ReactNode;
  /** 指数管理等不需要首字块的页面传 true */
  hideLeading?: boolean;
  /** 方块底色/文字色覆盖(如基金类型色调) */
  leadingClassName?: string;
  /** 传了才把主标题渲染成可点击链接 */
  onTitleClick?: () => void;
  /** 副标题是否等宽(基金/指数代码) */
  monoSubtitle?: boolean;
  className?: string;
}) {
  return (
    <div className={cn('flex items-center gap-2.5', className)}>
      {!hideLeading && (
        <span
          className={cn(
            'bg-muted text-muted-foreground flex size-7 shrink-0 items-center justify-center rounded-lg text-xs font-medium',
            leadingClassName,
          )}
        >
          {leading ?? initial ?? '?'}
        </span>
      )}
      <div className="min-w-0">
        {onTitleClick ? (
          <Button
            variant="link"
            className="text-foreground h-auto max-w-56 justify-start px-0 py-0 text-left text-sm font-medium"
            onClick={onTitleClick}
          >
            <span className="truncate">{title}</span>
          </Button>
        ) : (
          <div className="max-w-56 truncate text-sm font-medium">{title}</div>
        )}
        {subtitle != null && subtitle !== '' && (
          <div
            className={cn(
              'text-muted-foreground max-w-56 truncate text-xs',
              monoSubtitle && 'font-mono',
            )}
          >
            {subtitle}
          </div>
        )}
      </div>
    </div>
  );
}

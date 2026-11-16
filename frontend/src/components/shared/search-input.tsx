// src/components/shared/search-input.tsx —— 受控提交搜索框 + 重置按钮
// 6 个系统管理页逐字重复的搜索区统一收口;视觉与交互结果与页内实现一致
// 受控提交模式:输入态与查询态分离,回车才发请求(避免逐字请求打爆后端)
// className 需逐页显式传入现值——各页宽度存在三档变体(w-44 / h-8 w-44 / h-8 w-40 lg:w-52),
// 统一成默认值会引入无意的视觉变更
import { RefreshCwIcon, SearchIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export type SearchInputProps = {
  value: string;
  onValueChange: (value: string) => void;
  /** 回车提交 */
  onSubmit: () => void;
  /** 重置(各页语义略有差异:有的清搜索回全量,有的只清搜索保留其他过滤) */
  onReset: () => void;
  placeholder: string;
  /** 输入框宽度(pl-8 为左侧搜索图标留白,不可省略) */
  className?: string;
  /** 重置按钮的无障碍标签 */
  resetLabel?: string;
};

export function SearchInput({
  value,
  onValueChange,
  onSubmit,
  onReset,
  placeholder,
  className = 'w-44 pl-8',
  resetLabel = '重置搜索',
}: SearchInputProps) {
  return (
    <>
      <div className="relative">
        <SearchIcon className="text-muted-foreground absolute top-1/2 left-2 size-4 -translate-y-1/2" />
        <Input
          value={value}
          onChange={(e) => onValueChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') onSubmit();
          }}
          placeholder={placeholder}
          className={className}
          aria-label={placeholder}
        />
      </div>
      {/* 重置:图标 button */}
      <Button
        variant="ghost"
        size="icon"
        className="text-muted-foreground size-8"
        onClick={onReset}
        aria-label={resetLabel}
      >
        <RefreshCwIcon className="size-4" />
      </Button>
    </>
  );
}

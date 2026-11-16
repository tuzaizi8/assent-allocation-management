// src/components/shared/batch-delete-button.tsx —— 批量删除按钮("删除所选(N)")
// users/dicts/dict-data 三页逐字重复的批量删除条统一收口;视觉与交互结果与页内实现一致
// 是否渲染由页面用 `selectedCount > 0 && canRemove` 把关:权限判断不进共享层,
// 否则共享件要引入 RBAC 概念并反向依赖业务层 hook
import { Trash2Icon } from 'lucide-react';

import { Button } from '@/components/ui/button';

export type BatchDeleteButtonProps = {
  selectedCount: number;
  /** 删除请求进行中(各页 mutation 的 isPending) */
  pending: boolean;
  onClick: () => void;
  /** 按钮文案前缀,默认"删除所选" */
  label?: string;
};

export function BatchDeleteButton({
  selectedCount,
  pending,
  onClick,
  label = '删除所选',
}: BatchDeleteButtonProps) {
  return (
    <Button
      variant="outline"
      size="sm"
      // 勾选后按钮才出现:进场给一帧位移,避免工具栏突然多出一块;系统减弱动态时直接出现
      className="text-destructive animate-in fade-in-0 slide-in-from-top-1 duration-150 motion-reduce:animate-none"
      disabled={pending}
      onClick={onClick}
    >
      <Trash2Icon />
      {label}({selectedCount})
    </Button>
  );
}

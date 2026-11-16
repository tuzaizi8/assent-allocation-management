// src/features/statement-import/components/statement-confirm-dialog.tsx —— 导入二次确认
// 与共用件 delete-confirm-dialog 的唯一区别是语义:导入不是删数据,套删除的视觉(垃圾桶图标 +
// 红色按钮 + "此操作不可撤销")会让人以为自己在删东西。故单独一个:主色按钮 + 导入图标。
// UI 层约束:size="sm" 下 AlertDialogFooter 是 grid-cols-2 且 DOM 顺序即左右顺序 → Cancel 写在 Action 前。
// 点确认后由调用方立刻关弹窗并转入"处理中",所以这里不需要 pending 态(没有要等的按钮)。
import { FileInputIcon } from 'lucide-react';
import type * as React from 'react';

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogMedia,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';

type StatementConfirmDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: React.ReactNode;
  description: React.ReactNode;
  onConfirm: () => void;
  confirmText?: string;
};

export function StatementConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  onConfirm,
  confirmText = '确认导入',
}: StatementConfirmDialogProps) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent size="sm">
        <AlertDialogHeader>
          <AlertDialogMedia className="bg-primary/10">
            <FileInputIcon className="text-primary" />
          </AlertDialogMedia>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>
            {confirmText}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

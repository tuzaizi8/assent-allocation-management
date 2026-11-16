// src/components/shared/delete-confirm-dialog.tsx —— 二次确认弹窗(AlertDialog Destructive 官方范式)
// 6 个系统管理页逐字重复的删除确认框统一收口;视觉与交互结果与页内实现一致
// 默认是删除语义(红底垃圾桶 + 红色确认按钮),非删除但同样需要二次确认的操作
// (如快照「重建」:会先清空再重算,属重操作但不该被看成删除)传 destructive={false} 走中性变体
// 文案走"全 props 注入"而非语义参数:各页有批量/单选二态、逻辑删除(可恢复)与
// 物理删除(不可恢复)之分,menus 页还追加了后端拒绝说明——做成语义 props 会让共享层
// 被文案分支塞满,故 title/description 直接收 ReactNode,共享件内零业务分支
// (icon/destructive 只切换视觉,不带任何文案分支)
// 两个硬约束(改动前务必读):
//   ① size="sm" 决定 header 恒定居中、footer 为 grid-cols-2
//   ② size="sm" 下 DOM 顺序即左右顺序——删除在左、取消在右,不可调换
//   ③ onClick 的 e.preventDefault() 阻止 Radix 默认关闭,使请求进行中弹窗保持、
//      由 onSuccess 控制关闭;漏掉会导致删除中弹窗提前关闭
import { Loader2, Trash2Icon } from 'lucide-react';
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

export type DeleteConfirmDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 标题(各页按单删/批删二态自行给文案) */
  title: React.ReactNode;
  /** 描述(各页按逻辑/物理删除、是否批量自行给文案) */
  description: React.ReactNode;
  /** 删除请求进行中:禁用按钮 + 显示 spinner */
  pending: boolean;
  onConfirm: () => void;
  confirmText?: string;
  /** 顶部图标(默认垃圾桶):非删除语义的确认框传与操作语义一致的图标 */
  icon?: React.ReactNode;
  /** 是否删除语义(默认 true):false 时图标底色改中性、确认按钮不用 destructive 红 */
  destructive?: boolean;
};

export function DeleteConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  pending,
  onConfirm,
  confirmText = '确认删除',
  icon,
  destructive = true,
}: DeleteConfirmDialogProps) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      {/* size="sm" 是官方 Destructive demo 的关键:header 恒定居中(图标最上方居中),footer 两列 grid */}
      <AlertDialogContent size="sm">
        <AlertDialogHeader>
          <AlertDialogMedia
            className={destructive ? 'bg-destructive/10' : 'bg-muted'}
          >
            {icon ?? <Trash2Icon className="text-destructive" />}
          </AlertDialogMedia>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {/* size="sm" 下 footer 为 grid-cols-2,DOM 顺序即左右:删除在左,取消在右 */}
        <AlertDialogFooter>
          <AlertDialogAction
            variant={destructive ? 'destructive' : 'default'}
            disabled={pending}
            onClick={(e) => {
              // 阻止 Radix 默认关闭:请求进行中弹窗保持,由 onSuccess 控制关闭
              e.preventDefault();
              onConfirm();
            }}
          >
            {pending && <Loader2 className="animate-spin" />}
            {confirmText}
          </AlertDialogAction>
          <AlertDialogCancel disabled={pending}>取消</AlertDialogCancel>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

// src/features/dict/components/status-badge.tsx
// 通用字典状态徽章(消费模式 B):label 走字典,图标按语义槽位配置——
// dashboard-01 Status 视觉范式(outline Badge + 前置图标)的统一实现,
// 替代原 users/dicts/dict-data/logs 四处重复的 UserStatusBadge 等变体
import { CircleAlertIcon, CircleCheckIcon, CircleOffIcon } from 'lucide-react';
import type { ReactNode } from 'react';

import { Badge } from '@/components/ui/badge';

import { useDict } from '../api/get-dict';

// ===== 默认图标常量(导出供消费方复用) =====

/** 成功/正常:绿实心圆 + 白对勾(fill 只管填充,描边仍是 currentColor——不处理会呈现灰黑环+灰黑对勾,原 users 页坑 2) */
export const STATUS_SUCCESS_ICON = (
  <CircleCheckIcon className="fill-green-500 dark:fill-green-400 [&>circle]:stroke-none [&>path]:stroke-white" />
);
/** 失败/停用:灰色禁用语义 */
export const STATUS_FAILURE_ICON = <CircleOffIcon />;
/** 未知值兜底:警示语义 */
export const STATUS_UNKNOWN_ICON = <CircleAlertIcon />;

interface StatusBadgeProps {
  /** 字典类型:label 来源,如 'sys_normal_disable' / 'sys_oper_status' */
  dictType: string;
  /** 状态值:兼容 string('0'/'1') 与 number(0/1)——组件内统一 String() 归一 */
  value: string | number | null | undefined;
  /** 语义槽位图标(按值分支渲染;不传槽位则用默认三件套,传空对象则纯 label 徽章) */
  icons?: {
    success?: ReactNode;
    failure?: ReactNode;
    unknown?: ReactNode;
  };
  /** 判定"成功/正常"的值(默认 '0') */
  successValue?: string;
  /** 判定"失败/停用"的值(默认 '1';其它值走 unknown 分支) */
  failureValue?: string;
  /** 字典未命中时的兜底文案(默认 '未知') */
  fallback?: string;
  /** 透传 Badge className */
  className?: string;
}

/**
 * 字典状态徽章
 * 职责切分:字典管 label 文案,视觉(图标+着色)归前端——模式 B
 *
 * @example
 * // 三同构变体(users/dicts/dict-data):零配置
 * <StatusBadge dictType="sys_normal_disable" value={row.original.status} />
 *
 * // logs 变体:覆盖 failure 图标为红 X(非 0 全走 failure,unknown 传同款)
 * <StatusBadge
 *   dictType="sys_oper_status"
 *   value={row.status}
 *   failure={<CircleXIcon className="text-destructive" />}
 *   unknown={<CircleXIcon className="text-destructive" />}
 * />
 */
export function StatusBadge({
  dictType,
  value,
  icons,
  successValue = '0',
  failureValue = '1',
  fallback = '未知',
  className,
}: StatusBadgeProps) {
  const dict = useDict(dictType);
  const normalized = value == null ? null : String(value);
  const label =
    dict.find((d) => d.dictValue === normalized)?.dictLabel ?? fallback;

  // 图标分支:success → failure → unknown(值未命中任何已知分支)
  let icon: ReactNode;
  if (normalized === successValue) {
    icon = icons?.success ?? STATUS_SUCCESS_ICON;
  } else if (normalized === failureValue) {
    icon = icons?.failure ?? STATUS_FAILURE_ICON;
  } else {
    icon = icons?.unknown ?? STATUS_UNKNOWN_ICON;
  }

  return (
    <Badge
      variant="outline"
      className={className ?? 'text-muted-foreground px-1.5'}
    >
      {icon}
      {label}
    </Badge>
  );
}

// src/lib/has-permission.tsx
import { ReactNode } from 'react';

import { usePermissions } from './use-permissions';

interface HasPermissionProps {
  perm: string; // 权限标识，如 'system:user:add'
  fallback?: ReactNode; // 无权限时的兜底（默认不渲染）
  children: ReactNode;
}

/**
 * 权限级 RBAC 守卫组件
 * 有 perm 权限时渲染 children，无权限时渲染 fallback
 *
 * 后端类比：相当于后端接口层的 if not has_perm: raise 403
 * 区别：前端是 UX 隐藏（不渲染），后端是强制拦截（抛异常）
 *
 * @example
 * <HasPermission perm="system:user:add">
 *   <Button>新增</Button>
 * </HasPermission>
 */
export function HasPermission({
  perm,
  fallback = null,
  children,
}: HasPermissionProps) {
  const permissions = usePermissions();
  // 通配符 *:*:* 表示超级管理员，拥有全部权限
  const has = permissions.includes(perm) || permissions.includes('*:*:*');
  return <>{has ? children : fallback}</>;
}

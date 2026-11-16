// src/lib/use-permissions.ts
import { useUser } from './auth';

/**
 * 获取当前用户的权限列表
 * 后端类比：从 Session 取 perms 列表
 *
 * @returns permissions 数组，如 ['system:user:list', 'system:user:add']
 *          未登录或无 permissions 时返回空数组
 */
export function usePermissions(): string[] {
  const user = useUser();
  return user.data?.permissions ?? [];
}

/**
 * 判断当前用户是否拥有某权限
 * 支持通配符 *:*:*（超级管理员拥有全部权限）
 *
 * @param perm - 权限标识，如 'system:user:add'
 * @returns true 表示有权限
 */
export function useHasPermission(perm: string): boolean {
  const permissions = usePermissions();
  return permissions.includes(perm) || permissions.includes('*:*:*');
}

import * as React from 'react';

import { useUser } from './auth';

/**
 * 角色枚举：与后端 User.role 字段对齐
 * - ADMIN：管理员，可执行增删改
 * - USER：普通用户，只读
 */
export enum ROLES {
  ADMIN = 'ADMIN',
  USER = 'USER',
}

type RoleTypes = keyof typeof ROLES;

/**
 * 鉴权 hook：返回当前用户角色 + checkAccess 方法
 * checkAccess({ allowedRoles }) 判断当前用户是否在允许的角色列表内
 */
export const useAuthorization = () => {
  const user = useUser();

  if (!user.data) {
    throw Error('User does not exist!');
  }

  const checkAccess = React.useCallback(
    ({ allowedRoles }: { allowedRoles: RoleTypes[] }) => {
      if (allowedRoles && allowedRoles.length > 0 && user.data) {
        return allowedRoles?.includes(user.data.role);
      }
      return true;
    },
    [user.data],
  );

  return { checkAccess, role: user.data.role };
};

type AuthorizationProps = {
  forbiddenFallback?: React.ReactNode;
  children: React.ReactNode;
} & (
  | {
      allowedRoles: RoleTypes[];
      policyCheck?: never;
    }
  | {
      allowedRoles?: never;
      policyCheck: boolean;
    }
);

/**
 * RBAC 守卫组件：根据 allowedRoles 控制子组件可见性
 * 不满足条件时渲染 forbiddenFallback（默认 null）
 *
 * @example
 * <Authorization allowedRoles={[ROLES.ADMIN]}>
 *   <Button>仅管理员可见</Button>
 * </Authorization>
 */
export const Authorization = ({
  policyCheck,
  allowedRoles,
  forbiddenFallback = null,
  children,
}: AuthorizationProps) => {
  const { checkAccess } = useAuthorization();

  let canAccess = false;

  if (allowedRoles) {
    canAccess = checkAccess({ allowedRoles });
  }

  if (typeof policyCheck !== 'undefined') {
    canAccess = policyCheck;
  }

  return <>{canAccess ? children : forbiddenFallback}</>;
};

// 13.2 新增：权限级 RBAC（与角色级 Authorization 并存）
export { usePermissions, useHasPermission } from './use-permissions';
export { HasPermission } from './has-permission';

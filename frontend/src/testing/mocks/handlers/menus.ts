// src/testing/mocks/handlers/menus.ts
import { http } from 'msw';

import { env } from '@/config/env';

import { networkDelay, requireAuth, successResponse } from '../utils';

// 种子菜单数据（参考若依 RuoYi-Vue3 的菜单结构）
// 后端 /getRouters 只负责管理域菜单(管理员 CRUD 工作区,含基金管理);
// 资产域菜单为前端静态定义(features/menu/asset-menus.ts),不经此接口下发
const adminMenus = [
  {
    id: 1,
    parentId: 0,
    name: '系统管理',
    path: '/app/system',
    component: '',
    perms: '',
    menuType: 'M',
    visible: true,
    icon: 'settings',
    children: [
      {
        id: 100,
        parentId: 1,
        name: '用户管理',
        path: '/app/system/users',
        component: 'system/users',
        perms: 'system:user:list',
        menuType: 'C',
        visible: true,
        icon: 'users',
      },
    ],
  },
  {
    id: 2,
    parentId: 0,
    name: '资产管理',
    path: '/app/asset',
    component: '',
    perms: '',
    menuType: 'M',
    visible: true,
    icon: 'database',
    children: [
      {
        id: 200,
        parentId: 2,
        name: '基金管理',
        path: '/app/asset/funds',
        component: 'asset/funds',
        perms: 'asset:funds:list',
        menuType: 'C',
        visible: true,
        icon: 'database',
      },
    ],
  },
];

// 收集管理域菜单的全部权限标识,模拟后端 sys_role_menu 关联查询的授权判定:
// 角色被授予的 permissions 命中任一菜单 perms(或超管通配)即下发整棵管理菜单树
const collectPerms = (items: typeof adminMenus): string[] =>
  items
    .flatMap((menu) => [
      menu.perms,
      ...(menu.children ?? []).map((c) => c.perms),
    ])
    .filter(Boolean);
const managementPerms = collectPerms(adminMenus);

export const menusHandlers = [
  // GET /getRouters — 返回当前用户可见的菜单树
  //   后端类比：查 sys_menu + sys_role_menu 关联表，按角色过滤。
  //   无管理权限的普通角色返回空数组(侧边栏只剩资产 tab 的静态菜单)
  http.get(`${env.API_URL}/getRouters`, async ({ request, cookies }) => {
    await networkDelay();
    const { user } = requireAuth(cookies, request);
    // requireAuth 已校验登录态，此处 user 非空
    const hasManagementAccess =
      user!.role === 'ADMIN' ||
      (user!.permissions as string[]).some((p) => managementPerms.includes(p));
    return successResponse(hasManagementAccess ? adminMenus : []);
  }),
];

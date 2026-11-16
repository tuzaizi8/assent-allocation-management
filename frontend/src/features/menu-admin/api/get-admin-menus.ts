// src/features/menu-admin/api/get-admin-menus.ts
// 菜单管理页 CRUD(注意:与 features/menu(侧边栏 /getRouters 消费)是两个域)
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { z } from 'zod';

import { api } from '@/lib/api-client';

// ===== 类型 =====

/** 后端 sys_menu 行(管理页全量列表,含 F 按钮与隐藏项;后端 CamelCaseUtil 已转驼峰) */
export type SystemMenu = {
  menuId: number;
  menuName: string;
  parentId: number;
  orderNum: number | null;
  path: string | null;
  component: string | null;
  perms: string | null;
  menuType: 'M' | 'C' | 'F';
  icon: string | null;
  visible: '0' | '1' | null;
  status: '0' | '1' | null;
  createTime: string | null;
};

// ===== 查询 =====

export const getAdminMenus = () =>
  api
    .get('/system/menu/list')
    // 拦截器运行时已解包 body.data;类型签名仍是 AxiosResponse,需双重转换(同 users)
    .then((res) => res as unknown as SystemMenu[]);

/**
 * @param enabled 是否发起请求(默认 true)。
 * 菜单管理页始终启用;角色页的勾选树只在编辑弹窗打开时才拉——
 * "只读角色管理员"(有 system:role:list 无 system:menu:list)进列表页
 * 不触发请求,不会被 403 toast 打扰(权限最小化下的体验修正,2026-08-23)
 */
export const useAdminMenus = (enabled: boolean = true) =>
  useQuery({
    queryKey: ['admin-menus'],
    queryFn: getAdminMenus,
    enabled,
  });

// ===== 表单 =====

/**
 * 菜单表单校验:与后端 MenuService 同款规则(前端提前拦,省一次 601 往返)
 * - C 菜单必须有路由地址(菜单点击 404 防护)
 * - F 按钮必须有权限标识(无 perms 的按钮是死数据)
 */
export const menuFormSchema = z
  .object({
    menuId: z.number().optional(), // 编辑时携带
    parentId: z.coerce.number().int().min(0),
    menuType: z.enum(['M', 'C', 'F']),
    menuName: z.string().min(1, '必填').max(50, '最多 50 字'),
    orderNum: z.coerce.number().int().min(0),
    path: z.string().max(200, '最多 200 字').optional().or(z.literal('')),
    component: z.string().max(255, '最多 255 字').optional().or(z.literal('')),
    perms: z.string().max(100, '最多 100 字').optional().or(z.literal('')),
    icon: z.string().max(100, '最多 100 字').optional().or(z.literal('')),
    visible: z.enum(['0', '1']),
    status: z.enum(['0', '1']),
  })
  .superRefine((val, ctx) => {
    if (val.menuType === 'C' && !val.path) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['path'],
        message: '菜单类型必须填写路由地址',
      });
    }
    if (val.menuType === 'F' && !val.perms) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['perms'],
        message: '按钮类型必须填写权限标识',
      });
    }
  });
export type MenuFormInput = z.infer<typeof menuFormSchema>;

// ===== 变更 =====

export const useAddMenu = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: MenuFormInput) => api.post('/system/menu', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-menus'] });
    },
  });
};

export const useEditMenu = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: MenuFormInput) => api.put('/system/menu', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-menus'] });
    },
  });
};

export const useDeleteMenu = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (menuId: number) => api.delete(`/system/menu/${menuId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-menus'] });
    },
  });
};

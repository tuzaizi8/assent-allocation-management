// src/features/roles/api/get-roles.ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { z } from 'zod';

import { api } from '@/lib/api-client';
import { mapPage, PageResponse } from '@/lib/pagination';

// ===== 类型 =====

/** 后端 sys_role 行(分页 rows 元素,后端 to_camel 已转驼峰) */
export type SystemRole = {
  roleId: number;
  roleName: string;
  roleKey: string;
  roleSort: number;
  status: string | null;
  createTime: string | null;
  remark: string | null;
};

/** 角色详情(含绑定菜单ID,编辑回显勾选用) */
export type RoleDetail = SystemRole & {
  menuIds: number[];
};

// ===== 查询 =====

export const getRoles = (params: {
  pageNum: number;
  pageSize: number;
  roleName?: string;
}) =>
  api
    .get('/system/role/list', { params })
    .then((res) =>
      mapPage<SystemRole>(res as unknown as PageResponse<SystemRole>),
    );

/** 列表查询(空 roleName = 全量——后端动态 SQL 判空跳过) */
export const useRoles = (
  pageNum: number,
  pageSize: number,
  roleName?: string,
) =>
  useQuery({
    queryKey: ['roles', pageNum, pageSize, roleName],
    queryFn: () => getRoles({ pageNum, pageSize, roleName }),
  });

/**
 * 用户弹窗角色勾选用:全量角色(复用分页接口大页拉取,不新建独立端点——
 * 对齐 02-角色管理页"当前一个消费方不值得加端点"的既有取舍)。
 * 消费方(users.tsx 表单组件)仅在弹窗打开时挂载 = 天然惰性请求:
 * 无 system:role:list 权限的账号进用户列表页不触发,不被 403 toast 打扰
 * (同 useAdminMenus 的 enabled 修正,2026-08-23)。
 */
export const useRoleOptions = () =>
  useQuery({
    queryKey: ['role-options'],
    queryFn: () => getRoles({ pageNum: 1, pageSize: 100 }),
  });

export const useRole = (roleId: number | null) =>
  useQuery({
    queryKey: ['role', roleId],
    queryFn: () =>
      api
        .get(`/system/role/${roleId}`)
        .then((res) => res as unknown as RoleDetail),
    enabled: roleId != null,
  });

// ===== 表单 =====

/** 角色基础字段(菜单勾选 menuIds 由页面 state 管理,不进 zod 表单) */
export const roleFormSchema = z.object({
  roleId: z.number().optional(), // 编辑时携带
  roleName: z.string().min(1, '必填').max(30, '最多 30 字'),
  roleKey: z
    .string()
    .min(1, '必填')
    .max(100, '最多 100 字')
    .regex(/^[a-zA-Z_][a-zA-Z0-9_]*$/, '仅限字母/数字/下划线,字母开头'),
  roleSort: z.coerce.number().int().min(0),
  status: z.enum(['0', '1']),
  remark: z.string().max(500, '最多 500 字').optional().or(z.literal('')),
});
export type RoleFormInput = z.infer<typeof roleFormSchema>;

// ===== 变更 =====

export const useAddRole = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: RoleFormInput & { menuIds: number[] }) =>
      api.post('/system/role', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['roles'] });
    },
  });
};

export const useEditRole = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: RoleFormInput & { menuIds: number[] }) =>
      api.put('/system/role', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['roles'] });
      queryClient.invalidateQueries({ queryKey: ['role'] });
    },
  });
};

export const useDeleteRole = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (roleId: number) => api.delete(`/system/role/${roleId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['roles'] });
    },
  });
};

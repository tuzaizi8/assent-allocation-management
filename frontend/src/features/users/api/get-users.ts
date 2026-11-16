// src/features/users/api/get-users.ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { z } from 'zod';

import { api } from '@/lib/api-client';
import { mapPage, PageResponse } from '@/lib/pagination';

// ===== 类型 =====

/** 后端 sys_user 行(分页 rows 元素,后端 to_camel 已转驼峰) */
export type SystemUser = {
  userId: number;
  userName: string;
  nickName: string;
  email: string | null;
  phonenumber: string | null;
  status: string | null;
  createTime: string | null;
};

// ❌ 删除原手写的 UserPageResponse 接口,由 PageResponse<SystemUser> 泛型替代

/** 用户详情(含 roleIds,编辑弹窗勾选回显用——对齐 roles 的 RoleDetail.menuIds 模式) */
export type UserDetail = SystemUser & { roleIds: number[] };

// ===== 查询(改为 mapPage 映射) =====

export const getUsers = (params: {
  pageNum: number;
  pageSize: number;
  userName?: string;
}) =>
  api
    .get('/system/user/list', { params })
    // 注意:必须 as unknown as——拦截器运行时已解包(平铺对象),但 api.get 的
    // 类型签名仍是 AxiosResponse(缺 rows 等字段,直接 as 会报 TS2352 不重叠)
    .then((res) =>
      mapPage<SystemUser>(res as unknown as PageResponse<SystemUser>),
    );

/** 列表查询(空 userName = 全量——后端动态 SQL 判空跳过) */
export const useUsers = (
  pageNum: number,
  pageSize: number,
  userName?: string,
) =>
  useQuery({
    queryKey: ['users', pageNum, pageSize, userName],
    queryFn: () => getUsers({ pageNum, pageSize, userName }),
  });

/** 用户详情(含 roleIds 回显;编辑弹窗挂载时按需请求) */
export const useUserDetail = (userId: number | null) =>
  useQuery({
    queryKey: ['user', userId],
    queryFn: () =>
      api
        .get(`/system/user/${userId}`)
        .then((res) => res as unknown as UserDetail),
    enabled: userId != null,
  });

// ===== 变更 =====

/** 新增用户表单校验(对齐后端 UserAddModel 字段,camelCase 别名自动映射) */
export const addUserSchema = z.object({
  userName: z.string().min(1, '必填').max(30, '最多 30 字'),
  nickName: z.string().min(1, '必填').max(30, '最多 30 字'),
  password: z.string().min(5, '至少 5 位').max(100, '最多 100 字'),
  email: z.string().email('邮箱格式不正确').or(z.literal('')).optional(),
  phonenumber: z.string().max(11, '最多 11 位').or(z.literal('')).optional(),
  status: z.enum(['0', '1']).default('0'),
});
export type AddUserInput = z.infer<typeof addUserSchema>;

// roleIds 随表单合并提交(勾选组是受控组件,不进 zod schema——对齐 roles 页 menuIds 模式)
export const useAddUser = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: AddUserInput & { roleIds: number[] }) =>
      api.post('/system/user', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] }); // 失效列表缓存重拉
    },
  });
};

/** 编辑用户表单校验(对齐后端 UserEditModel;password 选填=重置密码,留空不修改) */
export const editUserSchema = z.object({
  userId: z.number(),
  userName: z.string().min(1, '必填').max(30, '最多 30 字'),
  nickName: z.string().min(1, '必填').max(30, '最多 30 字'),
  password: z
    .string()
    .min(5, '至少 5 位')
    .max(100, '最多 100 字')
    .or(z.literal(''))
    .optional(),
  email: z.string().email('邮箱格式不正确').or(z.literal('')).optional(),
  phonenumber: z.string().max(11, '最多 11 位').or(z.literal('')).optional(),
  status: z.enum(['0', '1']),
});
export type EditUserInput = z.infer<typeof editUserSchema>;

// roleIds 随表单合并提交;后端为全量替换语义(提交什么,绑定就是什么)
export const useEditUser = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: EditUserInput & { roleIds: number[] }) =>
      api.put('/system/user', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
      queryClient.invalidateQueries({ queryKey: ['user'] }); // 失效详情缓存(roleIds 已变)
    },
  });
};

export const useDeleteUser = () => {
  const queryClient = useQueryClient();
  return useMutation({
    // 后端契约:DELETE /system/user/{user_ids}(路径参数,支持逗号分隔批量)
    mutationFn: (userIds: number | number[]) => {
      const ids = Array.isArray(userIds) ? userIds.join(',') : userIds;
      return api.delete(`/system/user/${ids}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
    },
  });
};

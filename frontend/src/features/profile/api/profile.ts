// 个人资料数据层:GET/PUT /auth/profile、PUT /auth/password(仅需登录,无额外权限点)。
// 邮箱是登录账号(注册时 user_name = email),本轮只读;可改字段只有昵称与手机号。
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { toast } from 'sonner';
import { z } from 'zod';

import { paths } from '@/config/paths';
import { api } from '@/lib/api-client';

export type Profile = {
  /** 登录账号(注册时即邮箱,只读) */
  userName: string;
  /** 用户昵称(可改) */
  nickName: string | null;
  /** 邮箱(登录账号,只读) */
  email: string | null;
  /** 手机号码(可改,可空) */
  phonenumber: string | null;
  role: 'ADMIN' | 'USER';
  createTime: string | null;
  loginDate: string | null;
  pwdUpdateDate: string | null;
};

/** 昵称必填(库列非空,30 字上限与 sys_user.nick_name 对齐);手机号沿用用户管理的 max(11) 口径 */
export const profileSchema = z.object({
  nickName: z.string().min(1, '必填').max(30, '最多 30 字'),
  phonenumber: z.string().max(11, '最多 11 位').or(z.literal('')).optional(),
});
export type ProfileInput = z.infer<typeof profileSchema>;

/**
 * 修改密码:两次新密码一致 + 新旧不得相同。
 * 与后端 PasswordUpdateModel 同口径——前端拦是为了即时反馈,后端那次才是真正的防线。
 */
export const passwordSchema = z
  .object({
    oldPassword: z.string().min(1, '必填'),
    newPassword: z.string().min(5, '至少 5 位'),
    confirmPassword: z.string().min(1, '必填'),
  })
  .refine((values) => values.newPassword === values.confirmPassword, {
    message: '两次输入的新密码不一致',
    path: ['confirmPassword'],
  })
  .refine((values) => values.newPassword !== values.oldPassword, {
    message: '新密码不能与原密码相同',
    path: ['newPassword'],
  });
export type PasswordInput = z.infer<typeof passwordSchema>;

export const useProfile = () =>
  useQuery<Profile>({
    queryKey: ['profile'],
    queryFn: async () => (await api.get('/auth/profile')) as unknown as Profile,
    staleTime: 5 * 60 * 1000,
  });

export const useUpdateProfile = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: ProfileInput) =>
      api.put('/auth/profile', data) as unknown as Promise<Profile>,
    onSuccess: () => {
      // 两份缓存都要刷:本页左卡读 ['profile'],侧边栏底部昵称读 react-query-auth 的 ['authenticated-user']
      queryClient.invalidateQueries({ queryKey: ['profile'] });
      queryClient.invalidateQueries({ queryKey: ['authenticated-user'] });
      // 该响应带 data,而全局成功 toast 只在"无 data 的信封"上读 msg → 这里自己弹一次
      toast.success('资料已更新');
    },
  });
};

export const useUpdatePassword = () => {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  return useMutation({
    // 只发后端模型里有的字段:confirmPassword 纯前端校验,发过去也会被忽略,不如不发
    mutationFn: (data: PasswordInput) =>
      api.put('/auth/password', {
        oldPassword: data.oldPassword,
        newPassword: data.newPassword,
      }),
    onSuccess: () => {
      // 后端已作废该会话(Redis),这里只需清本地登录态并回登录页:
      // 不再调 /auth/logout——那是注定 401 的请求。成功提示由后端 msg 走全局 toast。
      localStorage.removeItem('app_token');
      queryClient.clear();
      navigate(paths.auth.login.getHref());
    },
  });
};

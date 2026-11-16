// src/lib/auth.tsx
import * as React from 'react';
import { configureAuth } from 'react-query-auth';
import { Navigate, useLocation } from 'react-router';
import { toast } from 'sonner';
import { z } from 'zod';

import { paths } from '@/config/paths';
import { AuthResponse, RegisterInput, User } from '@/types/api';

import { api } from './api-client';

// ===== 1. 鉴权 fetcher：与后端端点一一对应 =====
// 注意：api-client 响应拦截器已解包 FastAPI 统一响应体的 body.data，
// 所以 api.get('/auth/me') 直接返回 data 字段（未登录时为 null），
// 不需要再访问 .data（否则会对 null 取属性，抛 TypeError）
const getUser = async (): Promise<User | null> => {
  // 无 token：未登录是正常状态，直接返回 null，不发注定 401 的请求
  if (!localStorage.getItem('app_token')) {
    return null;
  }
  try {
    return (await api.get('/auth/me')) as User;
  } catch (error) {
    // 401 = 未登录/会话失效，属于正常态：清掉失效 token，返回 null
    // 业务 401（HTTP 200）reject 的是 body（code 为 number）；
    // HTTP 401 reject 的是 AxiosError（code 为字符串），需取 response.data.code
    const e = error as {
      code?: number | string;
      response?: { data?: { code?: number; msg?: string } };
    };
    const code = typeof e?.code === 'number' ? e.code : e?.response?.data?.code;
    if (code === 401) {
      localStorage.removeItem('app_token');
      // "带着 token 却 401"=会话已过期(被踢),须给出提示——否则用户只会看到
      // "忽然跳回登录页"而无任何解释(拦截器的 401 提示被本函数 catch 吞掉,不会触发)
      toast.error('登录已过期', {
        description: e?.response?.data?.msg || '请重新登录',
      });
      return null;
    }
    throw error;
  }
};

const logout = (): Promise<void> => {
  localStorage.removeItem('app_token');
  return api.post('/auth/logout');
};

export const loginInputSchema = z.object({
  email: z.string().min(1, 'Required').email('Invalid email'),
  password: z.string().min(5, 'Required'),
});
export type LoginInput = z.infer<typeof loginInputSchema>;

const loginWithEmailAndPassword = (data: LoginInput): Promise<AuthResponse> => {
  return api.post('/auth/login', data);
};

const registerWithEmailAndPassword = (
  data: RegisterInput,
): Promise<AuthResponse> => {
  return api.post('/auth/register', data);
};

export const registerInputSchema = z.object({
  email: z.string().min(1, 'Required').email('Invalid email'),
  password: z.string().min(5, 'Required'),
  nickName: z.string().min(1, 'Required').max(30, '昵称最多 30 个字符'),
});

// ===== 2. authConfig：把 fetcher 适配成 configureAuth 的契约 =====
const authConfig = {
  userFn: getUser, // 启动时调用，返回当前用户或抛错
  loginFn: async (data: LoginInput) => {
    const response = await loginWithEmailAndPassword(data);
    // 方案 A:后端返回 {jwt, user},把 jwt 存起来供拦截器读取
    localStorage.setItem('app_token', response.jwt);
    return response.user; // 后端返回 { jwt, user }，这里只取 user
  },
  registerFn: async (data: RegisterInput) => {
    const response = await registerWithEmailAndPassword(data);
    // 注册即登录：与 loginFn 对齐，存 token 供拦截器读取
    localStorage.setItem('app_token', response.jwt);
    return response.user;
  },
  logoutFn: logout,
};

// ===== 3. 导出四个 hook + AuthLoader =====
export const { useUser, useLogin, useLogout, useRegister, AuthLoader } =
  configureAuth(authConfig);

// ===== 4. ProtectedRoute:未登录重定向到登录页(带 redirectTo 回跳) =====
export const ProtectedRoute = ({ children }: { children: React.ReactNode }) => {
  const user = useUser();
  const location = useLocation();

  // 未登录:重定向到 /auth/login?redirectTo=当前路径
  if (!user.data) {
    return (
      <Navigate to={paths.auth.login.getHref(location.pathname)} replace />
    );
  }

  return children;
};

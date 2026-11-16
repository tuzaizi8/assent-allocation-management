import { delay, HttpResponse } from 'msw';
import type { StrictRequest } from 'msw';

import { db } from './db';

// ① mock trace-id(模拟 FastAPI TraceASGIMiddleware)
export const mockTraceId = () => 'a'.repeat(32);

// ② FastAPI 统一响应体工厂 —— 成功
export const successResponse = (data: unknown) =>
  new HttpResponse(
    JSON.stringify({
      code: 200,
      msg: 'success',
      data,
      success: true,
      time: new Date().toISOString(),
    }),
    {
      headers: {
        'Content-Type': 'application/json',
        'trace-id': mockTraceId(),
      },
    },
  );

// ③ FastAPI 统一响应体工厂 —— 失败
export const errorResponse = (code: number, msg: string, httpStatus = 200) =>
  new HttpResponse(
    JSON.stringify({
      code,
      msg,
      data: null,
      success: false,
      time: new Date().toISOString(),
    }),
    {
      status: httpStatus,
      headers: {
        'Content-Type': 'application/json',
        'trace-id': mockTraceId(),
      },
    },
  );

// ④ 网络延迟(测试时固定 200ms,开发时随机 300-1000ms)
export const networkDelay = () => {
  const delayTime = import.meta.env.TEST
    ? 200
    : Math.floor(Math.random() * 700) + 300;
  return delay(delayTime);
};

// ⑤ base64 编码/解码（兼容 Node 和浏览器）
//    后端类比：JWT 的 sign/verify，这里简化为 base64
export const encode = (obj: any) => {
  const btoa =
    typeof window === 'undefined'
      ? (str: string) => Buffer.from(str, 'binary').toString('base64')
      : window.btoa;
  return btoa(JSON.stringify(obj));
};

export const decode = (str: string) => {
  const atob =
    typeof window === 'undefined'
      ? (str: string) => Buffer.from(str, 'base64').toString('binary')
      : window.atob;
  return JSON.parse(atob(str));
};

// ⑥ 简单 hash 函数（模拟密码加密）
//    后端类比：bcrypt.hash，这里用 djb2 算法简化
export const hash = (str: string) => {
  let hash = 5381,
    i = str.length;
  while (i) {
    hash = (hash * 33) ^ str.charCodeAt(--i);
  }
  return String(hash >>> 0);
};

// ⑦ Cookie 名称
const AUTH_COOKIE = 'react_scaffold_token';

export const AUTH_COOKIE_NAME = AUTH_COOKIE;

// ⑧ 清除密码等敏感字段
//    后端类比：UserResponse DTO，不返回 password
export const sanitizeUser = <T extends Record<string, any>>(user: T): T => {
  const result = { ...user };
  delete result.password;
  delete result.iat;
  return result;
};

// ⑨ 登录验证：查 db + 校验密码 + 生成 token
//    后端类比：POST /auth/login 的核心逻辑
export function authenticate({
  email,
  password,
}: {
  email: string;
  password: string;
}) {
  const user = db.user.findFirst({
    where: {
      email: { equals: email },
    },
  });

  if (user?.password === hash(password)) {
    const sanitizedUser = sanitizeUser(user);
    const encodedToken = encode(sanitizedUser);
    return { user: sanitizedUser, jwt: encodedToken };
  }

  throw new Error('邮箱或密码错误');
}

// ⑩ 从 user 生成 token（编码 sanitized user，不含 password）
//    后端类比：JWT sign(payload, secret)
export const generateToken = (user: unknown) => {
  return encode(user);
};

// ⑪ 鉴权检查：解 token → 查 db → 返回真实 user
//    后端类比：JWT verify + 查用户
export function requireAuth(
  cookies: Record<string, string>,
  request?: StrictRequest<any>,
) {
  try {
    // 双通道:优先 Authorization Bearer 头(镜像真实后端方案 A),回退 Cookie(mock 登录闭环)
    let encodedToken = cookies[AUTH_COOKIE_NAME];
    const authHeader = request?.headers.get('Authorization');
    if (authHeader?.startsWith('Bearer ')) {
      encodedToken = authHeader.slice(7);
    }
    if (!encodedToken) {
      return { error: 'Unauthorized', user: null };
    }

    // 解 token 拿 user 信息
    const decodedToken = decode(encodedToken) as { id: string };

    // 从 db 查询真实用户
    const user = db.user.findFirst({
      where: {
        id: { equals: decodedToken.id },
      },
    });

    if (!user) {
      return { error: 'Unauthorized', user: null };
    }

    return { user: sanitizeUser(user) };
  } catch (err: any) {
    return { error: 'Unauthorized', user: null };
  }
}

// ⑫ 管理员权限检查
export function requireAdmin(user: { role: string } | null) {
  if (user?.role !== 'ADMIN') {
    throw new Error('Unauthorized: admin role required');
  }
}

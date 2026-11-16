import { HttpResponse, http } from 'msw';

import { env } from '@/config/env';

import { db, persistDb } from '../db';
import {
  AUTH_COOKIE_NAME,
  authenticate,
  errorResponse,
  generateToken,
  hash,
  networkDelay,
  requireAuth,
  sanitizeUser,
  successResponse,
} from '../utils';

type LoginBody = {
  email: string;
  password: string;
};

type RegisterBody = {
  email: string;
  password: string;
  firstName: string;
  lastName: string;
};

// ① 种子用户：首次调用时写入 db（替代原 mockUsers 硬编码数组）
const seedUsers = () => {
  const existing = db.user.getAll();
  if (existing.length === 0) {
    db.user.create({
      id: 'mock-user-id',
      email: 'test@example.com',
      password: hash('password123'),
      firstName: 'Test',
      lastName: 'User',
      role: 'ADMIN',
      permissions: ['*:*:*'], // 新增：超级管理员通配符
      teamId: 'mock-team-id',
      bio: 'Test user',
      createdAt: Date.now(),
    });
  }
};

export const authHandlers = [
  // ② POST /auth/login —— 登录，返回 {user, jwt} 并 Set-Cookie
  //    升级：用 authenticate() 查 db + 校验密码
  http.post(`${env.API_URL}/auth/login`, async ({ request }) => {
    await networkDelay();

    try {
      seedUsers();
      const credentials = (await request.json()) as LoginBody;

      // 用 authenticate 查 db + 校验密码
      const { user, jwt } = authenticate({
        email: credentials.email,
        password: credentials.password,
      });

      return new HttpResponse(
        JSON.stringify({
          code: 200,
          msg: 'success',
          data: { user, jwt },
          success: true,
          time: new Date().toISOString(),
        }),
        {
          headers: {
            'Content-Type': 'application/json',
            'trace-id': 'a'.repeat(32),
            'Set-Cookie': `${AUTH_COOKIE_NAME}=${jwt}; Path=/;`,
          },
        },
      );
    } catch (error: any) {
      return errorResponse(401, error?.message || '邮箱或密码错误', 401);
    }
  }),

  // ③ POST /auth/register —— 注册，写入 db
  //    升级：用 db.user.create 写入，后续可登录
  http.post(`${env.API_URL}/auth/register`, async ({ request }) => {
    await networkDelay();

    try {
      seedUsers();
      const body = (await request.json()) as RegisterBody;

      const existingUser = db.user.findFirst({
        where: { email: { equals: body.email } },
      });
      if (existingUser) {
        return errorResponse(400, '该邮箱已注册');
      }

      // 写入 db（密码用 hash 加密）
      const newUser = db.user.create({
        email: body.email,
        password: hash(body.password),
        firstName: body.firstName,
        lastName: body.lastName,
        role: 'USER',
        permissions: ['discussions:list'], // 新增：普通用户只能看讨论区
        teamId: 'mock-team-id',
        bio: '',
        createdAt: Date.now(),
      });

      await persistDb('user');

      const sanitizedUser = sanitizeUser(newUser);
      const token = generateToken(sanitizedUser);

      return new HttpResponse(
        JSON.stringify({
          code: 200,
          msg: 'success',
          data: { user: sanitizedUser, jwt: token },
          success: true,
          time: new Date().toISOString(),
        }),
        {
          headers: {
            'Content-Type': 'application/json',
            'trace-id': 'a'.repeat(32),
            'Set-Cookie': `${AUTH_COOKIE_NAME}=${token}; Path=/;`,
          },
        },
      );
    } catch (error: any) {
      return errorResponse(500, error?.message || 'Server Error', 500);
    }
  }),

  // ④ POST /auth/logout —— 登出，清除 Cookie
  http.post(`${env.API_URL}/auth/logout`, async () => {
    await networkDelay();
    return new HttpResponse(
      JSON.stringify({
        code: 200,
        msg: 'success',
        data: null,
        success: true,
        time: new Date().toISOString(),
      }),
      {
        headers: {
          'Content-Type': 'application/json',
          'trace-id': 'a'.repeat(32),
          'Set-Cookie': `${AUTH_COOKIE_NAME}=; Path=/; Max-Age=0;`,
        },
      },
    );
  }),

  // ⑤ GET /auth/me —— 返回当前用户（从 db 查询真实用户）
  //    升级：requireAuth 现在会解 token → 查 db → 返回真实 user
  http.get(`${env.API_URL}/auth/me`, async ({ cookies }) => {
    await networkDelay();

    try {
      seedUsers();
      const { user } = requireAuth(cookies);
      return successResponse(user);
    } catch (error: any) {
      return errorResponse(500, error?.message || 'Server Error', 500);
    }
  }),
];

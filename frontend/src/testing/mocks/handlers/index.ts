import { http } from 'msw';

import { env } from '@/config/env';

import { networkDelay, successResponse } from '../utils';

// 已实现接口的 handler 组改为 server.ts(测试环境)直接导入,此处不再引用
// import { authHandlers } from './auth';
// import { dictsHandlers } from './dicts';
// import { menusHandlers } from './menus';

export const handlers = [
  // ✅ 后端已实现(2026-08-21/22)→ 注释,请求直发 8000(七节规范 3:禁止双轨并存)
  // 需要纯 mock 演示时取消注释即可恢复
  // ...authHandlers,      // /auth/login|me|logout|register
  // ...menusHandlers,     // /getRouters
  // ...dictsHandlers,     // /dict/data/type/{dict_type}
  http.get(`${env.API_URL}/healthcheck`, async () => {
    await networkDelay();
    return successResponse({ ok: true });
  }),
];

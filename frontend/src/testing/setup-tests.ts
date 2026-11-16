import '@testing-library/jest-dom/vitest';

import { initializeDb, resetDb } from '@/testing/mocks/db';
import { server } from '@/testing/mocks/server';

// ① 不 mock zustand：zustand 在 jsdom 下完全可用。
//    vi.mock('zustand') 会让 create 返回 undefined，导致 store
//    (useTheme 等) 变成 undefined → AppProvider 崩溃。
//    如需避免 store 状态在测试间串味，在 afterEach 中手动 setState 重置。

// ② MSW server 生命周期：启动 → 拦截所有请求
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterAll(() => server.close());

beforeEach(async () => {
  // ③ jsdom 缺失的 ResizeObserver polyfill（Radix UI 需要）
  const ResizeObserverMock = vi.fn(() => ({
    observe: vi.fn(),
    unobserve: vi.fn(),
    disconnect: vi.fn(),
  }));
  vi.stubGlobal('ResizeObserver', ResizeObserverMock);

  // ④ jsdom 没有原生 btoa/atob，用 Node Buffer 兜底
  window.btoa = (str: string) => Buffer.from(str, 'binary').toString('base64');
  window.atob = (str: string) => Buffer.from(str, 'base64').toString('binary');

  // ⑤ 每个 test 前：从 localStorage 重新装载 mock DB（await 确保完成）
  await initializeDb();
});

afterEach(() => {
  // ⑥ 每个 test 后：重置 MSW handler + 清空 mock DB
  server.resetHandlers();
  resetDb();
});

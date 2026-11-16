// 仅在开发环境且开启 mock 时启动 MSW（VITE_APP_ENABLE_API_MOCKING）
// 生产环境（yarn build）不会引入此文件
import { env } from '@/config/env';

export async function startMockWorker() {
  if (import.meta.env.DEV && env.ENABLE_API_MOCKING) {
    const { worker } = await import('./browser');
    await worker.start({
      onUnhandledRequest: 'bypass', // 未 mock 的请求直接放行
    });
    // 初始化种子数据(从 mocked-db.json 加载到 mswjs/data 内存)
    const { initializeDb } = await import('./db');
    await initializeDb();
    console.log('[MSW] Mock worker started + DB initialized');
  } else if (import.meta.env.DEV) {
    // 直连真实后端联调时，清理上次会话注册的 MSW Service Worker，
    // 避免残留的 worker 拦截请求（现象：登录偶发 401、刷新后登录态丢失）
    const registrations = await navigator.serviceWorker.getRegistrations();
    await Promise.all(
      registrations
        .filter((r) => r.active?.scriptURL.includes('mockServiceWorker'))
        .map((r) => r.unregister()),
    );
  }
}

import { defineConfig, devices } from '@playwright/test';

const PORT = 3000;

export default defineConfig({
  // ① 测试目录:E2E 与 Vitest 隔离
  testDir: './e2e',
  // ② 并行测试
  fullyParallel: true,
  // ③ CI 禁止 test.only
  forbidOnly: !!process.env.CI,
  // ④ CI 重试 2 次,本地不重试
  retries: process.env.CI ? 2 : 0,
  // ⑤ CI 单线程,本地多线程
  workers: process.env.CI ? 1 : undefined,
  // ⑥ HTML 报告
  reporter: 'html',
  // ⑦ 全局设置
  use: {
    trace: 'on-first-retry',
  },
  // ⑧ 项目配置:setup + chromium
  projects: [
    // setup 项目:跑 auth.setup.ts 预置登录态
    { name: 'setup', testMatch: /.*\.setup\.ts/ },
    {
      name: 'chromium',
      testMatch: /.*\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        // 复用 setup 保存的登录态
        storageState: 'e2e/.auth/user.json',
      },
      dependencies: ['setup'],
    },
  ],
  // ⑨ 自动启动 dev server
  webServer: {
    command: `pnpm dev --port ${PORT}`,
    timeout: 30 * 1000,
    port: PORT,
    reuseExistingServer: !process.env.CI,
  },
});

/// <reference types="vitest" />
/// <reference types="vite/client" />

import path from 'path';

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import viteTsconfigPaths from 'vite-tsconfig-paths';

export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss(), viteTsconfigPaths()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
  },
  preview: {
    port: 3000,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/testing/setup-tests.ts',
    // 兜底 env:env.ts 在 import 期做 zod 校验(API_URL 必填),CI/无 .env 环境
    // 没有真实地址——测试走 MSW 拦截,不需要真实 API,给占位即可全量可跑
    env: {
      VITE_APP_API_URL: 'http://msw.local',
      VITE_APP_URL: 'http://localhost:3000',
    },
    exclude: ['**/node_modules/**', '**/e2e/**'],
    coverage: {
      provider: 'v8',
      include: ['src/**'],
    },
  },
});

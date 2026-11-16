// src/testing/mocks/index.ts
import { startMockWorker } from './start';

// 统一入口:语义化命名,新 handler 在此注册
export const enableMocking = async () => {
  return startMockWorker();
};

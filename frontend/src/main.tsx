import * as React from 'react';
import { createRoot } from 'react-dom/client';

import './index.css';
import { App } from './app'; // ← 具名导入
import { enableMocking } from './testing/mocks'; // ← 统一入口

const root = document.getElementById('root');
if (!root) throw new Error('No root element found'); // ← 显式校验

// 先启用 MSW 模拟服务,再挂载 React 树
enableMocking().then(() => {
  createRoot(root).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
});

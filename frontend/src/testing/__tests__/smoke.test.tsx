import { describe, test, expect } from 'vitest';

import { createUser, renderApp, screen } from '@/testing/test-utils';

// ① 最简单的测试组件
function TestPage() {
  return (
    <div>
      <h1>Test Page</h1>
      <p>Hello Test</p>
    </div>
  );
}

describe('smoke test - 验证测试体系', () => {
  // ① 验证 renderApp 默认渲染(自动登录)
  test('renderApp 渲染组件(默认登录用户)', async () => {
    await renderApp(<TestPage />);
    expect(screen.getByText('Hello Test')).toBeInTheDocument();
  });

  // ② 验证 renderApp 匿名访问(user: null)
  test('renderApp 匿名访问', async () => {
    await renderApp(<TestPage />, { user: null });
    expect(screen.getByText('Hello Test')).toBeInTheDocument();
  });

  // ③ 验证 createUser(test-utils 版)生成 + 写入 db + sanitize
  test('createUser 生成 sanitized 用户', async () => {
    const user = await createUser({ role: 'USER' });
    expect(user.id).toBeDefined();
    expect(user.email).toContain('@');
    expect(user.role).toBe('USER');
    expect(user.password).toBeUndefined(); // sanitizeUser 移除了 password
  });
});

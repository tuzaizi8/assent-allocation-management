import { test as setup } from '@playwright/test';

import { createUser } from '../../src/testing/data-generators';

const authFile = 'e2e/.auth/user.json';

setup('authenticate', async ({ page }) => {
  // 用 data-generators 生成随机用户（避免冲突）
  const user = createUser();

  // ① 注册流程
  await page.goto('/auth/register');
  await page.getByLabel('姓').fill(user.lastName);
  await page.getByLabel('名').fill(user.firstName);
  await page.getByLabel('邮箱').fill(user.email);
  await page.getByLabel('密码').fill(user.password);
  await page.getByRole('button', { name: '注册' }).click();

  // 等待注册成功跳转到 /app
  await page.waitForURL('/app', { timeout: 10000 });

  // ② 登出
  //    直接清除浏览器 cookie（page.request 不共享浏览器 cookie，
  //    发到 localhost:3000 不会命中 mock server 的 /auth/logout）
  await page.context().clearCookies();

  // ③ 用 admin 种子用户登录（ADMIN 权限）
  //    注册用户是 USER 角色，RBAC 会隐藏 Create/Delete 按钮
  //    admin 种子用户（test@example.com）是 ADMIN 角色
  await page.goto('/auth/login');
  await page.getByLabel('邮箱').fill('test@example.com');
  await page.getByLabel('密码').fill('password123');
  await page.getByRole('button', { name: '登录' }).click();

  // 等待登录成功跳转
  await page.waitForURL('/app', { timeout: 10000 });

  // ④ 保存 storageState（Cookie 会自动保存）
  await page.context().storageState({ path: authFile });
});

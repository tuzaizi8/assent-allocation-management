import { test, expect } from '@playwright/test';

// 原有 smoke 测试保留
test('smoke - 页面能加载', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /landing/i })).toBeVisible();
});

test('smoke - 路由跳转', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL('/');

  // 访问不存在的页面 → 404
  await page.goto('/nonexistent-page');
  await expect(page.getByText(/404|not found/i)).toBeVisible({
    timeout: 5000,
  });
});

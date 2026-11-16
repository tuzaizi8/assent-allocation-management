import { render as rtlRender, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Cookies from 'js-cookie';
import { RouterProvider, createMemoryRouter } from 'react-router';

import { AppProvider } from '@/app/provider';

import { createUser as generateUser } from './data-generators';
import { db } from './mocks/db';
import { AUTH_COOKIE_NAME, generateToken, sanitizeUser } from './mocks/utils';

// ① 在 mock DB 中创建真实用户记录
//    与 data-generators 的 createUser 区别:这里写入 db,返回 sanitized user
export const createUser = async (userProperties?: any) => {
  const user = generateUser(userProperties) as any;
  await db.user.create(user);
  return sanitizeUser(user);
};

// ② 登录:生成 token 并写入 Cookie(用 js-cookie,更简洁)
export const loginAsUser = async (user: any) => {
  const sanitizedUser = sanitizeUser(user);
  const token = generateToken(sanitizedUser);
  Cookies.set(AUTH_COOKIE_NAME, token, { path: '/' });
  // 方案 A 真实登录态:getUser 无 localStorage.app_token 时短路返回 null(03 文档)
  localStorage.setItem('app_token', token);
  return { user: sanitizedUser, jwt: token };
};

// ③ 等待 loading 消失(统一处理异步渲染)
//    用 waitFor 替代 waitForElementToBeRemoved：后者要求 loading 元素先存在，
//    如果 loading 从未出现(或已消失)会立即抛错；waitFor 断言「没有 loading」为真即可通过。
//    必须按 role=status 判定：Spinner 渲染的是 role="status" + aria-label="Loading"，
//    既无 testid 也无文本节点，只查 testid/文本会漏判、导致断言早于 AuthLoader 就绪。
export const waitForLoadingToFinish = () =>
  waitFor(
    () => {
      expect(
        screen.queryAllByRole('status').length +
          screen.queryAllByTestId(/loading/i).length +
          screen.queryAllByText(/loading/i).length,
      ).toBe(0);
    },
    { timeout: 4000 },
  );

// ④ 用户初始化的三种模式
const initializeUser = async (user: any) => {
  if (typeof user === 'undefined') {
    // 未传 user:默认创建并登录一个新用户
    const newUser = await createUser();
    return loginAsUser(newUser);
  } else if (user) {
    // 传入 user 对象:直接登录
    return loginAsUser(user);
  } else {
    // 显式传 null:匿名访问
    return null;
  }
};

// ⑤ 核心:renderApp
export const renderApp = async (
  ui: any,
  { user, url = '/', path = '/', ...renderOptions }: Record<string, any> = {},
) => {
  // 1. 初始化用户(三种模式)
  const initializedUser = await initializeUser(user);

  // 2. 用 createMemoryRouter 测试路由相关逻辑
  const router = createMemoryRouter(
    [
      {
        path: path,
        element: ui,
      },
    ],
    {
      initialEntries: url ? ['/', url] : ['/'],
      initialIndex: url ? 1 : 0,
    },
  );

  // 3. 渲染:包裹 AppProvider + RouterProvider
  const returnValue = {
    ...rtlRender(ui, {
      wrapper: () => {
        return (
          <AppProvider>
            <RouterProvider router={router} />
          </AppProvider>
        );
      },
      ...renderOptions,
    }),
    user: initializedUser,
  };

  // 4. 等待 loading 消失(AuthLoader 的 spinner)
  await waitForLoadingToFinish();

  return returnValue;
};

// ⑥ 统一导出 Testing Library 的所有工具
export * from '@testing-library/react';
export { userEvent, rtlRender };

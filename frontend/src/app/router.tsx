// src/app/router.tsx
import { QueryClient, useQueryClient } from '@tanstack/react-query';
import { useMemo } from 'react';
import { createBrowserRouter, redirect } from 'react-router';
import { RouterProvider } from 'react-router/dom';

import { AdminLayout } from '@/components/layouts';
import { Spinner } from '@/components/ui/spinner';
import { paths } from '@/config/paths';
import { AppSidebar } from '@/features/menu/components/app-sidebar';
import { ProtectedRoute } from '@/lib/auth';

import { ErrorBoundary as AppRootErrorBoundary } from './routes/app/root';

// convert:路由模块导出 clientLoader/clientAction 时注入 queryClient
// (依赖注入而非 import,便于测试替换)
const convert = (queryClient: QueryClient) => (m: any) => {
  const { clientLoader, clientAction, default: Component, ...rest } = m;
  return {
    ...rest,
    loader: clientLoader?.(queryClient),
    action: clientAction?.(queryClient),
    Component,
  };
};

// /app 父路由的鉴权守卫 loader(数据加载期守卫)
// 必须用 loader 而非 element 里的 ProtectedRoute,因为子路由的 clientLoader
// 会在父路由 element 渲染之前执行,导致未登录时子路由 loader 先发请求报错
// react-query-auth 默认 userKey 是 ['authenticated-user']
// AuthLoader 启动时已调 userFn 把 user(或 null)写入 React Query 缓存
const appRootLoader = (queryClient: QueryClient) => async () => {
  const user = queryClient.getQueryData(['authenticated-user']);
  if (!user) {
    throw redirect(paths.auth.login.getHref(window.location.pathname));
  }
  return null;
};

// 初始水合期间的兜底渲染(消除 react-router 7 "No HydrateFallback element" 警告;
// 纯 CSR 下实际由 provider 的 Suspense/AuthLoader 兜底,此处仅声明路由级 fallback)
const HydrateFallback = () => (
  <div className="animate-in fade-in-0 flex h-screen w-screen items-center justify-center duration-200 motion-reduce:animate-none">
    <Spinner className="text-muted-foreground size-8" />
  </div>
);

export const createAppRouter = (queryClient: QueryClient) =>
  createBrowserRouter([
    {
      path: paths.home.path,
      HydrateFallback,
      lazy: () => import('./routes/landing').then(convert(queryClient)),
    },
    {
      path: paths.auth.register.path,
      HydrateFallback,
      lazy: () => import('./routes/auth/register').then(convert(queryClient)),
    },
    {
      path: paths.auth.login.path,
      HydrateFallback,
      lazy: () => import('./routes/auth/login').then(convert(queryClient)),
    },
    {
      path: paths.app.root.path,
      HydrateFallback,
      loader: appRootLoader(queryClient),
      element: (
        <ProtectedRoute>
          <AdminLayout sidebar={<AppSidebar />} />
        </ProtectedRoute>
      ),
      ErrorBoundary: AppRootErrorBoundary,
      children: [
        {
          path: paths.app.dashboard.path,
          lazy: () =>
            import('./routes/app/dashboard').then(convert(queryClient)),
          handle: { title: '首页' },
        },
        {
          path: paths.app.system.users.path,
          lazy: () => import('./routes/app/users').then(convert(queryClient)),
          handle: { title: '用户管理', parent: '系统管理' },
        },
        {
          path: paths.app.system.menus.path,
          lazy: () => import('./routes/app/menus').then(convert(queryClient)),
          handle: { title: '菜单管理', parent: '系统管理' },
        },
        {
          path: paths.app.system.roles.path,
          lazy: () => import('./routes/app/roles').then(convert(queryClient)),
          handle: { title: '角色管理', parent: '系统管理' },
        },
        {
          path: paths.app.system.dicts.path,
          lazy: () => import('./routes/app/dicts').then(convert(queryClient)),
          handle: { title: '字典管理', parent: '系统管理' },
        },
        {
          path: paths.app.system.dictData.path,
          lazy: () =>
            import('./routes/app/dict-data').then(convert(queryClient)),
          handle: { title: '字典数据', parent: '系统管理' },
        },
        {
          path: paths.app.system.logs.path,
          lazy: () => import('./routes/app/logs').then(convert(queryClient)),
          handle: { title: '日志管理', parent: '系统管理' },
        },
        {
          path: paths.app.asset.fundInfoManagement.path,
          lazy: () =>
            import('./routes/app/fund-info-management').then(
              convert(queryClient),
            ),
          handle: { title: '基金信息管理', parent: '系统管理' },
        },
        {
          path: paths.app.asset.funds.path,
          lazy: () => import('./routes/app/funds').then(convert(queryClient)),
          handle: { title: '基金管理', parent: '资产管理' },
        },
        {
          path: paths.app.asset.fundNavs.path,
          lazy: () =>
            import('./routes/app/fund-navs').then(convert(queryClient)),
          handle: { title: '基金净值', parent: '资产管理' },
        },
        {
          path: paths.app.asset.indexYields.path,
          lazy: () =>
            import('./routes/app/index-yields').then(convert(queryClient)),
          handle: { title: '指数收益率', parent: '资产管理' },
        },
        {
          path: paths.app.asset.positionsSummary.path,
          lazy: () =>
            import('./routes/app/positions-summary').then(convert(queryClient)),
          handle: { title: '持仓简况', parent: '资产管理' },
        },
        {
          path: paths.app.asset.fundInfo.path,
          lazy: () =>
            import('./routes/app/fund-info').then(convert(queryClient)),
          handle: { title: '基金详情', parent: '资产管理' },
        },
        {
          path: paths.app.asset.positions.path,
          lazy: () =>
            import('./routes/app/positions').then(convert(queryClient)),
          handle: { title: '持仓明细', parent: '资产管理' },
        },
        {
          path: paths.app.asset.transactions.path,
          lazy: () =>
            import('./routes/app/transactions').then(convert(queryClient)),
          handle: { title: '交易记录', parent: '资产管理' },
        },
        {
          path: paths.app.asset.analysis.path,
          lazy: () =>
            import('./routes/app/positions-analysis').then(
              convert(queryClient),
            ),
          handle: { title: '持仓分析', parent: '资产管理' },
        },
        {
          path: paths.app.asset.snapshots.path,
          lazy: () =>
            import('./routes/app/snapshots').then(convert(queryClient)),
          handle: { title: '历史持仓', parent: '资产管理' },
        },
        {
          path: paths.app.asset.transactionsImport.path,
          lazy: () =>
            import('./routes/app/import-transactions').then(
              convert(queryClient),
            ),
          handle: { title: '交易导入', parent: '资产管理' },
        },
        {
          path: paths.app.profile.path,
          lazy: () => import('./routes/app/profile').then(convert(queryClient)),
          handle: { title: '个人资料' },
        },
      ],
    },
    {
      path: '*',
      HydrateFallback,
      lazy: () => import('./routes/not-found').then(convert(queryClient)),
    },
  ]);

export const AppRouter = () => {
  const queryClient = useQueryClient(); // ← 从 AppProvider 注入的 Provider 获取
  const router = useMemo(() => createAppRouter(queryClient), [queryClient]);
  return <RouterProvider router={router} />;
};

// src/app/provider.tsx
import { QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import * as React from 'react';
import { ErrorBoundary } from 'react-error-boundary';
import { HelmetProvider } from 'react-helmet-async';

import { MainErrorFallback } from '@/components/errors/main';
import { ThemeApplier } from '@/components/theme/theme-applier';
import { Toaster } from '@/components/ui/sonner';
import { Spinner } from '@/components/ui/spinner';
import { TooltipProvider } from '@/components/ui/tooltip';
import { AuthLoader } from '@/lib/auth';
import { createQueryClient } from '@/lib/react-query';

type AppProviderProps = {
  children: React.ReactNode;
};

export const AppProvider = ({ children }: AppProviderProps) => {
  // 惰性初始化 QueryClient:整个生命周期只创建一次(单例)
  // 工厂函数含 MutationCache 成功钩子(全局写操作 toast,见 lib/react-query)
  const [queryClient] = React.useState(() => createQueryClient());

  return (
    <React.Suspense
      fallback={
        <div className="animate-in fade-in-0 flex h-screen w-screen items-center justify-center duration-200 motion-reduce:animate-none">
          <Spinner className="text-muted-foreground size-8" />
        </div>
      }
    >
      <ErrorBoundary FallbackComponent={MainErrorFallback}>
        <HelmetProvider>
          <QueryClientProvider client={queryClient}>
            {/* 全局 TooltipProvider:sidebar 菜单按钮折叠态 tooltip 等消费方依赖 */}
            <TooltipProvider>
              <ThemeApplier /> {/* 13.5 新增：全局主题应用 */}
              {import.meta.env.DEV && <ReactQueryDevtools />}
              {/* sonner 官方 toast 容器:duration 5s;hover 暂停自动关闭 */}
              <Toaster duration={5000} position="top-right" />
              <AuthLoader
                renderLoading={() => (
                  <div className="flex h-screen w-screen items-center justify-center">
                    <Spinner className="text-muted-foreground size-8" />
                  </div>
                )}
                // userFn 抛出非 401 异常（网络断/500）时的兜底 UI，
                // 避免 react-query-auth 默认 renderError 把 JSON.stringify(error) 渲染成整页
                renderError={() => <MainErrorFallback />}
              >
                {children}
              </AuthLoader>
            </TooltipProvider>
          </QueryClientProvider>
        </HelmetProvider>
      </ErrorBoundary>
    </React.Suspense>
  );
};

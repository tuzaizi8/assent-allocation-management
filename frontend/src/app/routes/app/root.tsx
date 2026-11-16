import { Outlet } from 'react-router';

// 路由级错误边界(react-router v7 约定:大写 E)
// 更外层错误由应用级 MainErrorFallback(AppProvider/ErrorBoundary)兜底
export const ErrorBoundary = () => {
  return (
    <div className="flex h-screen items-center justify-center">
      <div className="text-center">
        <h1 className="text-2xl font-bold">Something went wrong!</h1>
        <p className="text-muted-foreground">请刷新页面或联系管理员</p>
      </div>
    </div>
  );
};

export default function AppRootRoute() {
  return (
    <div className="p-8">
      <header className="border-b pb-4">
        <h1 className="text-xl font-bold">App 布局</h1>
        <p className="text-muted-foreground">路由路径: /app(含子路由 Outlet)</p>
        {/* 创建 DashboardLayout 后,改为侧边栏 + 主内容区 */}
      </header>
      <main className="py-4">
        <Outlet />
      </main>
    </div>
  );
}

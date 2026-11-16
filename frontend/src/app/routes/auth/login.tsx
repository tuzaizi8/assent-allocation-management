import { useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { toast } from 'sonner';

import { AuthLayout } from '@/components/layouts';
import { paths } from '@/config/paths';
import { LoginForm } from '@/features/auth/components';
import { AUTH_FLASH_KEY } from '@/lib/api-client';

// 登录页:读取 URL 的 redirectTo 参数(ProtectedRoute 未登录重定向时带上),
// 渲染 AuthLayout + LoginForm,登录成功后跳回 redirectTo;
// 无 redirectTo 时统一落仪表盘(paths.app.dashboard,2026-10-15;面板由路由派生自动对齐资产 tab)
const LoginRoute = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const redirectTo = searchParams.get('redirectTo');

  // 401 被踢回登录页的提示(flash message):redirectLogin 整页跳转会销毁 toast,
  // 提示经 sessionStorage 传递,在此展示(读取即清除,只弹一次)
  useEffect(() => {
    const flash = sessionStorage.getItem(AUTH_FLASH_KEY);
    if (flash) {
      sessionStorage.removeItem(AUTH_FLASH_KEY);
      toast.error('登录已过期', { description: flash });
    }
  }, []);

  return (
    <AuthLayout title="登录" description="欢迎回来，请登录你的账户">
      <LoginForm
        onSuccess={() => {
          // 跨用户缓存隔离:menu/dict 等登录周期缓存(staleTime Infinity)若残留
          // 上个账号的数据,新账号会直接消费造成串味;仅保留刚写入的当前用户键
          queryClient.removeQueries({
            predicate: (query) => query.queryKey[0] !== 'authenticated-user',
          });
          navigate(redirectTo ?? paths.app.dashboard.getHref(), {
            replace: true,
          });
        }}
      />
    </AuthLayout>
  );
};

export default LoginRoute;

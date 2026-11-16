import { useQueryClient } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router';

import { AuthLayout } from '@/components/layouts';
import { paths } from '@/config/paths';
import { RegisterForm } from '@/features/auth/components';

// 注册页:注册即登录(后端直接返回 jwt),成功后按用户权限选默认 tab
// (统一落仪表盘;redirectTo 优先;面板由路由派生自动对齐)
const RegisterRoute = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const redirectTo = searchParams.get('redirectTo');

  return (
    <AuthLayout title="注册" description="填写以下信息，创建你的账户">
      <RegisterForm
        onSuccess={() => {
          // 跨用户缓存隔离(同登录):注册即登录,清掉 SPA 会话内可能残留的
          // 上个账号的登录周期缓存,仅保留刚写入的当前用户键
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

export default RegisterRoute;

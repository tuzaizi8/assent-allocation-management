import { Navigate } from 'react-router';

import { paths } from '@/config/paths';
import { useUser } from '@/lib/auth';

export default function LandingRoute() {
  const user = useUser();

  if (user.data) {
    return <Navigate to={paths.app.root.getHref()} replace />;
  }

  // 注意:不带 redirectTo 参数——登录成功后 LoginRoute 默认跳 /app,
  // 避免「登录 → 跳回 / → 又重定向 /app」的连环跳
  return <Navigate to={paths.auth.login.getHref()} replace />;
}

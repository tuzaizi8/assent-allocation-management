import { useQueryClient } from '@tanstack/react-query';
import {
  BadgeCheckIcon,
  BellIcon,
  ChevronsUpDownIcon,
  LogOutIcon,
} from 'lucide-react';
import { useNavigate } from 'react-router';

import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from '@/components/ui/sidebar';
import { paths } from '@/config/paths';
import { useLogout, useUser } from '@/lib/auth';

/**
 * 侧边栏底部用户菜单(sidebar-08 官方 NavUser 结构)
 * 数据来自 useUser(/auth/me);登出迁移自原顶栏 UserMenu:
 * logout → 清 React Query 全部缓存(防旧账号菜单残留) → 跳登录页
 */
export function NavUser() {
  const { isMobile } = useSidebar();
  const user = useUser();
  const navigate = useNavigate();
  const logout = useLogout();
  const queryClient = useQueryClient();

  if (!user.data) return null;

  const name = `${user.data.firstName} ${user.data.lastName}`.trim();
  const email = user.data.email;
  const initials = user.data.firstName[0]?.toUpperCase() ?? '?';

  const handleLogout = async () => {
    await logout.mutateAsync(undefined);
    queryClient.clear();
    navigate(paths.auth.login.getHref());
  };

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              size="lg"
              className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
            >
              <Avatar className="h-8 w-8 rounded-lg">
                <AvatarFallback className="rounded-lg">
                  {initials}
                </AvatarFallback>
              </Avatar>
              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-medium">{name}</span>
                <span className="truncate text-xs">{email}</span>
              </div>
              <ChevronsUpDownIcon className="ml-auto size-4" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg"
            side={isMobile ? 'bottom' : 'right'}
            align="end"
            sideOffset={4}
          >
            <DropdownMenuLabel className="p-0 font-normal">
              <div className="flex items-center gap-2 px-1 py-1.5 text-left text-sm">
                <Avatar className="h-8 w-8 rounded-lg">
                  <AvatarFallback className="rounded-lg">
                    {initials}
                  </AvatarFallback>
                </Avatar>
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-medium">{name}</span>
                  <span className="truncate text-xs">{email}</span>
                </div>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() => navigate(paths.app.profile.getHref())}
            >
              <BadgeCheckIcon />
              个人资料
            </DropdownMenuItem>
            <DropdownMenuItem>
              <BellIcon />
              通知
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={handleLogout}
              className="text-destructive"
            >
              <LogOutIcon />
              退出登录
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}

import {
  ChevronRightIcon,
  Database,
  FileText,
  Folder,
  LayoutDashboard,
  LayoutGrid,
  Menu as MenuIcon,
  MessageSquare,
  Gauge,
  Settings,
  Shield,
  TrendingUp,
  Upload,
  Users,
  Wallet,
  type LucideIcon,
} from 'lucide-react';
import { NavLink, useLocation } from 'react-router';

// Collapsible 用 animate-ui 动画原语:展开/收缩带 height 0→auto + opacity + y 位移过渡
// (0.35s easeInOut),替代原生 Radix 的瞬间开合
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/animate-ui/primitives/radix/collapsible';
import {
  SidebarGroup,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
} from '@/components/ui/sidebar';
import { Skeleton } from '@/components/ui/skeleton';
import { Spinner } from '@/components/ui/spinner';

import type { MenuItem } from '../types';

// 菜单 icon 字符串 → lucide 组件映射(后端 sys_menu.icon 下发字符串)
const iconMap: Record<string, LucideIcon> = {
  'file-text': FileText,
  settings: Settings,
  users: Users,
  menu: MenuIcon,
  shield: Shield,
  'message-square': MessageSquare,
  database: Database,
  folder: Folder,
  'layout-dashboard': LayoutDashboard,
  gauge: Gauge,
  wallet: Wallet,
  upload: Upload,
  'trending-up': TrendingUp,
};

const resolveIcon = (name?: string): LucideIcon =>
  (name && iconMap[name]) || LayoutGrid;

/**
 * 主导航:后端动态菜单渲染(sidebar-08 官方结构)
 * - M 目录(有 children):官方 Collapsible 分组(箭头展开子菜单,目录本身不导航)
 * - C 菜单(无 children):NavLink 单链接
 * - NavLink 驱动 SPA 路由;isActive prop 触发官方 data-active 高亮
 */
export function NavMain({
  items,
  isLoading,
  isError,
}: {
  items: MenuItem[];
  isLoading?: boolean;
  isError?: boolean;
}) {
  const location = useLocation();

  if (isLoading) {
    return (
      <SidebarGroup>
        {/* 菜单骨架:与真实菜单项同高,加载完不跳版 */}
        <div className="flex flex-col gap-2 px-2 py-2">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-8 w-full" />
          ))}
          <Spinner className="sr-only" />
        </div>
      </SidebarGroup>
    );
  }

  if (isError) {
    return (
      <SidebarGroup>
        <div className="px-3 py-4 text-center text-sm text-destructive">
          菜单加载失败
        </div>
      </SidebarGroup>
    );
  }

  return (
    <SidebarGroup>
      {/* 官方 SidebarMenu 是 gap-0(菜单项之间零间距,靠按钮内边距撑开),条目挨得太紧;
          一级菜单补 4px 间距即可,再大(6px)会显得松散发散 */}
      <SidebarMenu className="gap-1">
        {items.map((item) => {
          const Icon = resolveIcon(item.icon);
          const children = (item.children ?? []).filter((c) => c.visible);
          // 当前路径命中子菜单时:分组高亮 + 默认展开
          const groupActive = children.some(
            (c) => c.path === location.pathname,
          );

          // C 菜单(无子项):NavLink 单链接
          if (!children.length) {
            return (
              <SidebarMenuItem key={item.id}>
                <SidebarMenuButton
                  asChild
                  tooltip={item.name}
                  isActive={item.path === location.pathname}
                >
                  <NavLink to={item.path}>
                    <Icon />
                    <span>{item.name}</span>
                  </NavLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
            );
          }

          // M 目录:官方 sidebar-08 Collapsible 分组(目录本身不导航)
          // 整行按钮就是展开触发器(官方范式):原先只有右上角 20px 小箭头可点,
          // 且箭头的扩大热区 after:-inset-2 被桌面端 md:after:hidden 禁用,
          // 点目录名称无反应,用户感知为"展开不了";箭头保留作旋转指示
          // 选中反馈只在子菜单上:目录按钮不设 isActive(仅 defaultOpen 自动展开)
          return (
            // group/collapsible 让箭头的旋转类能经由父级 li 的 data-state 生效
            <Collapsible
              key={item.id}
              asChild
              defaultOpen={groupActive}
              className="group/collapsible"
            >
              <SidebarMenuItem>
                <CollapsibleTrigger asChild>
                  <SidebarMenuButton tooltip={item.name}>
                    <Icon />
                    <span>{item.name}</span>
                  </SidebarMenuButton>
                </CollapsibleTrigger>
                <CollapsibleTrigger asChild>
                  <SidebarMenuAction className="group-data-[state=open]/collapsible:rotate-90">
                    <ChevronRightIcon />
                    <span className="sr-only">展开/收起</span>
                  </SidebarMenuAction>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <SidebarMenuSub>
                    {children.map((subItem) => (
                      <SidebarMenuSubItem key={subItem.id}>
                        <SidebarMenuSubButton
                          asChild
                          isActive={subItem.path === location.pathname}
                        >
                          <NavLink to={subItem.path}>
                            <span>{subItem.name}</span>
                          </NavLink>
                        </SidebarMenuSubButton>
                      </SidebarMenuSubItem>
                    ))}
                  </SidebarMenuSub>
                </CollapsibleContent>
              </SidebarMenuItem>
            </Collapsible>
          );
        })}
      </SidebarMenu>
    </SidebarGroup>
  );
}

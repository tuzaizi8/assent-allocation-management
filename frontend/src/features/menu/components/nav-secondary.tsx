import { LifeBuoyIcon, SendIcon, type LucideIcon } from 'lucide-react';
import * as React from 'react';

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from '@/components/ui/sidebar';

type NavItem = {
  title: string;
  icon: LucideIcon;
};

// 次级导航:入口保留、暂不跳转(目标页未定)——不套 <a>,由 SidebarMenuButton 默认渲染的
// 无 handler <button> 实现"点了不进入任何界面"
// TODO: 目标页确定后接上跳转
const items: NavItem[] = [
  { title: '支持', icon: LifeBuoyIcon },
  { title: '反馈', icon: SendIcon },
];

export function NavSecondary({
  ...props
}: React.ComponentPropsWithoutRef<typeof SidebarGroup>) {
  return (
    <SidebarGroup {...props}>
      <SidebarGroupContent>
        {/* 与 NavMain 同款:官方 gap-0 条目太紧,补 4px 保持一致观感 */}
        <SidebarMenu className="gap-1">
          {items.map((item) => (
            <SidebarMenuItem key={item.title}>
              <SidebarMenuButton size="sm">
                <item.icon />
                <span>{item.title}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  );
}

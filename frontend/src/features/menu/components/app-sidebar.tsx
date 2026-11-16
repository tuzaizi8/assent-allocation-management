import * as React from 'react';

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from '@/components/ui/sidebar';

import { useMenu } from '../api/get-menus';
import { ASSET_MENUS } from '../asset-menus';
import { useNavTabs } from '../hooks/use-nav-tabs';

import { NavMain } from './nav-main';
import { NavSecondary } from './nav-secondary';
import { NavTabsSwitcher } from './nav-tabs';
import { NavUser } from './nav-user';

/**
 * 应用侧边栏(官方 inset 方案 + 顶级模块 Tabs,四块结构:
 * tab 切换器/菜单区/次级外链/用户菜单,仅菜单区随 tab 切换数据源)
 * - SidebarHeader:管理/资产 icon Tabs 切换器(只切菜单,不导航)
 * - SidebarContent:NavMain(菜单区) + NavSecondary(次级外链,共享)
 * - SidebarFooter:NavUser(用户菜单,共享)
 * 折叠/移动端 Sheet/快捷键(Cmd+B)由 SidebarProvider 内建
 */
export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const { data: menus, isLoading, isError } = useMenu();
  const { tabs, activeTab, selectTab } = useNavTabs();

  // 双数据源:管理 tab 全量展示后端菜单(哪些菜单可见由后端按角色过滤,
  // 前端不做路径归属猜测);资产 tab 展示前端静态菜单
  const items =
    activeTab === 'management'
      ? (menus ?? []).filter((m) => m.visible)
      : ASSET_MENUS;

  // loading/error 只描述后端菜单请求,静态资产菜单无此态
  const isBackendMenuArea = activeTab === 'management';

  return (
    <Sidebar variant="inset" {...props}>
      <SidebarHeader>
        <NavTabsSwitcher
          tabs={tabs}
          value={activeTab}
          onValueChange={selectTab}
        />
      </SidebarHeader>
      <SidebarContent>
        <NavMain
          items={items}
          isLoading={isBackendMenuArea ? isLoading : false}
          isError={isBackendMenuArea ? isError : false}
        />
        <NavSecondary className="mt-auto" />
      </SidebarContent>
      <SidebarFooter>
        <NavUser />
      </SidebarFooter>
    </Sidebar>
  );
}

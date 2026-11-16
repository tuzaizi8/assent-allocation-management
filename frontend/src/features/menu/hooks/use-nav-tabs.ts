import { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router';

import {
  getExplicitTabFromPathname,
  getTabFromPathname,
  NAV_TABS,
  type NavTab,
  type NavTabValue,
} from '@/config/nav-tabs';
import { usePermissions } from '@/lib/use-permissions';

import { useMenu } from '../api/get-menus';

/**
 * 侧边栏 tab 选中态与可见性
 * - activeTab 以"正在使用哪套菜单"为准:资产路由可能同时出现在管理菜单
 *   (/app/asset/*),仅凭 pathname 会在管理 Tab 点资产菜单时误切到资产
 * - 只有路由显式归属某个 tab 时才由路由同步:/app/system/* → 管理、
 *   仪表盘 → 资产;其余保持用户当前选择
 * - 初值仍由路由推导,保证刷新/深链有确定落点
 * - 管理 tab 可见性:超管通配符 / 任一 system:* 权限 / 后端菜单树非空 三者其一;
 *   前端不硬编码角色判断;资产 tab 恒可见
 */
export function useNavTabs(): {
  tabs: NavTab[];
  activeTab: NavTabValue;
  selectTab: (value: NavTabValue) => void;
} {
  const navigate = useNavigate();
  const location = useLocation();
  const { data: menus, isLoading: menusLoading } = useMenu();
  const permissions = usePermissions();

  const hasManagementAccess =
    permissions.includes('*:*:*') ||
    permissions.some((p) => p.startsWith('system:')) ||
    (menus ?? []).length > 0;

  const tabs = NAV_TABS.filter(
    (tab) => tab.value !== 'management' || hasManagementAccess,
  );

  // 初值:刷新/深链时由路由推导;后续路由变化不再无条件改写
  const [activeTab, setActiveTab] = useState<NavTabValue>(
    () => getTabFromPathname(location.pathname) ?? 'asset',
  );

  // 路由显式归属时才同步;资产页返回 null,保持当前菜单来源
  useEffect(() => {
    const explicit = getExplicitTabFromPathname(location.pathname);
    if (!explicit) return;
    if (explicit === 'management' && !hasManagementAccess) return;
    setActiveTab(explicit);
  }, [location.pathname, hasManagementAccess]);

  // 权限收回时管理面板回落资产;菜单仍在加载时不抢先判定,避免深链首次进入被误收
  useEffect(() => {
    if (menusLoading) return;
    if (activeTab === 'management' && !hasManagementAccess) {
      setActiveTab('asset');
    }
  }, [activeTab, hasManagementAccess, menusLoading]);

  // 点击 tab = 切菜单来源 + 导航到该 tab 的默认落地页
  const selectTab = (value: NavTabValue) => {
    setActiveTab(value);
    const tab = NAV_TABS.find((t) => t.value === value);
    if (tab) navigate(tab.defaultPath);
  };

  return { tabs, activeTab, selectTab };
}

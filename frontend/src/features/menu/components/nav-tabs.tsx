import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { NavTab, NavTabValue } from '@/config/nav-tabs';

/**
 * 侧边栏顶级模块切换器(受控 Tabs)
 * - tab 只切换菜单区数据源,不导航——右侧页面由菜单项点击驱动
 * - 无管理权限的普通角色仅剩资产 tab 时切换器独占展示,授权后管理 tab 追加出现
 * - 激活白块由 @/components/ui/tabs 的测量式滑动指示器提供:按激活 trigger 的
 *   offset 做 CSS transform 过渡,不用共享 layoutId,滚动/路由切换不会投影跳动
 */
export function NavTabsSwitcher({
  tabs,
  value,
  onValueChange,
}: {
  tabs: NavTab[];
  value: NavTabValue;
  onValueChange: (value: NavTabValue) => void;
}) {
  return (
    <Tabs value={value} onValueChange={(v) => onValueChange(v as NavTabValue)}>
      {/* 覆盖官方 TabsList 的 bg-muted(0.97):侧边栏已压到 0.968,两者差值 0.002 完全融成一片,
          改用比侧边栏深一档的 --sidebar-tab-bg(0.935)把切换器从侧边栏里"抠"出来 */}
      <TabsList className="w-full bg-[var(--sidebar-tab-bg)]">
        {tabs.map((tab) => (
          <TabsTrigger key={tab.value} value={tab.value} title={tab.label}>
            <tab.icon data-icon="inline-start" />
            <span>{tab.label}</span>
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}

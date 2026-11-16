import { Database, Settings2, type LucideIcon } from 'lucide-react';

import { paths } from './paths';

export type NavTabValue = 'management' | 'asset';

export interface NavTab {
  value: NavTabValue;
  label: string;
  icon: LucideIcon;
  /** 点击 tab 时导航到的默认落地页(2026-10-15:tab 与路由双向绑定) */
  defaultPath: string;
}

// 侧边栏顶级模块 tab:管理域菜单由后端 /getRouters 全量下发,资产域菜单为
// 前端静态定义(ASSET_MENUS)。同一资产路由可能同时出现在两套菜单里,
// 故 activeTab 以"用户正在使用哪套菜单"为准(useNavTabs 持状态),
// 只在路由显式归属某个 tab 时才由路由此同步
export const NAV_TABS: NavTab[] = [
  {
    value: 'management',
    label: '管理',
    icon: Settings2,
    defaultPath: paths.app.system.users.getHref(),
  },
  {
    value: 'asset',
    label: '资产',
    icon: Database,
    defaultPath: paths.app.dashboard.getHref(),
  },
];

// 段级前缀匹配:'/'结尾精确吞掉自身与子路径,不误伤兄弟段
export function matchesPathPrefix(
  pathname: string,
  prefixes: string[],
): boolean {
  return prefixes.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

// 归属各 tab 的路由前缀(与 paths.ts 唯一真相源对齐):
// 管理域全部在 /app/system/*;仪表盘是 '/app' 段级精确;资产域业务页 /app/asset/*
const MANAGEMENT_ROUTE_PREFIXES = ['/app/system'];
const ASSET_ROUTE_PREFIXES = ['/app/asset'];

// 不归属任何 tab 的中性页面(保持当前 tab 不动)
const NEUTRAL_PATHS = ['/app/profile'];

// 初始/默认 tab 推导:挂载与刷新时使用,不参与后续每次路由变化的同步
// (资产页可能同时出现在管理菜单,不能据此反复改写用户当前选择)
export function getTabFromPathname(pathname: string): NavTabValue | null {
  if (NEUTRAL_PATHS.includes(pathname)) return null;
  if (matchesPathPrefix(pathname, MANAGEMENT_ROUTE_PREFIXES))
    return 'management';
  if (
    pathname === '/app' ||
    matchesPathPrefix(pathname, ASSET_ROUTE_PREFIXES)
  ) {
    return 'asset';
  }
  // 未知的 /app/* 深链兜底归资产(资产域是主业务面)
  return 'asset';
}

/**
 * 路由是否显式归属某个 tab。
 * 返回 null = 该路由可能同时出现在两套菜单(如 /app/asset/*),保持当前 tab。
 */
export function getExplicitTabFromPathname(
  pathname: string,
): NavTabValue | null {
  if (matchesPathPrefix(pathname, MANAGEMENT_ROUTE_PREFIXES))
    return 'management';
  if (pathname === paths.app.dashboard.getHref()) return 'asset';
  return null;
}

// 登录/注册后的默认落地页:统一仪表盘(2026-10-15 用户裁决——此前管理员落
// 用户管理但面板绑定不上,成为「乱跳」观感的一半来源)。
// redirectTo 优先级在调用方处理。

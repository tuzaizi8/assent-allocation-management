import type { MenuItem } from './types';

// 资产 tab 的前端静态菜单:不依赖后端 /getRouters(后端只负责管理域菜单)。
// 仪表盘是当前唯一确定的归属项;后续新增资产页面直接在此数组追加,
// NavMain 消费 MenuItem[] 与数据来源无关,静态/后端菜单可平滑互切
export const ASSET_MENUS: MenuItem[] = [
  {
    id: 1,
    parentId: 0,
    name: '仪表盘',
    path: '/app',
    component: '',
    perms: '',
    menuType: 'C',
    visible: true,
    icon: 'layout-dashboard',
  },
  {
    // 简况只看有效持仓,入口排在其数据的"上游"明细之前,符合概览→下钻的阅读顺序
    id: 4,
    parentId: 0,
    name: '持仓简况',
    path: '/app/asset/positions-summary',
    component: '',
    // 持仓域后端已去掉按钮级权限(仅登录 + 行级隔离),菜单不挂 perms 才是全员可见
    perms: '',
    menuType: 'C',
    visible: true,
    icon: 'gauge',
  },
  {
    id: 2,
    parentId: 0,
    name: '持仓明细',
    path: '/app/asset/positions',
    component: '',
    // 持仓域后端已去掉按钮级权限(仅登录 + 行级隔离),菜单不挂 perms 才是全员可见
    perms: '',
    menuType: 'C',
    visible: true,
    icon: 'wallet',
  },
  {
    // 持仓分析是数据消费页(回撤/波动率/夏普等专业指标):紧接持仓明细,同一份持仓数据的下钻视角(明细 → 分析)
    id: 7,
    parentId: 0,
    name: '持仓分析',
    path: '/app/asset/analysis',
    component: '',
    // 持仓域后端仅登录(行级隔离私域数据),菜单不挂 perms 才是全员可见
    perms: '',
    menuType: 'C',
    visible: true,
    icon: 'trending-up',
  },
  {
    id: 3,
    parentId: 0,
    name: '交易记录',
    path: '/app/asset/transactions',
    component: '',
    // 流水是行级隔离私域数据,同持仓一样仅登录可见
    perms: '',
    menuType: 'C',
    visible: true,
    icon: 'file-text',
  },
  {
    // 快照是分析接口的数据基座:排在业务页之后、作为运维入口收尾
    id: 5,
    parentId: 0,
    name: '历史持仓',
    path: '/app/asset/snapshots',
    component: '',
    // 快照域后端仅登录(行级隔离),菜单不挂 perms 才是全员可见
    perms: '',
    menuType: 'C',
    visible: true,
    icon: 'database',
  },
  {
    // 导入是数据入口:排在快照管理之后,导入确认会连带重建持仓与快照
    id: 6,
    parentId: 0,
    name: '交易导入',
    path: '/app/asset/import-transactions',
    component: '',
    // 导入域后端仅登录(行级隔离私域数据),菜单不挂 perms 才是全员可见
    perms: '',
    menuType: 'C',
    visible: true,
    icon: 'upload',
  },
  // 基金信息管理(fund_info 缓存表管理)刻意不在资产 tab:它是管理性入口,
  // 只挂管理 tab 的后端动态菜单(sys_menu 105,资产管理目录下)
];

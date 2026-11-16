// src/config/paths.ts
export const paths = {
  home: {
    path: '/',
    getHref: () => '/',
  },

  auth: {
    register: {
      path: '/auth/register',
      getHref: (redirectTo?: string | null | undefined) =>
        `/auth/register${redirectTo ? `?redirectTo=${encodeURIComponent(redirectTo)}` : ''}`,
    },
    login: {
      path: '/auth/login',
      getHref: (redirectTo?: string | null | undefined) =>
        `/auth/login${redirectTo ? `?redirectTo=${encodeURIComponent(redirectTo)}` : ''}`,
    },
  },

  app: {
    root: {
      path: '/app',
      getHref: () => '/app',
    },
    dashboard: {
      path: '',
      getHref: () => '/app',
    },
    users: {
      path: 'users',
      getHref: () => '/app/users',
    },
    system: {
      users: {
        path: 'system/users',
        getHref: () => '/app/system/users',
      },
      menus: {
        path: 'system/menus',
        getHref: () => '/app/system/menus',
      },
      roles: {
        path: 'system/roles',
        getHref: () => '/app/system/roles',
      },
      dicts: {
        path: 'system/dicts',
        getHref: () => '/app/system/dicts',
      },
      dictData: {
        path: 'system/dicts/data',
        getHref: (dictType: string) =>
          `/app/system/dicts/data?dictType=${encodeURIComponent(dictType)}`,
      },
      logs: {
        path: 'system/logs',
        getHref: () => '/app/system/logs',
      },
    },
    asset: {
      funds: {
        path: 'asset/funds',
        getHref: () => '/app/asset/funds',
      },
      fundNavs: {
        path: 'asset/fund-navs',
        getHref: () => '/app/asset/fund-navs',
      },
      indexYields: {
        path: 'asset/index-yields',
        getHref: () => '/app/asset/index-yields',
      },
      positions: {
        path: 'asset/positions',
        getHref: () => '/app/asset/positions',
      },
      positionsSummary: {
        path: 'asset/positions-summary',
        getHref: () => '/app/asset/positions-summary',
      },
      fundInfo: {
        path: 'asset/fund-info',
        getHref: (fundCode: string) =>
          `/app/asset/fund-info?fundCode=${encodeURIComponent(fundCode)}`,
      },
      // 基金信息管理页(fund_info 缓存表管理;路径避开 fundInfo=基金详情页)
      fundInfoManagement: {
        path: 'asset/fund-info-management',
        getHref: () => '/app/asset/fund-info-management',
      },
      transactions: {
        path: 'asset/transactions',
        getHref: () => '/app/asset/transactions',
      },
      // 持仓分析:集中展示回撤/波动率/夏普等专业指标(数据源 risk-metrics 接口)
      analysis: {
        path: 'asset/analysis',
        getHref: () => '/app/asset/analysis',
      },
      snapshots: {
        path: 'asset/snapshots',
        getHref: () => '/app/asset/snapshots',
      },
      // 交易导入:排在快照管理之后(导入确认会连带重建快照,入口贴着数据基座放)
      transactionsImport: {
        path: 'asset/import-transactions',
        getHref: () => '/app/asset/import-transactions',
      },
    },
    profile: {
      path: 'profile',
      getHref: () => '/app/profile',
    },
  },
} as const;

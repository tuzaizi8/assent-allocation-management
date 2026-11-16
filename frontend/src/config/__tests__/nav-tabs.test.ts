// nav-tabs 路由归属单测:显式归属决定"是否同步 tab",初始归属决定刷新落点。
// 两类路由的差别就是本 bug 的根因——/app/asset/* 属于资产页,但也可能挂在管理菜单下。
import {
  getExplicitTabFromPathname,
  getTabFromPathname,
} from '@/config/nav-tabs';

describe('getTabFromPathname(初始/默认 tab)', () => {
  test('管理路由归管理', () => {
    expect(getTabFromPathname('/app/system/users')).toBe('management');
    expect(getTabFromPathname('/app/system/dicts/data')).toBe('management');
  });

  test('仪表盘与资产路由归资产', () => {
    expect(getTabFromPathname('/app')).toBe('asset');
    expect(getTabFromPathname('/app/asset/positions')).toBe('asset');
    expect(getTabFromPathname('/app/asset/funds')).toBe('asset');
  });

  test('中性页不归属任何 tab', () => {
    expect(getTabFromPathname('/app/profile')).toBeNull();
  });
});

describe('getExplicitTabFromPathname(是否由路由同步 tab)', () => {
  test('管理路由显式归管理', () => {
    expect(getExplicitTabFromPathname('/app/system/users')).toBe('management');
    expect(getExplicitTabFromPathname('/app/system/dicts/data')).toBe(
      'management',
    );
  });

  test('仪表盘显式归资产', () => {
    expect(getExplicitTabFromPathname('/app')).toBe('asset');
  });

  test('资产业务页可能同时出现在两套菜单,不同步 tab', () => {
    expect(getExplicitTabFromPathname('/app/asset/funds')).toBeNull();
    expect(getExplicitTabFromPathname('/app/asset/positions')).toBeNull();
  });

  test('中性页不同步 tab', () => {
    expect(getExplicitTabFromPathname('/app/profile')).toBeNull();
  });
});

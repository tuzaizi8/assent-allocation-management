// src/features/menu/api/get-menus.ts
import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api-client';
import { useUser } from '@/lib/auth';

import type { MenuItem } from '../types';

// fetcher：调用后端 /getRouters 获取当前用户可见的菜单树
export const getMenuTree = (): Promise<MenuItem[]> => {
  return api.get('/getRouters');
};

export const useMenu = () => {
  const user = useUser();
  return useQuery({
    queryKey: ['menu'],
    queryFn: getMenuTree,
    // 菜单不频繁变，登录周期内不重新请求
    // 后端类比：相当于 Redis 缓存用户权限，TTL=session 过期时间
    staleTime: Infinity,
    // 未登录不发请求
    enabled: !!user.data,
  });
};

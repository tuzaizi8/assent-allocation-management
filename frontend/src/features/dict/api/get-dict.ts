// src/features/dict/api/get-dict.ts
import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api-client';
import { useUser } from '@/lib/auth';

import type { DictOption } from '../types';

// fetcher：调用后端 /dict/data/type/:dictType 获取指定类型的字典选项
export const getDictByType = (dictType: string): Promise<DictOption[]> => {
  return api.get(`/dict/data/type/${dictType}`);
};

/**
 * 字典 hook：同类型字典全局只请求一次，永久缓存（登录周期内不变）
 * 后端类比：相当于后端从 Redis 取字典（不每次查库）
 *
 * @param dictType - 字典类型，如 'sys_user_sex'
 * @returns 字典选项数组，未登录或未加载时返回空数组
 */
export function useDict(dictType: string): DictOption[] {
  const user = useUser();
  const { data } = useQuery({
    queryKey: ['dict', dictType],
    queryFn: () => getDictByType(dictType),
    // 字典半静态，登录周期内不重新请求
    // 后端类比：Redis 缓存 TTL=Session 过期时间
    staleTime: Infinity,
    // 未登录或空类型不发请求（避免 401）
    enabled: !!dictType && !!user.data,
  });
  return data ?? [];
}

/**
 * 便捷方法：把字典值翻译成标签文本（表格列渲染常用）
 * 返回函数而非值，因为表格 render 会对每个单元格调用
 *
 * 后端类比：相当于后端的 dict_label(dictType, value) 工具方法
 *
 * @param dictType - 字典类型
 * @returns 翻译函数：(value) => label，找不到时返回原值
 */
export function useDictLabel(dictType: string) {
  const dict = useDict(dictType);
  return (value: string) =>
    dict.find((d) => d.dictValue === value)?.dictLabel ?? value;
}

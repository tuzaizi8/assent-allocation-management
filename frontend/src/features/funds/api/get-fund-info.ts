// 基金详细信息数据层 —— GET /fund/info/{fund_code}(同花顺档案全量键值,三级缓存)
// 响应带 data 键,拦截器剥信封后直接拿到 {字段: 值} dict
import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api-client';

export type FundInfo = Record<string, string>;

/**
 * 与「基金全称」同源同义、不在页面与抽屉里罗列的档案键。
 * 消费方必须同时在「兜底/追加」分支里排掉它,否则它只是换个位置出现。
 */
export const HIDDEN_FUND_INFO_FIELDS = ['基金简称'];

/**
 * 基金详情(按需单查:仅当 fundCode 非 null 时发请求,照 index-yields 抽屉范式)。
 * 后端三级缓存(Redis 1h → DB → akshare),前端 staleTime 给 5 分钟兜底减少重复拉取。
 */
export const useFundInfo = (fundCode: string | null) =>
  useQuery({
    queryKey: ['fund-info', fundCode],
    queryFn: () =>
      api
        .get(`/fund/info/${fundCode}`)
        .then((res) => res as unknown as FundInfo),
    enabled: fundCode != null,
    staleTime: 5 * 60 * 1000,
  });

// src/features/fund-info-admin/api/get-fund-info-admin.ts
// 基金信息管理数据层:fund_info 缓存表的列表/详情/同步/新增/删除。
// 存在意义:fund_info 三级缓存在 DB 命中后不再回源,档案停在首次抓取的快照,
// 管理页的同步/新增是唯一的人工刷新入口。
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api-client';
import { mapPage, type PageResponse } from '@/lib/pagination';

/** fund_info 分页列表行(窄投影,不含 info 大 JSON) */
export type FundInfoRow = {
  fundInfoId: number;
  fundCode: string;
  /** join fund 带出;fund 表缺失(已删)时为 null */
  fundName: string | null;
  fundType: string | null;
  createTime: string;
  /** 上次强制回源/更新时间——判断档案是否过期的主要依据 */
  updateTime: string;
};

/** 同步回执:遍历表内基金逐个回源的统计 */
export type FundInfoSyncResult = {
  total: number;
  success: number;
  failedCodes: string[];
};

/** 详情单查载荷:同花顺档案全量键值 */
export type FundInfoDetail = Record<string, string>;

/** 分页列表(默认全量,代码模糊搜索) */
export const useFundInfoList = (
  pageNum: number,
  pageSize: number,
  keyword: string,
) =>
  useQuery({
    queryKey: ['fund-info-admin', 'list', pageNum, pageSize, keyword],
    queryFn: () =>
      api
        .get('/fund/info/list', {
          params: { pageNum, pageSize, keyword: keyword || undefined },
        })
        .then((res) =>
          mapPage<FundInfoRow>(res as unknown as PageResponse<FundInfoRow>),
        ),
  });

/** 详情单查(带 info 全量键值) */
export const useFundInfoDetail = (fundCode: string | null) =>
  useQuery({
    queryKey: ['fund-info-admin', 'detail', fundCode],
    enabled: fundCode != null,
    queryFn: () =>
      api
        .get(`/fund/info/${fundCode}`)
        .then((res) => res as unknown as FundInfoDetail),
  });

// ===== 变更 =====

/** 全量同步:遍历表内基金逐个强制回源(耗时数十秒,timeout 单独放宽) */
export const useSyncAllFundInfos = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      (await api.post(
        '/fund/info/sync',
        {},
        { timeout: 120_000 },
      )) as unknown as FundInfoSyncResult,
    // 成功 toast 由全局 MutationCache 读后端 msg 统一弹(含失败清单),业务层勿重复弹
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['fund-info-admin'] });
      return result;
    },
  });
};

/** 单只同步:强制回源刷新该基金档案(行内按钮,单只回源 1-2s) */
export const useSyncFundInfo = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (fundCode: string) =>
      (await api.post(
        `/fund/info/sync/${fundCode}`,
        {},
        { timeout: 30_000 },
      )) as unknown as { fundCode: string },
    onSuccess: (_res, fundCode) => {
      queryClient.invalidateQueries({ queryKey: ['fund-info-admin'] });
      return fundCode;
    },
  });
};

/** 手动新增:按代码回源抓取档案入库 */
export const useAddFundInfo = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (fundCode: string) =>
      (await api.post(
        '/fund/info',
        { fundCode },
        { timeout: 30_000 },
      )) as unknown as { fundCode: string },
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['fund-info-admin'] });
      return result;
    },
  });
};

/** 删除缓存行(详情接口会重新回源,可随时恢复) */
export const useDeleteFundInfo = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (fundCode: string) =>
      (await api.delete(`/fund/info/${fundCode}`)) as unknown as {
        fundCode: string;
      },
    onSuccess: (_res, fundCode) => {
      queryClient.invalidateQueries({ queryKey: ['fund-info-admin'] });
      return fundCode;
    },
  });
};

// src/features/indices/api/get-indices.ts —— 指数收益率管理域数据层
// 对齐后端 module_fund 的 /index/* 端点(公共数据,无接口权限,仅登录):
// GET /index/list(不分页) / GET /index/{code} / POST /index/sync(全部)
// / POST /index/sync/{code}(单个,强制回源) / DELETE /index/{codes}(物理删缓存行)
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { api } from '@/lib/api-client';

// ===== 类型 =====

/** 列表行:内置指数全集 + 库中缓存汇总(不含行情明细,明细走详情接口) */
/** 同步状态三态(直用字典 sys_index_sync_status 的 dict_value,日志页范式):
 * '1'=已同步(新鲜) / '0'=未同步(无缓存行或无有效记录) / '2'=已过期(有数据但超 24h 口径) */
export type IndexSyncStatus = '1' | '0' | '2';

export type IndexItem = {
  indexCode: string; // Sina symbol,如 sh000300
  indexName: string; // 沪深300
  syncStatus: IndexSyncStatus; // 三态判定(后端读时计算):行存在+有记录+未过期 才是 '1'
  latestClose: number | null; // 最新收盘点位
  dailyYield: number | null; // 最新一日涨跌幅(%)
  latestDate: string | null; // 最新数据日期 yyyy-MM-dd
  recordCount: number; // 缓存的行情条数
  source: string | null; // 数据来源(如 akshare)
  updateTime: string | null; // 缓存更新时间(后端已格式化)
};

export type IndexYield = { period: string; yieldPct: number | null };
export type IndexRecent = {
  navDate: string;
  close: number;
  dailyYield: number;
};

/** 详情 = 列表行 + 区间收益率 + 最近 10 个交易日明细 */
export type IndexDetail = IndexItem & {
  yields: IndexYield[];
  recent: IndexRecent[];
};

/** 全量同步结果(后端逐个独立提交,返回成功数与失败清单) */
export type SyncAllResult = {
  success: number;
  failed: string[];
  total: number;
};

// ===== 查询 =====

export const getIndices = (params: { keyword?: string; syncStatus?: string }) =>
  api
    .get('/index/list', { params })
    .then((res) => res as unknown as IndexItem[]);

/** 列表(集合固定,不分页;未同步的指数也在列) */
export const useIndices = (keyword?: string, syncStatus?: string) =>
  useQuery({
    queryKey: ['indices', keyword, syncStatus],
    queryFn: () => getIndices({ keyword, syncStatus }),
  });

/** 详情(抽屉按需单查):元数据 + 区间收益率 + 最近 10 个交易日 */
export const useIndexDetail = (indexCode: string | null) =>
  useQuery({
    queryKey: ['index', indexCode],
    queryFn: () =>
      api
        .get(`/index/${indexCode}`)
        .then((res) => res as unknown as IndexDetail),
    enabled: indexCode != null,
  });

// ===== 变更 =====

/**
 * 全量同步(限流 4 次/小时,5 个指数逐个回源,耗时长)。
 * toast 在此局部弹:响应带 data 载荷,axios 拦截器剥掉信封后全局 MutationCache
 * 读不到 msg(全局成功钩子只认 data.msg)——带载荷的写接口都须自弹。
 * 部分失败用 warning:后端对单指数失败只进 failed 清单不抛错,这里是唯一浮现口。
 */
export const useSyncAllIndices = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (): Promise<SyncAllResult> =>
      (await api.post('/index/sync')) as SyncAllResult,
    onSuccess: (data) => {
      const text = `成功同步 ${data.success}/${data.total} 个指数`;
      if (data.failed.length > 0) {
        toast.warning(text, { description: `失败：${data.failed.join('、')}` });
      } else {
        toast.success(text);
      }
      queryClient.invalidateQueries({ queryKey: ['indices'] });
      queryClient.invalidateQueries({ queryKey: ['index'] });
    },
  });
};

/** 单指数同步(强制回源,绕过缓存新鲜度判定)。toast 局部弹,原因同上 */
export const useSyncIndex = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (
      indexCode: string,
    ): Promise<{ indexName: string; recordCount: number }> =>
      (await api.post(`/index/sync/${indexCode}`)) as {
        indexName: string;
        recordCount: number;
      },
    onSuccess: (data) => {
      toast.success(
        `成功同步「${data.indexName}」${data.recordCount} 条行情数据`,
      );
      queryClient.invalidateQueries({ queryKey: ['indices'] });
      queryClient.invalidateQueries({ queryKey: ['index'] });
    },
  });
};

/**
 * 删除缓存行(物理删除)。后端会连带清 Redis——否则删完列表/图表仍从缓存读到已删数据。
 * 删除是可恢复的:下次同步或访问图表会重新拉取全量行情。toast 局部弹,原因同上。
 */
export const useDeleteIndices = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (
      indexCodes: string[],
    ): Promise<{ deleted: number; codes: string[] }> =>
      (await api.delete(`/index/${indexCodes.join(',')}`)) as {
        deleted: number;
        codes: string[];
      },
    onSuccess: (data) => {
      toast.success(`已清除 ${data.deleted} 个指数的历史缓存`);
      queryClient.invalidateQueries({ queryKey: ['indices'] });
      queryClient.invalidateQueries({ queryKey: ['index'] });
    },
  });
};

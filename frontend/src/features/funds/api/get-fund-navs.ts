// src/features/funds/api/get-fund-navs.ts —— 基金净值域数据层
// 对齐后端 GET /fund/nav/list(分页,窄投影不含 nav_data 大 JSON)
// / POST /fund/nav/{code}(按需同步单只,消费七接口)
// / GET /fund/list(弹窗候选搜索:添加入口按代码或名称模糊匹配 fund 表)
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { getFundCandidates } from '@/features/funds/api/get-funds';
import { api } from '@/lib/api-client';
import { mapPage, PageResponse } from '@/lib/pagination';
import { useHasPermission } from '@/lib/use-permissions';

// ===== 类型 =====

/** 后端净值行(窄投影:列表不含 nav_data 大 JSON;后端 CamelCaseUtil 已转驼峰) */
export type FundNavRow = {
  fundNavId: number;
  fundCode: string;
  fundName: string | null;
  /** 最新净值日期 yyyy-MM-dd(冗余列,同步时由后端维护) */
  latestDate: string | null;
  /** 净值记录条数(冗余列) */
  recordCount: number | null;
  updateTime: string | null;
};

export type FundNavListParams = {
  pageNum: number;
  pageSize: number;
  fundCode?: string;
  fundName?: string;
  syncStatus?: string;
};

// ===== 查询 =====

export const getFundNavs = (params: FundNavListParams) =>
  api
    .get('/fund/nav/list', { params })
    // 拦截器运行时已解包(平铺对象),类型签名仍是 AxiosResponse(同 funds 的双重转换)
    .then((res) =>
      mapPage<FundNavRow>(res as unknown as PageResponse<FundNavRow>),
    );

/**
 * 净值行列表。keyword 按形态分流:纯数字查代码,否则查名称(与 funds 页一致——
 * 后端 code 与 name 是 AND 关系的模糊条件,同传会要求都命中)。
 */
export const useFundNavs = (
  pageNum: number,
  pageSize: number,
  keyword?: string,
  syncStatus?: string,
) => {
  const trimmed = keyword?.trim();
  // 权限闸门:无 fund:nav:list 的账号经 redirectTo 误入本页时不发请求
  const canAccess = useHasPermission('fund:nav:list');
  return useQuery({
    queryKey: ['fund-navs', pageNum, pageSize, trimmed, syncStatus],
    queryFn: () => {
      const isCode = !!trimmed && /^\d+$/.test(trimmed);
      return getFundNavs({
        pageNum,
        pageSize,
        ...(trimmed
          ? isCode
            ? { fundCode: trimmed }
            : { fundName: trimmed }
          : {}),
        syncStatus,
      });
    },
    enabled: canAccess,
  });
};

/**
 * 添加入口的基金候选(弹窗内即时搜索 fund 表)。
 * 搜索走 /fund/list(需 fund:fund:list 权限),关键词按形态分流:纯数字查代码,否则查名称;
 * 只取前 10 条作候选——弹窗是"选一只同步"的窄场景,不做翻页。
 * 内置 300ms 防抖:cmdk 逐字输入若每键一请求,/fund/list 的 30/60 限流仍会被打满(10/60 时实测必触发 429);
 * 防抖收在 hook 内,消费方无需各自包装。
 */
export const useFundCandidates = (keyword: string, open: boolean) => {
  const trimmed = keyword.trim();
  // 防抖查询词:清空立即生效(避免弹窗重开后短暂用旧词误发请求),非空输入延迟 300ms
  const [debouncedKeyword, setDebouncedKeyword] = useState(trimmed);
  useEffect(() => {
    if (!trimmed) {
      setDebouncedKeyword('');
      return;
    }
    const timer = setTimeout(() => setDebouncedKeyword(trimmed), 300);
    return () => clearTimeout(timer);
  }, [trimmed]);
  return useQuery({
    queryKey: ['fund-candidates', debouncedKeyword],
    queryFn: () => {
      const isCode = /^\d+$/.test(debouncedKeyword);
      // 走公共候选端点(仅登录,无 fund:fund:list 权限要求):
      // 选基金是建仓/买入的核心路径,不该被基金管理页的菜单权限卡住
      return getFundCandidates({
        pageNum: 1,
        pageSize: 10,
        ...(isCode ? { code: debouncedKeyword } : { name: debouncedKeyword }),
      });
    },
    // 弹窗关即零请求(不查 cached 结果之外的任何东西),关键词为空也不发
    enabled: open && debouncedKeyword.length > 0,
    // 同词 30s 内重搜直接命中缓存:与防抖双兜底,彻底远离 30/60 限流
    staleTime: 30_000,
  });
};

// ===== 变更 =====

/**
 * 按需同步单只基金净值(消费七接口)。
 * 响应 data 是 records 数组:被拦截器剥掉信封后全局 MutationCache 读不到 msg,
 * 须局部 toast(带载荷写接口范式,同 get-indices);返回条数供文案展示。
 */
export const useSyncFundNav = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (fundCode: string): Promise<number> => {
      const records = (await api.post(
        `/fund/nav/${fundCode}`,
      )) as unknown as Array<Record<string, unknown>>;
      return records.length;
    },
    onSuccess: (count) => {
      toast.success(`同步成功，共 ${count} 条净值记录`);
      queryClient.invalidateQueries({ queryKey: ['fund-navs'] });
    },
  });
};

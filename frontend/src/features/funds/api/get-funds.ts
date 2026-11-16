// src/features/funds/api/get-funds.ts —— 基金管理域数据层
// 对齐后端 module_fund:GET /fund/list(分页+动态条件) / GET /fund/{id} / POST /fund
// / PUT /fund / DELETE /fund/{fund_ids} / POST /fund/sync
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { z } from 'zod';

import { api } from '@/lib/api-client';
import { mapPage, PageResponse } from '@/lib/pagination';
import { useHasPermission } from '@/lib/use-permissions';

// ===== 类型 =====

/** 后端 fund 表行(分页 rows 元素;后端 VO 已 to_camel,前端只消费驼峰) */
export type Fund = {
  fundId: number;
  code: string;
  name: string;
  fundType: string | null;
  /** '0' 正常 / '1' 停用(与 sys_normal_disable 字典同语义) */
  status: string | null;
  createBy: string | null;
  createTime: string | null;
  updateBy: string | null;
  updateTime: string | null;
  remark: string | null;
};

// ===== 查询 =====

export type FundListParams = {
  pageNum: number;
  pageSize: number;
  /** 代码模糊匹配 */
  code?: string;
  /** 名称模糊匹配 */
  name?: string;
  /** 类型精确匹配 */
  fundType?: string;
  /** 状态精确匹配 */
  status?: string;
};

export const getFunds = (params: FundListParams) =>
  api
    .get('/fund/list', { params })
    // 同 users:拦截器运行时已解包(平铺对象),但 api.get 的类型签名仍是 AxiosResponse,
    // 直接 as 会报 TS2352 不重叠,需经 as unknown 过渡
    .then((res) => mapPage<Fund>(res as unknown as PageResponse<Fund>));

/**
 * 基金候选(公共参考数据,仅登录即可):供建仓/买入与净值页的选择器按代码或名称模糊搜索。
 * 与 /fund/list 的区别是后者挂 fund:fund:list(「基金管理」菜单权限)——用它卡录入控件会让
 * 没有该菜单的普通账号连建仓都做不了,故选取器走这个无权限端点(后端上限 20 条)。
 */
export const getFundCandidates = (params: FundListParams) =>
  api
    .get('/fund/candidates', { params })
    .then((res) => mapPage<Fund>(res as unknown as PageResponse<Fund>));

/** 类型选项(库内现有基金类型 distinct;集合随同步增长,写操作后由 mutation 一并失效) */
export const useFundTypes = () => {
  // 权限闸门:无 fund:fund:list 的账号经 redirectTo 误入本页时不发请求,
  // 避免登录即弹"无此接口权限" toast(页面渲染无权限空态,零请求)
  const canAccess = useHasPermission('fund:fund:list');
  return useQuery({
    queryKey: ['fund-types'],
    queryFn: () =>
      api.get('/fund/types').then((res) => res as unknown as string[]),
    // 类型集合低频变动,对齐字典的消费口径:登录周期内不重取,靠写操作主动失效
    staleTime: Infinity,
    enabled: canAccess,
  });
};

/** 图表时间档(与后端 filter_records_by_period 同源,由 GET /fund/periods 下发):
 * 档位驱动后端回溯计算,前端自造常量会与计算口径漂移,故消费端动态拉取。
 * 公共选项数据:后端仅验证登录不挂接口权限(与 /fund/chart/* 同口径),无需权限闸门 */
export const useFundPeriods = () => {
  return useQuery({
    queryKey: ['fund-periods'],
    queryFn: () =>
      api.get('/fund/periods').then((res) => res as unknown as string[]),
    // 档位集合随代码发布才可能变化,登录周期内不重取
    staleTime: Infinity,
  });
};

/**
 * 列表查询。keyword 按形态分流:纯数字只查代码,否则只查名称——
 * 后端 code 与 name 是两个 AND 关系的模糊条件,同一个词同时传会要求"代码与名称都命中"。
 */
export const useFunds = (
  pageNum: number,
  pageSize: number,
  keyword?: string,
  fundType?: string,
  status?: string,
) => {
  const trimmed = keyword?.trim();
  // 权限闸门同 useFundTypes:无权限时不发请求,交由页面渲染无权限空态
  const canAccess = useHasPermission('fund:fund:list');
  return useQuery({
    queryKey: ['funds', pageNum, pageSize, trimmed, fundType, status],
    queryFn: () => {
      const isCode = !!trimmed && /^\d+$/.test(trimmed);
      return getFunds({
        pageNum,
        pageSize,
        ...(trimmed ? (isCode ? { code: trimmed } : { name: trimmed }) : {}),
        fundType,
        status,
      });
    },
    enabled: canAccess,
  });
};

// 详情页与编辑弹窗均用列表行数据(对齐 users 页:基金行字段完整,无需再拉详情,
// 也避免多一次 fund:fund:query 权限依赖),故本域不提供 useFundDetail

// ===== 变更 =====

/** 新增校验(对齐后端 FundAddModel:code 1-20、name 1-100) */
export const addFundSchema = z.object({
  code: z.string().min(1, '必填').max(20, '最多 20 字'),
  name: z.string().min(1, '必填').max(100, '最多 100 字'),
  fundType: z.string().max(20, '最多 20 字').or(z.literal('')).optional(),
  status: z.enum(['0', '1']).default('0'),
  remark: z.string().max(500, '最多 500 字').or(z.literal('')).optional(),
});
export type AddFundInput = z.infer<typeof addFundSchema>;

/** 编辑校验(新增字段 + 主键;后端靠 fundId 定位记录) */
export const editFundSchema = addFundSchema.extend({ fundId: z.number() });
export type EditFundInput = z.infer<typeof editFundSchema>;

/**
 * 选填字段的空串转 undefined:JSON.stringify 会丢弃 undefined,
 * 后端 exclude_unset 便不会把空串写进库(避免 remark 存成空字符串而非 NULL)。
 */
export const toFundPayload = <T extends AddFundInput>(values: T) => ({
  ...values,
  fundType: values.fundType || undefined,
  remark: values.remark || undefined,
});

export const useAddFund = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: AddFundInput) => api.post('/fund', toFundPayload(data)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['funds'] }); // 失效列表缓存重拉
      // 新增可能引入库里没有过的新类型,类型选项一并失效
      queryClient.invalidateQueries({ queryKey: ['fund-types'] });
    },
  });
};

export const useEditFund = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: EditFundInput) => api.put('/fund', toFundPayload(data)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['funds'] });
      queryClient.invalidateQueries({ queryKey: ['fund-types'] });
    },
  });
};

export const useDeleteFund = () => {
  const queryClient = useQueryClient();
  return useMutation({
    // 后端契约:DELETE /fund/{fund_ids}(路径参数,逗号分隔支持批量;逻辑删除,
    // 被持仓引用时后端 601 整批拒删,由拦截器统一弹提示)
    mutationFn: (fundIds: number | number[]) => {
      const ids = Array.isArray(fundIds) ? fundIds.join(',') : fundIds;
      return api.delete(`/fund/${ids}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['funds'] });
      // 某类型的最后一只被删后,该类型不应再出现在筛选下拉里
      queryClient.invalidateQueries({ queryKey: ['fund-types'] });
    },
  });
};

/**
 * 全量同步(限流 4 次/小时,一次拉全市场基金,耗时很长)。
 * 成功 toast 由全局 MutationCache.onSuccess 读后端 msg(「成功同步 N 条基金数据」)统一弹。
 */
export const useSyncFunds = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post('/fund/sync'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['funds'] });
      // 同步最可能引入新类型(全市场基金),类型选项必须一并失效
      queryClient.invalidateQueries({ queryKey: ['fund-types'] });
    },
  });
};

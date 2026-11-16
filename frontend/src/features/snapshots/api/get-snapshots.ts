// src/features/snapshots/api/get-snapshots.ts —— 快照管理页数据层
// 信封契约同持仓域:分页响应 rows 平铺在顶层(拦截器整包返回,由 mapPage 消费),
// generate/rebuild 走 data 通道——两者被剥掉信封后全局 MutationCache 读不到 msg,故局部 toast 回执。
// 参数命名:list 用驼峰(后端查询模型带 camel 别名);generate 是标量 Query 参数且无别名,必须 snake_case。
// 快照是行级隔离私域数据:后端全部端点仅挂 CurrentUser,本域不引入权限闸门。
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { api } from '@/lib/api-client';
import { mapPage, type PageResponse } from '@/lib/pagination';

/** 全量重建(清空后按交易逐日重算整段历史)实测 60~100 秒,必须覆盖 api-client 的
 *  30 秒全局兜底:否则重建成功也被判失败——mutation 的 onSuccess 不执行,列表不自动
 *  刷新;且超时(无 response)会命中 api-client 的网络层重试被自动重发,后端回
 *  「已有重建正在进行」,把一次成功重建成说成失败。
 */
const SNAPSHOT_REBUILD_TIMEOUT_MS = 10 * 60 * 1000;

// ===== 类型 =====

/** 每日快照聚合行 */
export type SnapshotDailyRow = {
  /** yyyy-MM-dd */
  snapshotDate: string;
  fundCount: number;
  totalValue: number;
  /** 同日累计净投入;该日无现金流记录时为 null(展示破折号,不塞 0 冒充) */
  cumulativeInvested: number | null;
};

/** 生成快照回执 */
export type SnapshotGenerateResult = {
  startDate: string;
  endDate: string;
  daysGenerated: number;
  cashFlowDays: number;
};

/** 重建快照回执 */
export type SnapshotRebuildResult = {
  userId: number;
  cleared: { snapshotsDeleted: number; cashFlowsDeleted: number };
  rebuilt: {
    snapshotsCreated: number;
    cashFlowsCreated: number;
    dateRange: { start: string | null; end: string | null };
  };
};

/** 区间入参(空串/undefined 即未选,后端按默认区间处理:结束日今天、起始前 90 天) */
export type SnapshotRange = { startDate?: string; endDate?: string };

/** 某日单只基金的明细行(行点击抽屉;占比后端算好,前端不重算) */
export type SnapshotDayFund = {
  fundCode: string;
  /** 已删基金的行仍在(join isouter),名称可能为 null */
  fundName: string | null;
  shares: number;
  nav: number;
  marketValue: number;
  /** 占当日总市值百分比(两位小数) */
  ratio: number;
};

/** 某日的每日持仓明细(抽屉载荷) */
export type SnapshotDayDetail = {
  snapshotDate: string;
  totalValue: number;
  fundCount: number;
  funds: SnapshotDayFund[];
};

// ===== 查询 =====

/** 每日快照分页(新→旧) */
export const useSnapshotList = (
  pageNum: number,
  pageSize: number,
  range: SnapshotRange,
) =>
  useQuery({
    queryKey: [
      'snapshots',
      'list',
      pageNum,
      pageSize,
      range.startDate,
      range.endDate,
    ],
    queryFn: () =>
      api
        .get('/portfolio/snapshot/list', {
          params: {
            pageNum,
            pageSize,
            startDate: range.startDate,
            endDate: range.endDate,
          },
        })
        .then((res) =>
          mapPage<SnapshotDailyRow>(
            res as unknown as PageResponse<SnapshotDailyRow>,
          ),
        ),
  });

/** 某日基金明细(行点击抽屉;date 为 null 不发请求) */
export const useSnapshotDayDetail = (date: string | null) =>
  useQuery({
    queryKey: ['snapshots', 'day', date],
    enabled: date != null,
    queryFn: () =>
      api
        .get(`/portfolio/snapshot/day/${date}`)
        .then((res) => res as unknown as SnapshotDayDetail),
  });

// ===== 变更 =====

/** 生成每日持仓记录(固定最近 90 天——日期区间仅供查询,与生成解耦;2026-10-12 用户裁决;
 *  后端限流 10 次/小时,超限由 api-client 的 429 分支提示重试时间) */
export const useGenerateSnapshots = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      (await api.post(
        '/portfolio/snapshot/generate',
      )) as unknown as SnapshotGenerateResult,
    onSuccess: (result) => {
      toast.success(
        `历史持仓记录生成完成:${result.daysGenerated} 天记录 / ${result.cashFlowDays} 天现金流`,
      );
      queryClient.invalidateQueries({ queryKey: ['snapshots'] });
      // 快照市值变了,消费它的收益率曲线/指标卡缓存一并失效,否则曲线停留旧数据
      queryClient.invalidateQueries({ queryKey: ['portfolio-trend'] });
      queryClient.invalidateQueries({ queryKey: ['portfolio-twr'] });
      queryClient.invalidateQueries({ queryKey: ['daily-fund-profit'] });
    },
  });
};

/** 三级:只清空快照与现金流(交易与持仓不动,可随时重新生成) */
export const useDeleteAllSnapshots = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      (await api.delete('/portfolio/snapshot/all')) as unknown as {
        snapshotsDeleted: number;
        cashFlowsDeleted: number;
      },
    onSuccess: (result) => {
      toast.success(
        `已清空 ${result.snapshotsDeleted} 条历史持仓记录 / ${result.cashFlowsDeleted} 条现金流，可随时重新生成`,
      );
      queryClient.invalidateQueries({ queryKey: ['snapshots'] });
      // 快照市值变了,消费它的收益率曲线/指标卡缓存一并失效,否则曲线停留旧数据
      queryClient.invalidateQueries({ queryKey: ['portfolio-trend'] });
      queryClient.invalidateQueries({ queryKey: ['portfolio-twr'] });
      queryClient.invalidateQueries({ queryKey: ['daily-fund-profit'] });
    },
  });
};

/** 重建快照(清空后按交易记录逐日重建到今天;破坏性操作,调用方须先二次确认) */
export const useRebuildSnapshots = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      (await api.post('/portfolio/snapshot/rebuild', null, {
        timeout: SNAPSHOT_REBUILD_TIMEOUT_MS,
      })) as unknown as SnapshotRebuildResult,
    onSuccess: (result) => {
      // 回执带清空与重建两类条数:重建消耗 4 次/小时配额,必须让用户看到实际做了什么
      toast.success(
        `重建完成:清空 ${result.cleared.snapshotsDeleted} 条记录 / ${result.cleared.cashFlowsDeleted} 条现金流;重建 ${result.rebuilt.snapshotsCreated} 条记录 / ${result.rebuilt.cashFlowsCreated} 条现金流(${result.rebuilt.dateRange.start} ~ ${result.rebuilt.dateRange.end})`,
      );
      queryClient.invalidateQueries({ queryKey: ['snapshots'] });
      // 快照市值变了,消费它的收益率曲线/指标卡缓存一并失效,否则曲线停留旧数据
      queryClient.invalidateQueries({ queryKey: ['portfolio-trend'] });
      queryClient.invalidateQueries({ queryKey: ['portfolio-twr'] });
      queryClient.invalidateQueries({ queryKey: ['daily-fund-profit'] });
    },
  });
};

// ===== 季度变化 =====

/** 某季度末单只基金(季度变化卡片;占比后端算好) */
export type QuarterlyFund = {
  fundCode: string;
  fundName: string | null;
  /** fund 表的 fund_type(如 混合型-偏股/债券型-信用债),季度饼图按它聚合 */
  fundType: string | null;
  marketValue: number;
  ratio: number;
};

/** 一个季度末的持仓快照 */
export type QuarterlyQuarter = {
  /** 季度末自然日(3-31/6-30/9-30/12-31) */
  quarterEnd: string;
  /** 实际取到快照的日期(季度末撞周末/未生成时前移) */
  snapshotDate: string;
  totalValue: number;
  funds: QuarterlyFund[];
};

/** 近 N 个季度末持仓序列(变化对比由前端按相邻季度计算) */
export type QuarterlyResponse = {
  quarters: QuarterlyQuarter[];
};

/** 季度末持仓序列(历史持仓页季度变化卡片;默认近 8 季) */
export const useQuarterlySnapshots = () =>
  useQuery({
    queryKey: ['snapshots', 'quarterly'],
    queryFn: () =>
      api
        .get('/portfolio/snapshot/quarterly')
        .then((res) => res as unknown as QuarterlyResponse),
  });

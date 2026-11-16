// 持仓域数据层 —— 对齐后端 module_portfolio 的 /portfolio/position/* 端点
// 响应解包差异由拦截器行为决定(data 存在则返回 data,否则返回整包),逐端点不同:
//   list / transactions 经 model_content 平铺出网(顶层 rows/pageNum/pageSize/total/hasNext,无 data 键)
//     → mapPage 消费,与 fund 列表同一契约
//   {position_id} 有 data 键 → 直接拿到业务对象
//   建仓 / 买入 / 赎回 带 data 载荷 → 信封被剥后全局 MutationCache 读不到 msg,须局部 toast
// 持仓是行级隔离私域数据:后端全部端点仅挂 CurrentUser,故本域不引入任何权限闸门
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { z } from 'zod';

import { api } from '@/lib/api-client';
import { saveBlob } from '@/lib/download';
import { mapPage, PageResponse } from '@/lib/pagination';

// ===== 类型 =====

/** 买入流水(后端 purchase_records + 换算出的 total_cost;按 fund_code 匹配后可含同基金旧持仓的记录) */
export type PurchaseRecord = {
  purchaseId: number;
  positionId: number;
  fundCode: string;
  /** 所选日期净值未发布时为 0(待确认),发布后由后端懒确认回填 */
  shares: number;
  costPrice: number;
  /** yyyy-MM-dd */
  purchaseDate: string;
  totalCost: number;
  /** '0' 待确认(所选日期净值未公布) / '1' 已确认;存量数据恒为已确认 */
  status?: string;
  /** 买入金额(待确认时为用户输入,确认后冗余=shares*costPrice) */
  amount?: number | null;
  createTime: string | null;
  remark: string | null;
};

/** 赎回流水(后端 redemption_records + 换算出的 total_amount;按 fund_code 匹配后可含同基金旧持仓的记录) */
export type RedemptionRecord = {
  redemptionId: number;
  positionId: number;
  fundCode: string;
  shares: number;
  /** 所选日期净值未发布时为 0(待确认),发布后由后端懒确认回填 */
  navPrice: number;
  /** yyyy-MM-dd */
  redemptionDate: string;
  totalAmount: number;
  /** '0' 待确认(到账金额未定,份额照常参与波动) / '1' 已确认 */
  status?: string;
  /** 到账金额(确认后由后端回填) */
  amount?: number | null;
  createTime: string | null;
  remark: string | null;
};

/** 持仓明细(列表行与详情同构:汇总字段 + 买卖历史) */
export type PositionDetail = {
  positionId: number;
  userId: number;
  fundName: string;
  fundCode: string;
  fundType: string;
  /** 剩余份额 = Σ买入 − Σ赎回 */
  totalShares: number;
  /** 持仓成本 = 剩余份额对应的成本(卖出时按当时加权平均成本结转,已卖份额的成本不再压在这里) */
  totalCost: number;
  /** 平均成本 = 持仓成本 ÷ 剩余份额 */
  avgCostPrice: number;
  currentValue: number;
  /** 持有收益 = 当前市值 − 持仓成本(只看本轮持仓) */
  profit: number;
  /** 持有收益率(百分比数值,后端已 ×100) */
  profitRate: number;
  /** 已实现收益 = 该基金历次赎回/清仓结转的盈亏合计(含此前已清仓的多轮持仓) */
  realizedProfit: number;
  /** 累计盈亏 = 持有收益 + 已实现收益(「这只基金所有交易一共赚亏多少」) */
  totalProfit: number;
  /** 正常 / 部分赎回 / 全部赎回 */
  status: string;
  purchaseRecords: PurchaseRecord[];
  redemptionRecords: RedemptionRecord[];
  createTime: string | null;
  updateTime: string | null;
};

/** 交易流水(买入 + 赎回合并后的历史,含已清仓持仓的记录) */
export type PositionTransaction = {
  /** 后端直出中文,前端免映射 */
  type: string;
  /** 行级删除定位键:source 区分买卖两侧主键 */
  recordId: number;
  source: 'purchase' | 'redemption';
  fundCode: string;
  fundName: string;
  /** yyyy-MM-dd */
  date: string;
  /** 待确认(status='0')时为用户输入金额,份额/单价是 0 占位 */
  amount: number;
  shares: number;
  price: number;
  /** '0' 待确认(所选日期净值未公布) / '1' 已确认 */
  status?: string;
  remark: string | null;
};

// ===== 查询 =====

/** 持仓分页(分页作用于头表定位,行数据仍是含汇总与买卖历史的明细;keyword 后端按基金名称/代码模糊) */
/** 可排序字段:三个都是后端派生指标(份额×净值 / 结转成本),与后端 POSITION_SORT_KEYS 一一对应 */
export type PositionSortBy = 'current_value' | 'profit' | 'profit_rate';

export const usePositions = (
  pageNum: number,
  pageSize: number,
  keyword?: string,
  /** 排序字段;缺省后端口径 = 当前市值降序 */
  sortBy?: PositionSortBy,
  sortOrder?: 'asc' | 'desc',
) =>
  useQuery({
    // 排序必须进缓存键:否则切排序会命中上一份排序的缓存,表格看着"没反应"
    queryKey: ['positions', pageNum, pageSize, keyword, sortBy, sortOrder],
    queryFn: () =>
      api
        .get('/portfolio/position/list', {
          params: { pageNum, pageSize, keyword, sortBy, sortOrder },
        })
        .then((res) =>
          mapPage<PositionDetail>(
            res as unknown as PageResponse<PositionDetail>,
          ),
        ),
  });

/**
 * 有效持仓全量(简况卡片页消费,无分页元数据;后端 is_page=false 走 rows 通道,
 * 响应顶层只有 rows + statusCounts)。个人账本量级小,一次拉全比分页轮翻更省重接口调用。
 */
export const useAllPositions = () =>
  useQuery({
    queryKey: ['positions', 'all'],
    queryFn: () =>
      api
        .get('/portfolio/position/list', {
          params: { isPage: false },
        })
        .then((res) => {
          const body = res as unknown as { rows: PositionDetail[] };
          return body.rows ?? [];
        }),
  });

/** 买卖流水分页(txType 按类型精确筛选,值为后端直出的中文 '买入'/'赎回';已按日期倒序,前端不再排序) */
export const useTransactions = (
  pageNum: number,
  pageSize: number,
  txType?: string,
) =>
  useQuery({
    queryKey: ['position-transactions', pageNum, pageSize, txType],
    queryFn: () =>
      api
        .get('/portfolio/position/transactions', {
          params: { pageNum, pageSize, txType },
        })
        .then((res) =>
          mapPage<PositionTransaction>(
            res as unknown as PageResponse<PositionTransaction>,
          ),
        ),
  });

/** 持仓明细(抽屉按需单查;列表行已含同构数据,故仅在开抽屉时发请求) */
export const usePositionDetail = (positionId: number | null) =>
  useQuery({
    queryKey: ['position', positionId],
    queryFn: () =>
      api
        .get(`/portfolio/position/${positionId}`)
        .then((res) => res as unknown as PositionDetail),
    enabled: positionId != null,
  });

// ===== 校验 =====

/**
 * 建仓与买入共用一个 schema:后端两个 VO 字段与约束完全一致,
 * 且都是「份额 = 金额 ÷ 买入日净值」由后端换算,前端只传金额。
 */
export const tradeSchema = z.object({
  fundCode: z.string().min(1, '必填').max(20, '最多 20 字'),
  amount: z.coerce.number().gt(0, '必须大于 0'),
  purchaseDate: z.string().min(1, '必填'),
  /** 下单时点在 15:00 之后:确认日顺延到下一交易日(后端换算份额的净值随之改天) */
  afterCutoff: z.boolean().default(false),
  remark: z.string().max(500, '最多 500 字').or(z.literal('')).optional(),
});
export type TradeInput = z.infer<typeof tradeSchema>;

/** 赎回按份额提交(后端不接受金额),且不得早于首次买入日 */
export const redeemSchema = z.object({
  fundCode: z.string().min(1, '必填').max(20, '最多 20 字'),
  shares: z.coerce.number().gt(0, '必须大于 0'),
  redemptionDate: z.string().min(1, '必填'),
  /** 同买入:15:00 后下单按下一交易日净值成交(影响到账金额与份额扣减日) */
  afterCutoff: z.boolean().default(false),
  remark: z.string().max(500, '最多 500 字').or(z.literal('')).optional(),
});
export type RedeemInput = z.infer<typeof redeemSchema>;

/** 选填备注的空串转 undefined:JSON.stringify 丢弃后后端不把空串写进库 */
export const toTradePayload = <T extends { remark?: string }>(values: T) => ({
  ...values,
  remark: values.remark || undefined,
});

// ===== 变更 =====

/**
 * 建仓(首次买入)。已持仓时后端 601 拒绝并提示改用分批买入。
 * 局部 toast 且带上后端换算出的份额:用户填的是金额,份额是系统算的,需要回执。
 */
export const useCreatePosition = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (data: TradeInput) =>
      (await api.post(
        '/portfolio/position',
        toTradePayload(data),
      )) as unknown as PositionDetail,
    onSuccess: (detail) => {
      toast.success(`建仓成功，确认份额 ${detail.totalShares.toFixed(2)}`);
      queryClient.invalidateQueries({ queryKey: ['positions'] });
      queryClient.invalidateQueries({ queryKey: ['position-transactions'] });
    },
  });
};

/** 分批买入(无持仓时后端自动建仓,不拒绝) */
export const useAddPurchase = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (data: TradeInput) =>
      (await api.post(
        '/portfolio/position/purchase',
        toTradePayload(data),
      )) as unknown as PurchaseRecord,
    onSuccess: (record) => {
      toast.success(`买入成功，确认份额 ${record.shares.toFixed(2)}`);
      queryClient.invalidateQueries({ queryKey: ['positions'] });
      queryClient.invalidateQueries({ queryKey: ['position-transactions'] });
      queryClient.invalidateQueries({ queryKey: ['position'] });
    },
  });
};

/** 清空回执:后端按表返回实际清除条数(一/二级才会带持仓与流水条数) */
export type ClearResult = {
  snapshotsDeleted: number;
  cashFlowsDeleted: number;
  positionsDeleted?: number;
  purchasesDeleted?: number;
  redemptionsDeleted?: number;
};

/**
 * 一级:清空全部买卖流水 —— 连带清空持仓与快照/现金流,不可恢复。
 * toast 带上各表实际条数:只说「已清空」会让人低估这次操作的影响面。
 */
export const useDeleteAllTransactions = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      (await api.delete(
        '/portfolio/position/transactions',
      )) as unknown as ClearResult,
    onSuccess: (result) => {
      toast.success(
        `已清空 ${result.purchasesDeleted ?? 0} 条买入 / ${result.redemptionsDeleted ?? 0} 条赎回 / ${result.positionsDeleted ?? 0} 条持仓 / ${result.snapshotsDeleted} 条快照`,
      );
      queryClient.invalidateQueries({ queryKey: ['positions'] });
      queryClient.invalidateQueries({ queryKey: ['position-transactions'] });
      queryClient.invalidateQueries({ queryKey: ['position'] });
      queryClient.invalidateQueries({ queryKey: ['snapshots'] });
    },
  });
};

/**
 * 单条硬删除交易记录(source 区分买卖两侧端点;后端删除后连带快照全量重建,
 * 删除记录的持仓空壳会被物理清理、剩余份额回正的软删持仓会被复活)。
 */
export const useDeleteTransaction = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (tx: {
      source: 'purchase' | 'redemption';
      recordId: number;
    }) =>
      (await api.delete(
        `/portfolio/position/transactions/${tx.source}/${tx.recordId}`,
      )) as unknown as void,
    onSuccess: () => {
      toast.success('记录已删除');
      queryClient.invalidateQueries({ queryKey: ['positions'] });
      queryClient.invalidateQueries({ queryKey: ['position-transactions'] });
      queryClient.invalidateQueries({ queryKey: ['position'] });
      queryClient.invalidateQueries({ queryKey: ['snapshots'] });
    },
  });
};

/**
 * 导出交易记录:与导入模板同列形(表头由解析器同源生成),导出文件可直接回导;
 * blob 下载,中文文件名前端落盘时指定(理由同导入模板)。
 */
export const useExportTransactions = () =>
  useMutation({
    mutationFn: async () => {
      const blob = (await api.get('/portfolio/excel/transactions', {
        responseType: 'blob',
        timeout: 60_000,
      })) as unknown as Blob;
      saveBlob(blob, '交易记录.xlsx');
    },
    // 成功不弹 toast:浏览器下载提示已足够;失败必须说一声
    onError: () => toast.warning('导出失败，请稍后重试'),
  });

/**
 * 从交易记录重建持仓:头表全删按日期升序重放流水,份额金额不变、position_id 重挂。
 * 二级清空后流水悬空的修复入口;后端成功后连带快照全量重建(失败随 payload 提示)。
 */
export const useRebuildPositions = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      (await api.post(
        '/portfolio/position/rebuild-from-transactions',
      )) as unknown as {
        positionsCreated: number;
        recordsRelinked: number;
        snapshotRebuilt: boolean;
        snapshotMessage: string;
        errors: { fundCode: string; error: string }[];
      },
    onSuccess: (result) => {
      toast.success(
        `已从 ${result.recordsRelinked} 条交易记录重建 ${result.positionsCreated} 个持仓`,
        {
          description: result.snapshotRebuilt
            ? undefined
            : result.snapshotMessage,
        },
      );
      queryClient.invalidateQueries({ queryKey: ['positions'] });
      queryClient.invalidateQueries({ queryKey: ['position-transactions'] });
      queryClient.invalidateQueries({ queryKey: ['position'] });
      queryClient.invalidateQueries({ queryKey: ['snapshots'] });
    },
  });
};

/** 二级:清空全部持仓 —— 连带清空快照/现金流,买卖流水保留(历史收益仍可追溯) */
export const useDeleteAllPositions = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      (await api.delete('/portfolio/position/all')) as unknown as ClearResult,
    onSuccess: (result) => {
      toast.success(
        `已清空 ${result.positionsDeleted ?? 0} 条持仓 / ${result.snapshotsDeleted} 条快照(买卖流水保留)`,
      );
      queryClient.invalidateQueries({ queryKey: ['positions'] });
      queryClient.invalidateQueries({ queryKey: ['position-transactions'] });
      queryClient.invalidateQueries({ queryKey: ['position'] });
      queryClient.invalidateQueries({ queryKey: ['snapshots'] });
    },
  });
};

/** 赎回(全额赎回时后端自动软删持仓,列表里自然消失,前端不额外跳转) */
export const useRedeemPosition = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (data: RedeemInput) =>
      (await api.post(
        '/portfolio/position/redeem',
        toTradePayload(data),
        // 赎回端点同步做净值回源(货基首访拉全量收益序列)+快照回填,是合法慢路径;
        // 全局 30s 超时会丢响应造成「结果未知」,放宽到与基金信息全量同步一致的 120s
        { timeout: 120_000 },
      )) as unknown as RedemptionRecord,
    onSuccess: (record) => {
      toast.success(`赎回成功，到账金额 ${record.totalAmount.toFixed(2)}`);
      queryClient.invalidateQueries({ queryKey: ['positions'] });
      queryClient.invalidateQueries({ queryKey: ['position-transactions'] });
      queryClient.invalidateQueries({ queryKey: ['position'] });
    },
  });
};

// src/features/statement-import/api/statement-import.ts —— 交易导入数据层
// 契约要点(对应后端 statement_import_service / excel_vo,2026-09-17):
// - preview 走 multipart/form-data,字段名 file;api-client 的请求拦截器只设 Accept 与 Authorization,
//   传 FormData 时 axios 会自动补 boundary —— 手设 Content-Type 反而会丢 boundary 导致 422。
// - confirm 是 JSON 且字段必须驼峰(后端 VO 用 to_camel),type 传中文「买入/赎回」(preview 行原样回传)。
// - 两个响应都走 data 通道,信封被剥后全局拦截器读不到 msg → 回执 toast 必须在 onSuccess 里局部发。
// - confirm 外层信封 success 恒为 true,业务成功位在内层 data.success(用户取消/落库前校验拦截/成功三分支)。
import {
  useMutation,
  useMutationState,
  useQueryClient,
} from '@tanstack/react-query';
import { toast } from 'sonner';

import { api } from '@/lib/api-client';
import { saveBlob } from '@/lib/download';

/**
 * 导入这两个接口单独放宽到 10 分钟（覆盖 api-client 的全局 30s）。
 * 理由：大对账单解析慢——实测 78 页 / 0.9MB 的文本层 PDF 读取就要 7.6s（逐页解析表格），
 * 扫描件按页 OCR 更久；给大文件留足时间，别在 30s 处把请求掐断。
 * 注：api-client 的重试只按「有没有 response」判定，超时同样没有 response，
 * 所以超时后仍会被重发（最多 2 次）；这里的意义是「让大文件有机会跑完」。
 */
const STATEMENT_IMPORT_TIMEOUT_MS = 10 * 60 * 1000;

// ===== 类型 =====

/** preview 单行(预览行原样回传即可作为 confirm 的 records 元素) */
export type StatementPreviewRow = {
  /** 来源行号(Excel 是工作表行号、PDF 是表内行序、OCR 是网格行序);判不出时为 null */
  row: number | null;
  /** 后端已归一成中文 */
  type: '买入' | '赎回';
  /**
   * 分红行才有值,非分红行为空串:账本没有独立的分红表(分红就落在买入/赎回表里),
   * 类型列靠它显示「红利再投资 / 现金分红」标签,确认时也原样回传给后端写进备注。
   */
  dividend: '红利再投资' | '现金分红' | '';
  fundCode: string;
  fundName: string;
  /** yyyy-MM-dd;解析不出时为 null(该行会被校验层拦成 error) */
  date: string | null;
  amount: number;
  shares: number;
  unitPrice: number;
  fee: number;
  orderNo: string | null;
  status: 'pending';
  /** 来源可追溯:页码 / 解析层 / 置信度 / 命中的平台适配器 */
  page: number | null;
  layer: 'text' | 'ocr';
  confidence: number;
  adapter: string;
  /** 净值未发布、份额待确认(列表式截图):该行 shares/unitPrice 为 0,只按 amount 落库 */
  navPending: boolean;
  /** 基金代码的解析依据 / 候选清单(列表式截图);表格式明细为空串 */
  resolveNote: string;
};

/** 分级校验问题;warnings[] 元素同时带 error 与 warning 两个键(值相同),统一读 error */
export type StatementIssue = {
  error: string;
  row: number | null;
  field: string;
  page: number | null;
  warning?: string;
};

export type StatementPreviewSummary = {
  purchases: number;
  redemptions: number;
  total: number;
  warnings: number;
  /** 命中的平台适配器(key 与中文名)、抽取模式与文件类型;kinds 同时反映是否走了 OCR */
  adapter: string;
  adapterName: string;
  /** 抽取模式:表头映射 / 卡片式逐块 / 列表式逐条 */
  mode: 'table' | 'labelValue' | 'listItem';
  kind: 'excel' | 'pdf' | 'image';
  ocrUsed: boolean;
  /** 解析出的原始条数(未被校验剔除前),用于解释"为什么预览比解析少" */
  parsed: number;
};

export type StatementPreviewResult = {
  preview: StatementPreviewRow[];
  summary: StatementPreviewSummary;
  errors: StatementIssue[];
  warnings: StatementIssue[];
};

/** confirm 单条记录(只取后端 ImportTransactionRecordModel 认的字段) */
export type StatementConfirmRecord = {
  fundCode: string;
  fundName: string;
  date: string | null;
  type: '买入' | '赎回';
  /** 分红行标签:后端据此把「| 红利再投资 / | 现金分红」写进落库备注(账本靠备注区分分红) */
  dividend?: '红利再投资' | '现金分红' | '';
  amount: number;
  shares: number;
  unitPrice: number;
  fee: number;
  orderNo: string | null;
};

export type StatementConfirmResult = {
  /** 内层业务成功位:false = 用户取消或被落库前校验拦截(此时一个字节都没写) */
  success: boolean;
  /** skipped = 同平台判重丢弃的条数(库里已有记录与手输记录都保留,只追加真正的新记录) */
  imported:
    | { purchases: number; redemptions: number; skipped?: number }
    | Record<string, never>;
  positionsCreated: number;
  /**
   * 快照是否随本次导入重建成功。false = 记录已入库但快照没跟上(重建被占用且重试耗尽),
   * 界面必须提示手动重建一次;可选字段:旧后端不返回时按"已重建"处理,不弹提示。
   */
  snapshotRebuilt?: boolean;
  /** 未重建时的可读说明(取自后端回执);缺省时前端用兜底文案 */
  snapshotRebuildMessage?: string;
  /**
   * 三分支形状不同:取消 → [{error}];校验拦截 → [{error,row,field,page}];
   * 成功 → 逐条建仓失败 [{fund_code,error}]
   */
  errors: Array<{
    error: string;
    row?: number | null;
    field?: string;
    page?: number | null;
    fund_code?: string;
  }>;
};

// ===== 选文件时的客户端软提示 =====

/** 逗号分隔的 accept(仅影响系统选文件对话框的默认过滤) */
export const STATEMENT_IMPORT_ACCEPT = '.xlsx,.pdf,.png,.jpg,.jpeg';

/** 超过该体积只提醒不拦截:后端无字节上限,但解析耗时随体积增长 */
const LARGE_FILE_BYTES = 20 * 1024 * 1024;

const ALLOWED_EXTENSIONS = ['xlsx', 'pdf', 'png', 'jpg', 'jpeg'];

export type FileNotice = { level: 'warning' | 'info'; message: string };

/**
 * 软提示:后端按内容魔数判定类型,所以这里只给文案、不拦提交;
 * 唯一值得提前说的是 .xls —— Excel 97-2003 二进制后端明确拒绝,另存为 .xlsx 即可。
 */
export const describeFileNotice = (file: File): FileNotice | null => {
  const extension = file.name.split('.').pop()?.toLowerCase() ?? '';
  if (extension === 'xls') {
    return {
      level: 'warning',
      message: 'Excel 97-2003 的 .xls 无法解析，请另存为 .xlsx 后重试',
    };
  }
  if (file.size === 0) {
    return { level: 'warning', message: '文件内容为空，请重新选择' };
  }
  if (!ALLOWED_EXTENSIONS.includes(extension)) {
    return {
      level: 'info',
      message: `扩展名 .${extension || '(无)'} 不在常见列表（.xlsx / PDF / PNG / JPEG），仍会按内容尝试解析`,
    };
  }
  if (file.size > LARGE_FILE_BYTES) {
    return { level: 'info', message: '文件较大，解析可能需要更久' };
  }
  return null;
};

/** preview 行 → confirm 记录:只保留后端认的字段;错误行由页面在勾选阶段就排除 */
export const toConfirmRecords = (
  rows: StatementPreviewRow[],
): StatementConfirmRecord[] =>
  rows.map(
    ({
      fundCode,
      fundName,
      date,
      type,
      dividend,
      amount,
      shares,
      unitPrice,
      fee,
      orderNo,
    }) => ({
      fundCode,
      fundName,
      date,
      type,
      dividend,
      amount,
      shares,
      unitPrice,
      fee,
      orderNo,
    }),
  );

// ===== 变更 =====

/**
 * 解析预览:选文件不自动触发,由用户点「解析并预览」——
 * preview 限流 12 次/120 秒,连点会把配额烧光。
 */
export const usePreviewStatementImport = () =>
  useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append('file', file);
      // 刻意不设 Content-Type:交给 axios 按 FormData 自动补 boundary
      return (await api.post(
        '/portfolio/import/transactions/preview',
        formData,
        { timeout: STATEMENT_IMPORT_TIMEOUT_MS },
      )) as unknown as StatementPreviewResult;
    },
    // 成功不弹 toast:页面随即切到预览态并展示统计与问题清单,再弹一次是重复提示
  });

/**
 * 下载导入模板:模板由后端用**解析器支持的语义表头**生成(xlsx),所以按 blob 取;
 * 中文文件名在前端落盘时指定(响应头只给 ASCII 名,免得依赖各浏览器对 filename* 的支持)。
 */
export const useDownloadStatementTemplate = () =>
  useMutation({
    mutationFn: async () => {
      const blob = (await api.get('/portfolio/import/transactions/template', {
        responseType: 'blob',
        timeout: 60_000,
      })) as unknown as Blob;
      saveBlob(blob, '交易记录导入模板.xlsx');
    },
    // 成功不弹 toast:浏览器自身的下载提示已足够;失败必须说一声(否则用户以为点了没反应)
    onError: () => toast.warning('模板下载失败，请稍后重试'),
  });

/** 确认导入的 mutation key:让「是否正在导入」能在组件之外(跨挂载)被读到 */
export const STATEMENT_IMPORT_CONFIRM_KEY = [
  'statement-import-confirm',
] as const;

/** confirm 入参:fileName 只给进度面板显示用(切页回来后文件已不在本地 state),不发给后端 */
export type StatementConfirmPayload = {
  adapter: string;
  records: StatementConfirmRecord[];
  fileName: string;
};

/**
 * 确认导入:只提交勾选行;落库前后端会再校验一次,有 error 级问题整批拒收(内层 success=false)。
 * confirm **按平台累加**:同平台已导入过的记录判重跳过,其它平台与手输记录一律保留,随后全量重建
 * 持仓并补建快照——平台作用域取自本次预览的 `summary.adapter`,故调用方必须把它带上。
 */
export const useConfirmStatementImport = () => {
  const queryClient = useQueryClient();
  return useMutation({
    // 带 key 才能被 useStatementImportState 跨挂载筛选到
    mutationKey: STATEMENT_IMPORT_CONFIRM_KEY,
    mutationFn: async (payload: StatementConfirmPayload) =>
      // 与 preview 同一口径:一次导入上千条会连带重建持仓与快照,同样给足 10 分钟
      (await api.post(
        '/portfolio/import/transactions/confirm',
        {
          confirmed: true,
          adapter: payload.adapter,
          records: payload.records,
        },
        { timeout: STATEMENT_IMPORT_TIMEOUT_MS },
      )) as unknown as StatementConfirmResult,
    onSuccess: (result) => {
      if (!result.success) {
        toast.warning(
          result.errors[0]?.error ?? '导入未完成，请检查记录后重试',
        );
        return;
      }
      const imported = result.imported as {
        purchases?: number;
        redemptions?: number;
        skipped?: number;
      };
      const skipped = imported.skipped ?? 0;
      toast.success(
        `导入完成：新增买入 ${imported.purchases ?? 0} 条 / 赎回 ${imported.redemptions ?? 0} 条` +
          (skipped > 0 ? `，跳过 ${skipped} 条同平台重复` : '') +
          `，新建持仓 ${result.positionsCreated} 个`,
      );
      // 记录已入库、快照却没重建(重建被并发占用且重试耗尽):必须让使用者知道要手动重建,
      // 否则收益曲线会停在旧份额上、界面上毫无提示(2026-09-20 实测踩过这条)
      if (result.snapshotRebuilt === false) {
        toast.warning(
          result.snapshotRebuildMessage ??
            '记录已入库，但历史持仓未重建：请到「历史持仓」页点一次「重建记录」，否则收益曲线会停在旧份额上',
        );
      }
      // 导入重建了持仓与流水,后端随后又补建了快照 → 三处读路径一并失效
      queryClient.invalidateQueries({ queryKey: ['positions'] });
      queryClient.invalidateQueries({ queryKey: ['position-transactions'] });
      queryClient.invalidateQueries({ queryKey: ['snapshots'] });
    },
  });
};

/**
 * 「是否正在导入 / 本次导入回执」的唯一真相来源:读全局 mutation 缓存,而不是组件本地 state。
 *
 * 为什么:切菜单会让路由组件卸载,本地 state 全丢,而请求仍在后台跑 —— 于是「选择文件」又能点了
 * (2026-09-21 实测踩到)。mutation 在缓存里活得比组件久、也不会因卸载被取消,所以任何一次挂载
 * 读到的都是同一份真相:只要请求没结束,页面就一直处于"占用期"。
 */
export const useStatementImportState = () => {
  const states = useMutationState({
    filters: { mutationKey: STATEMENT_IMPORT_CONFIRM_KEY, exact: true },
    // select 直接回 m.state(稳定引用):改成新建对象字面量会让每次渲染都判定为变了
    select: (mutation) => mutation.state,
  });
  const latest = states[states.length - 1];
  const variables = latest?.variables as StatementConfirmPayload | undefined;

  return {
    /** 请求进行中(含离开页面期间):true 时页面只能显示进度面板 */
    importing: latest?.status === 'pending',
    /** 已结束的成功回执(内层 success=false 也在这里,由完成页显示红字说明) */
    result:
      latest?.status === 'success'
        ? (latest.data as StatementConfirmResult)
        : null,
    /** 进度面板要显示的文件名/条数:取自 mutation 变量,所以切页回来仍在 */
    fileName: variables?.fileName ?? '',
    recordCount: variables?.records.length ?? 0,
  };
};

/**
 * 格式化日期为短日期字符串（如 "2026-08-28"）
 * 与 DateField 日历选择器的值格式/后端 filters 契约保持一致
 * @param date - 日期字符串、时间戳或 Date 对象
 */
export const formatDate = (date: string | number | Date): string => {
  const d = new Date(date);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

/**
 * 盈亏数值着色类名：红涨绿跌（--profit/--loss 语义 token，与仪表盘同口径），零值不着色
 */
export const profitClass = (value: number): string =>
  value > 0 ? 'text-profit' : value < 0 ? 'text-loss' : '';

/**
 * 涨跌文字色（零值走浅灰）：用于副标题等零值需要中性灰而非透明色的场景
 */
export const trendClass = (value: number): string =>
  value > 0 ? 'text-profit' : value < 0 ? 'text-loss' : 'text-muted-foreground';

/**
 * 涨跌色 token（图表描边/填充用，零值浅灰）
 */
export const trendColor = (value: number): string =>
  value > 0
    ? 'var(--color-profit)'
    : value < 0
      ? 'var(--color-loss)'
      : 'var(--muted-foreground)';

/**
 * 千分位数值（两位小数，不含货币符号）
 */
export const formatNumber = (value: number): string =>
  value.toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

/**
 * 金额（¥ + 千分位，两位小数）；负数表现为 ¥-12.34
 */
export const formatMoney = (value: number): string => `¥${formatNumber(value)}`;

/**
 * 四位小数单价（千分位，不含货币符号）：基金净值/平均成本价的展示口径
 */
export const formatUnitPrice = (value: number): string =>
  value.toLocaleString('zh-CN', {
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  });

/**
 * 带符号数值（千分位，两位小数，不含货币符号）：正数补 +，零与负数原样
 */
export const signedNum = (value: number): string =>
  `${value > 0 ? '+' : ''}${formatNumber(value)}`;

/**
 * 带符号百分比（两位小数）：正数补 +，零不加符号；百分比不加千分位（贴合读数习惯）
 */
export const signedPct = (value: number): string =>
  `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;

/**
 * 带符号金额：正数补 +（¥ 紧随其后）
 */
export const signedMoney = (value: number): string =>
  `${value > 0 ? '+' : ''}${formatMoney(value)}`;

/**
 * 文件体积（B / KB / MB，一位小数）
 * 收口在 format.ts 而不是页面里：文件卡片描述与"文件较大"软提示共用同一套口径
 */
export const formatFileSize = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

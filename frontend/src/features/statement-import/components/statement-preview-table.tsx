// src/features/statement-import/components/statement-preview-table.tsx —— 待提交记录表
// 行标识用 preview 数组下标而不是 row:一张 PDF 里每张表的行号都从 1 起,跨表会撞号。
// 有告警的行整行淡黄底 + 行末提醒图标(Tooltip 给原因):提示归提示,勾选权仍在用户手里。
import { FileWarningIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import type { StatementPreviewRow } from '@/features/statement-import/api/statement-import';
import { cn } from '@/utils/cn';
import { formatMoney, formatNumber } from '@/utils/format';

// 买卖用显式色而不是 --profit/--loss 语义 token:那对 token 在本仓表示「涨/跌」,
// 拿来涂申购/赎回会让「红=买入」与「红=浮盈」撞车。
const TYPE_STYLE: Record<StatementPreviewRow['type'], string> = {
  买入: 'border-destructive/30 text-destructive',
  赎回: 'border-emerald-600/30 text-emerald-600',
};

// 分红行单独一套色:账本没有独立分红表(分红落在买入/赎回表里),这两枚标签就是它在预览页的身份。
// 红利再投资 = 份额涨、钱不动(琥珀);现金分红 = 钱到手、份额不动(天蓝)。
const DIVIDEND_STYLE: Record<'红利再投资' | '现金分红', string> = {
  红利再投资: 'border-amber-600/30 text-amber-600',
  现金分红: 'border-sky-600/30 text-sky-600',
};

type StatementPreviewTableProps = {
  /** 当前页已切片的行 */
  rows: StatementPreviewRow[];
  /** 当前页首行在完整 preview 数组里的下标 */
  rowOffset: number;
  isSelected: (index: number) => boolean;
  /** 下标 → 该行告警原因(可能多条) */
  warningsByIndex: Map<number, string[]>;
  onToggleRow: (index: number) => void;
  onToggleAll: (checked: boolean) => void;
  headerChecked: boolean | 'indeterminate';
};

export function StatementPreviewTable({
  rows,
  rowOffset,
  isSelected,
  warningsByIndex,
  onToggleRow,
  onToggleAll,
  headerChecked,
}: StatementPreviewTableProps) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader className="bg-muted">
          <TableRow>
            <TableHead className="w-10">
              <Checkbox
                checked={headerChecked}
                onCheckedChange={(checked) => onToggleAll(checked === true)}
                aria-label="全选或全不选本页可提交记录"
              />
            </TableHead>
            <TableHead className="w-20">类型</TableHead>
            <TableHead className="min-w-48">基金</TableHead>
            <TableHead className="w-28">日期</TableHead>
            <TableHead className="w-28 text-right">金额</TableHead>
            <TableHead className="w-28 text-right">份额</TableHead>
            <TableHead className="w-24 text-right">单价</TableHead>
            <TableHead className="w-20 text-right">手续费</TableHead>
            <TableHead className="w-36">订单号</TableHead>
            <TableHead className="w-28">来源</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, offset) => {
            const index = rowOffset + offset;
            const warnings = warningsByIndex.get(index) ?? [];
            return (
              <TableRow
                key={index}
                data-state={isSelected(index) ? 'selected' : undefined}
                className={cn(
                  'animate-in fade-in-0 fill-mode-both duration-150 motion-reduce:animate-none',
                  warnings.length > 0 && 'bg-amber-50/60',
                )}
                // 延迟封顶:一页几十行时不让最后一行等太久
                style={{
                  animationDelay: `${Math.min(offset, 8) * 20}ms`,
                }}
              >
                <TableCell>
                  <Checkbox
                    checked={isSelected(index)}
                    onCheckedChange={() => onToggleRow(index)}
                    aria-label={`选择第 ${row.row ?? index + 1} 行记录`}
                  />
                </TableCell>
                <TableCell>
                  <Badge
                    variant="outline"
                    className={
                      row.dividend
                        ? DIVIDEND_STYLE[row.dividend]
                        : TYPE_STYLE[row.type]
                    }
                  >
                    {row.dividend || row.type}
                  </Badge>
                </TableCell>
                <TableCell>
                  <span className="block font-medium">
                    {row.fundName || '—'}
                  </span>
                  <span className="text-muted-foreground block text-xs tabular-nums">
                    {row.fundCode}
                  </span>
                </TableCell>
                <TableCell className="tabular-nums">
                  {row.date ?? '—'}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatMoney(row.amount)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {row.navPending ? (
                    <span className="text-muted-foreground">待确认</span>
                  ) : (
                    formatNumber(row.shares)
                  )}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {row.navPending ? (
                    <span className="text-muted-foreground">待确认</span>
                  ) : (
                    formatNumber(row.unitPrice)
                  )}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {row.fee ? formatNumber(row.fee) : '—'}
                </TableCell>
                <TableCell className="text-muted-foreground text-xs">
                  {row.orderNo ?? '—'}
                </TableCell>
                <TableCell className="text-muted-foreground text-xs whitespace-nowrap">
                  {row.row == null ? '—' : `第 ${row.row} 行`}
                  {row.page == null ? '' : ` · 第 ${row.page} 页`}
                  {warnings.length > 0 ? (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <FileWarningIcon className="ml-1 inline size-3.5 text-amber-600" />
                      </TooltipTrigger>
                      <TooltipContent>
                        <ul className="flex flex-col gap-0.5">
                          {warnings.map((reason, reasonIndex) => (
                            <li key={reasonIndex}>{reason}</li>
                          ))}
                        </ul>
                      </TooltipContent>
                    </Tooltip>
                  ) : null}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

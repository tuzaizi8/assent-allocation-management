// 持仓交易记录时间轴 —— 明细抽屉共用:买入/赎回合并按时间正序混排,Badge 区分交易类型;
// 所选日期净值未发布的交易 status='0' 待确认:份额/净值依赖该净值显示「🕒 待确认」徽章,
// 买入的金额录入时已确定照常显示数字,赎回的到账金额(=份额×未发布净值)确实未定也用徽章。
// 净值 T+1 发布后由后端懒确认回填,届时徽章自动变数值。
import { ClockIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import type {
  PurchaseRecord,
  RedemptionRecord,
} from '@/features/positions/api/get-positions';

/** 合并后的统一交易行(type 为后端直出的中文,与交易记录页同口径) */
type TransactionRow = {
  type: '买入' | '赎回';
  date: string;
  shares: number;
  price: number;
  amount: number;
  /** '0'=待确认(所选日期净值未公布):份额/净值依赖该净值 */
  pending: boolean;
  remark: string | null;
};

export function TransactionHistory({
  purchases,
  redemptions,
}: {
  purchases: PurchaseRecord[];
  redemptions: RedemptionRecord[];
}) {
  const rows: TransactionRow[] = [
    ...purchases.map((p) => ({
      type: '买入' as const,
      date: p.purchaseDate,
      shares: p.shares,
      price: p.costPrice,
      // 待确认时 totalCost 是 shares×costPrice=0 假数值,真实金额是用户输入的 amount
      amount: p.status === '0' ? (p.amount ?? 0) : p.totalCost,
      pending: p.status === '0',
      remark: p.remark,
    })),
    ...redemptions.map((r) => ({
      type: '赎回' as const,
      date: r.redemptionDate,
      shares: r.shares,
      price: r.navPrice,
      amount: r.totalAmount,
      pending: r.status === '0',
      remark: r.remark,
    })),
    // ISO 日期字符串字典序即时间序,sort 默认稳定不搅乱同日先后
  ].sort((a, b) => a.date.localeCompare(b.date));

  return (
    <div className="col-span-2 flex flex-col gap-2">
      <span className="text-muted-foreground">交易记录</span>
      {rows.length === 0 ? (
        <span className="text-sm">-</span>
      ) : (
        <div className="divide-y rounded-md border text-sm">
          {rows.map((row, index) => (
            <div
              // 同一行来源唯一(单条买入/赎回记录),以类型+日期+序号保 key 稳定
              key={`${row.type}-${row.date}-${index}`}
              className="flex items-center justify-between gap-2 px-3 py-2"
            >
              <Badge variant={row.type === '买入' ? 'secondary' : 'outline'}>
                {row.type}
              </Badge>
              <span className="tabular-nums">{row.date}</span>
              {row.pending ? (
                // 待确认:份额/净值依赖所选日期的净值,发布前不可知
                <>
                  <span className="text-muted-foreground text-xs">—</span>
                  <span className="text-muted-foreground text-xs">—</span>
                  <Badge
                    className="border-amber-500 text-amber-600"
                    variant="outline"
                  >
                    <ClockIcon className="size-3" />
                    待确认
                  </Badge>
                </>
              ) : (
                <>
                  <span className="tabular-nums">
                    {row.shares.toFixed(2)} 份
                  </span>
                  <span className="tabular-nums">@{row.price.toFixed(4)}</span>
                  <span className="tabular-nums">{row.amount.toFixed(2)}</span>
                </>
              )}
              <span className="text-muted-foreground truncate">
                {row.remark ?? '-'}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

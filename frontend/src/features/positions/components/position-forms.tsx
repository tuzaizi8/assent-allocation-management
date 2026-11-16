// 持仓写操作表单(建仓/买入/赎回)
// 收在 feature 内:页面文件只留表格与弹层编排,表单可独立演进
// 金额与份额在表单态按字符串收(Input 的原生值),提交前经 schema.parse 转数字——
// 若直接让 zod coerce 进表单态,空输入会落成 0 或 NaN,既污染默认值又换来难读的报错
// 日期字段走共享的 DateField(shadcn 日历):不用系统原生 date 控件,免得同一页两套控件形态
import { zodResolver } from '@hookform/resolvers/zod';
import { Loader2 } from 'lucide-react';
import { useForm } from 'react-hook-form';

import { DateField } from '@/components/shared/date-field';
import { Button } from '@/components/ui/button';
import { DialogFooter } from '@/components/ui/dialog';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { FundCombobox } from '@/features/funds/components/fund-combobox';
import {
  redeemSchema,
  toTradePayload,
  tradeSchema,
  useAddPurchase,
  useCreatePosition,
  type PositionDetail,
  type RedeemInput,
  type TradeInput,
} from '@/features/positions/api/get-positions';
import { formatDate } from '@/utils/format';

/** 表单态:数值字段保持字符串,与 Input 的原生值一致 */
type TradeValues = Omit<TradeInput, 'amount'> & { amount: string };
type RedeemValues = Omit<RedeemInput, 'shares'> & { shares: string };

/** 本地时区的 yyyy-MM-dd(后端 Pydantic date 直吃该格式) */
const todayISO = () => formatDate(new Date());

/**
 * 建仓与买入共用一套字段(后端两个 VO 同构),仅提交端点与按钮文案不同:
 * 建仓遇已持仓会 601 拒绝,买入则追加。份额由后端按买入日净值换算,前端不传份额。
 */
export function TradeForm({
  mode,
  onDone,
}: {
  mode: 'create' | 'purchase';
  onDone: (open: boolean) => void;
}) {
  const createPosition = useCreatePosition();
  const addPurchase = useAddPurchase();
  const mutation = mode === 'create' ? createPosition : addPurchase;
  const form = useForm<TradeValues>({
    resolver: zodResolver(tradeSchema),
    defaultValues: {
      fundCode: '',
      amount: '',
      purchaseDate: todayISO(),
      afterCutoff: false,
      remark: '',
    },
  });

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit((values) => {
          const input = tradeSchema.parse(values);
          mutation.mutate(toTradePayload(input), {
            onSuccess: () => onDone(false),
          });
        })}
        className="space-y-4"
      >
        <FormField
          control={form.control}
          name="fundCode"
          render={({ field }) => (
            <FormItem>
              <FormLabel>基金</FormLabel>
              <FormControl>
                <FundCombobox
                  onChange={(fund) => field.onChange(fund?.code ?? '')}
                  className="rounded-md border"
                  listClassName="max-h-40"
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="amount"
          render={({ field }) => (
            <FormItem>
              <FormLabel>购买金额(元)</FormLabel>
              <FormControl>
                <Input
                  type="number"
                  step="0.01"
                  min="0"
                  placeholder="如 1000"
                  {...field}
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="purchaseDate"
          render={({ field }) => (
            <FormItem>
              <FormLabel>买入日期</FormLabel>
              <FormControl>
                {/* 不写 id:由 FormControl 注入,FormLabel 的 htmlFor 才对得上 */}
                <DateField
                  value={field.value}
                  onChange={(value) => field.onChange(value)}
                  placeholder="选择日期"
                  className="w-full"
                  size="default"
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        {/* 下单时点:15:00 是基金收盘线,之后下单按下一交易日净值成交(与截图导入同一条线) */}
        <FormField
          control={form.control}
          name="afterCutoff"
          render={({ field }) => (
            <FormItem className="flex flex-row items-center justify-between rounded-lg border p-3">
              <div className="space-y-0.5">
                <FormLabel>15:00 之后下单</FormLabel>
                <p className="text-muted-foreground text-xs">
                  开启后按<b>下一交易日</b>
                  净值换算份额（非交易日继续顺延）；15:00 前提交按当日净值。
                </p>
              </div>
              <FormControl>
                <Switch
                  checked={field.value}
                  onCheckedChange={field.onChange}
                  aria-label="15:00 之后下单"
                />
              </FormControl>
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="remark"
          render={({ field }) => (
            <FormItem>
              <FormLabel>备注(选填)</FormLabel>
              <FormControl>
                <Textarea {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <DialogFooter>
          <Button
            type="submit"
            className="flex-1"
            disabled={mutation.isPending}
          >
            {mutation.isPending && <Loader2 className="animate-spin" />}
            {mode === 'create' ? '建仓' : '买入'}
          </Button>
          <Button
            type="button"
            variant="outline"
            className="flex-1"
            disabled={mutation.isPending}
            onClick={() => onDone(false)}
          >
            取消
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}

/**
 * 赎回表单。后端按份额赎回(不接受金额),且会校验不超持有份额、不早于首次买入日,
 * 超额与日期倒挂都由后端 601 拦下,前端只做非空与正数校验。
 * 提交不直接发请求:先交给页面的确认弹窗复核基金/份额/日期。
 */
export function RedeemForm({
  position,
  onSubmit,
  onDone,
}: {
  position: PositionDetail;
  onSubmit: (values: RedeemInput) => void;
  onDone: (open: boolean) => void;
}) {
  const form = useForm<RedeemValues>({
    resolver: zodResolver(redeemSchema),
    defaultValues: {
      fundCode: position.fundCode,
      shares: '',
      redemptionDate: todayISO(),
      afterCutoff: false,
      remark: '',
    },
  });

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit((values) =>
          onSubmit(redeemSchema.parse(values)),
        )}
        className="space-y-4"
      >
        <div className="flex flex-col gap-1 text-sm">
          <span className="text-muted-foreground">赎回基金</span>
          <span>
            {position.fundName}（{position.fundCode}）
          </span>
          <span className="text-muted-foreground text-xs">
            当前持有 {position.totalShares.toFixed(4)} 份
          </span>
        </div>
        <FormField
          control={form.control}
          name="shares"
          render={({ field }) => (
            <FormItem>
              <FormLabel>赎回份额</FormLabel>
              <FormControl>
                <Input
                  type="number"
                  step="0.0001"
                  min="0"
                  placeholder="如 500"
                  {...field}
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="redemptionDate"
          render={({ field }) => (
            <FormItem>
              <FormLabel>赎回日期</FormLabel>
              <FormControl>
                {/* 不写 id:由 FormControl 注入,FormLabel 的 htmlFor 才对得上 */}
                <DateField
                  value={field.value}
                  onChange={(value) => field.onChange(value)}
                  placeholder="选择日期"
                  className="w-full"
                  size="default"
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        {/* 同买入:15:00 后下单按下一交易日净值,影响到账金额与份额扣减日 */}
        <FormField
          control={form.control}
          name="afterCutoff"
          render={({ field }) => (
            <FormItem className="flex flex-row items-center justify-between rounded-lg border p-3">
              <div className="space-y-0.5">
                <FormLabel>15:00 之后下单</FormLabel>
                <p className="text-muted-foreground text-xs">
                  开启后按<b>下一交易日</b>净值成交（非交易日继续顺延）；15:00
                  前提交按当日净值。
                </p>
              </div>
              <FormControl>
                <Switch
                  checked={field.value}
                  onCheckedChange={field.onChange}
                  aria-label="15:00 之后下单"
                />
              </FormControl>
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="remark"
          render={({ field }) => (
            <FormItem>
              <FormLabel>备注(选填)</FormLabel>
              <FormControl>
                <Textarea {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <DialogFooter>
          <Button type="submit" variant="destructive" className="flex-1">
            赎回
          </Button>
          <Button
            type="button"
            variant="outline"
            className="flex-1"
            onClick={() => onDone(false)}
          >
            取消
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}

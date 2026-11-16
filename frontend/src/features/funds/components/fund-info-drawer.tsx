// 基金详情抽屉 —— 基金管理页/持仓明细页的名称点击共用:展示同花顺档案全量键值
// 数据经 useFundInfo 按需单查(后端三级缓存),loading 态由 DetailDrawer 的 prop 承担
import { DetailDrawer, DetailField } from '@/components/shared/detail-drawer';
import {
  HIDDEN_FUND_INFO_FIELDS,
  useFundInfo,
} from '@/features/funds/api/get-fund-info';

// 首屏展示优先级最高的字段排前(源站字段名可能变动,列表中不存在的自动跳过)
const PRIORITY_FIELDS = [
  '基金代码',
  '基金类型',
  '基金全称',
  '投资类型',
  '基金经理',
  '成立日期',
];

export function FundInfoDrawer({
  fundCode,
  onOpenChange,
}: {
  /** null = 关闭(不发请求) */
  fundCode: string | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { data: info, isLoading } = useFundInfo(fundCode);

  // 已知字段排前、其余按源站返回顺序追加,保证全量可见且常用项不沉底;
  // 隐藏字段不追加(只从 PRIORITY_FIELDS 里删 = 它沉到列表末尾继续出现)
  const orderedEntries = info
    ? [
        ...PRIORITY_FIELDS.filter((key) => key in info).map(
          (key) => [key, info[key]] as const,
        ),
        ...Object.entries(info).filter(
          ([key]) =>
            !PRIORITY_FIELDS.includes(key) &&
            !HIDDEN_FUND_INFO_FIELDS.includes(key),
        ),
      ]
    : [];

  return (
    <DetailDrawer
      open={fundCode != null}
      onOpenChange={onOpenChange}
      title="基金详情"
      description="同花顺基金档案"
      loading={isLoading}
      scroll
    >
      {info &&
        orderedEntries.map(([field, value]) => (
          <DetailField key={field} label={field} value={value || '-'} />
        ))}
    </DetailDrawer>
  );
}

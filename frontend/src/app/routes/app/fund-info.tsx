// 基金详情页 —— 持仓明细页基金名称点击跳转而来(照字典管理 dicts→dict-data 的页面跳转范式)
// 内容为同花顺档案全量键值(fund_info JSONB),按语义分组卡片排版;分组是展示层语义,与数据解耦
import { ArrowLeftIcon } from 'lucide-react';
import { motion, useReducedMotion } from 'motion/react';
import { useNavigate, useSearchParams } from 'react-router';

import { EmptyStateArt } from '@/components/shared/empty-state-art';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  HIDDEN_FUND_INFO_FIELDS,
  useFundInfo,
  type FundInfo,
} from '@/features/funds/api/get-fund-info';
import { FundRiskMetricsCard } from '@/features/funds/components/fund-risk-metrics-card';
import { FundYieldChartCard } from '@/features/funds/components/fund-yield-chart-card';

/** 语义分组配置:fields 顺序即展示顺序;数据里的未归组字段兜底进最后一组(全量可见) */
const INFO_GROUPS: Array<{ title: string; fields: string[] }> = [
  {
    title: '基本信息',
    fields: [
      '基金代码',
      '基金类型',
      '基金全称',
      '投资类型',
      '基金经理',
      '成立日期',
    ],
  },
  {
    title: '费率',
    fields: [
      '管理费',
      '托管费',
      '最高认购费',
      '最高申购费',
      '最高赎回费',
      '首次最低金额（元）',
      '首次最低金额',
    ],
  },
  { title: '规模', fields: ['成立规模', '份额规模'] },
  {
    title: '受托与其他',
    fields: ['基金管理人', '基金托管人', '业绩比较基准'],
  },
];

/**
 * 长文本字段跨满整行(卡片内两列网格下占满)。
 * 基金全称刻意不在列:它在基本信息卡里跨行会把后一项挤成单列,该卡要求两两成行。
 */
const WIDE_FIELDS = ['业绩比较基准'];

export default function FundInfoRoute() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const fundCode = searchParams.get('fundCode');

  const { data: info, isLoading } = useFundInfo(fundCode);
  const reduceMotion = useReducedMotion();

  // 分组渲染结构:组内取数据中存在的字段;未被任何组归类的字段追加进最后一组(源站加字段不丢);
  // 隐藏字段两条分支都不进(只从分组里删 = 它换个卡片继续出现)
  const groups = info
    ? INFO_GROUPS.map((group) => ({
        title: group.title,
        entries: group.fields
          .filter((field) => field in info)
          .map((field) => [field, info[field]] as const),
      })).concat({
        title: '其他信息',
        entries: Object.entries(info as FundInfo)
          .filter(
            ([field]) =>
              !INFO_GROUPS.some((g) => g.fields.includes(field)) &&
              !HIDDEN_FUND_INFO_FIELDS.includes(field),
          )
          .map((field) => [field[0], field[1]] as const),
      })
    : [];

  return (
    <div className="flex flex-col gap-4">
      {/* 页头:返回 + 标题 + 基金代码 */}
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="outline"
          size="sm"
          onClick={() => navigate(-1)}
          aria-label="返回上一页"
        >
          <ArrowLeftIcon />
          返回
        </Button>
        <span className="text-lg font-semibold">基金详情</span>
        {fundCode && <Badge variant="secondary">{fundCode}</Badge>}
      </div>

      {isLoading ? (
        // 骨架直接铺成两列卡片:与档案分组同布局,数据回来时不跳版
        <div className="grid gap-4 md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-40 w-full rounded-xl" />
          ))}
        </div>
      ) : !info || Object.keys(info).length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed py-16">
          <EmptyStateArt className="h-14 w-24" />
          <span className="text-muted-foreground">暂无该基金的档案信息</span>
          <Button variant="outline" size="sm" onClick={() => navigate(-1)}>
            返回
          </Button>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {groups.map(
            (group, groupIndex) =>
              group.entries.length > 0 && (
                // 档案分组逐张进场:组与组之间给 50ms 间隔,避免整页卡片同时出现
                <motion.div
                  key={group.title}
                  className="h-full"
                  initial={reduceMotion ? false : { opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{
                    duration: 0.35,
                    delay: Math.min(groupIndex, 6) * 0.05,
                    ease: 'easeOut',
                  }}
                >
                  <Card className="h-full gap-3 px-5 py-4">
                    <CardHeader className="px-0 py-0">
                      <CardTitle className="text-sm">{group.title}</CardTitle>
                    </CardHeader>
                    <CardContent className="grid grid-cols-2 gap-x-6 gap-y-3 px-0">
                      {group.entries.map(([field, value]) => {
                        const wide = WIDE_FIELDS.includes(field);
                        return (
                          <div
                            key={field}
                            className={wide ? 'col-span-2' : undefined}
                          >
                            <div className="text-muted-foreground text-xs">
                              {field}
                            </div>
                            <div className="break-all text-sm">
                              {value || '-'}
                            </div>
                          </div>
                        );
                      })}
                    </CardContent>
                  </Card>
                </motion.div>
              ),
          )}
        </div>
      )}

      {/* ===== 收益率曲线卡片(复权累计收益率 vs 指数基准,照仪表盘对比卡片) ===== */}
      {fundCode && (
        <FundYieldChartCard
          fundCode={fundCode}
          fundName={info?.['基金简称'] ?? fundCode ?? ''}
        />
      )}

      {/* ===== 关键指标大卡(与持仓分析页同款小节,数据源为该基金复权净值) ===== */}
      {fundCode && <FundRiskMetricsCard fundCode={fundCode} />}
    </div>
  );
}

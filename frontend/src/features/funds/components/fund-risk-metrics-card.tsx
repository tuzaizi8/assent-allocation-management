// src/features/funds/components/fund-risk-metrics-card.tsx —— 基金详情页「关键指标」大卡
// 与持仓分析页同款布局:指标条 + 全部图表收在一张大卡内,基准/档位选择器是卡头,
// 与上方「收益率对比」卡相互独立(同持仓分析页「对比卡自包含」的分工)。
// 数据源 GET /portfolio/analytics/fund-risk-metrics:收益率取自复权净值相邻相除,
// 指标内核与持仓版同源;小节内容复用 analytics 的 RiskMetricsPanel,这里只持卡头与请求。
// 与持仓分析页的差异:基金版后端只收时间档不收日期区间,故卡头无「自定义」档。
import { useState } from 'react';

import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useFundRiskMetrics } from '@/features/analytics/api/get-fund-risk-metrics';
import { RiskMetricsPanel } from '@/features/analytics/components/risk-metrics-panel';
import { useFundPeriods } from '@/features/funds/api/get-funds';
import { useIndices } from '@/features/indices/api/get-indices';

// 基准清单未加载/为空时的兜底初值(真实清单由 GET /index/list 下发,首项即沪深300,与后端默认一致)
const DEFAULT_BENCHMARK = '沪深300';
// 档位清单未加载/为空时的兜底初值(真实档位由 GET /fund/periods 下发)
const DEFAULT_PERIOD = '1年';

export function FundRiskMetricsCard({ fundCode }: { fundCode: string }) {
  const [period, setPeriod] = useState<string>(DEFAULT_PERIOD);
  // 用户显式选择 null=未选;未选时取清单首项,不写死指数名(清单变化自适应)
  const [selectedBenchmark, setSelectedBenchmark] = useState<string | null>(
    null,
  );
  const { data: periods } = useFundPeriods();
  const { data: indices, isLoading: indicesLoading } = useIndices();
  const benchmark =
    selectedBenchmark ?? indices?.[0]?.indexName ?? DEFAULT_BENCHMARK;

  const { data, isLoading } = useFundRiskMetrics(fundCode, period, benchmark);
  // 存成局部常量:TS 对属性访问链的收窄在 JSX 里会丢,别名后 null 检查才稳定
  const hasMetrics = (data?.metrics ?? null) != null;
  // 货币基金无净值,波动率/回撤等指标不适用——后端返回空载荷并带标记,这里换专属文案
  const isMoneyFund = data?.isMoneyFund === true;
  const emptyText = isMoneyFund
    ? '货币基金不适用波动率/回撤等专业指标,收益参考上方七日年化走势'
    : '暂无可用数据';

  return (
    <Card className="gap-0 py-0 shadow-sm shadow-black/5">
      <CardHeader className="flex items-center gap-2 space-y-0 py-5 sm:flex-row">
        <div className="grid flex-1 gap-1">
          <CardTitle>关键指标</CardTitle>
          {/* 正常态不占位:标题下只留加载/空数据的提示,基准与交易日数不再重复展示 */}
          {(isLoading || !hasMetrics) && (
            <CardDescription>
              {isLoading ? '数据加载中…' : emptyText}
            </CardDescription>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={benchmark}
            onValueChange={setSelectedBenchmark}
            disabled={indicesLoading}
          >
            <SelectTrigger className="w-28" aria-label="选择基准指数">
              <SelectValue placeholder="选择基准指数" />
            </SelectTrigger>
            <SelectContent className="rounded-xl">
              {(indices ?? []).map((item) => (
                <SelectItem
                  key={item.indexCode}
                  value={item.indexName}
                  className="rounded-lg"
                >
                  {item.indexName}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={period} onValueChange={setPeriod}>
            <SelectTrigger className="w-28">
              <SelectValue placeholder="时间范围" />
            </SelectTrigger>
            <SelectContent className="rounded-xl">
              {(periods?.length ? periods : [DEFAULT_PERIOD]).map((option) => (
                <SelectItem key={option} value={option}>
                  {option}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </CardHeader>

      <RiskMetricsPanel
        data={data}
        isLoading={isLoading}
        metricsEmptyHint={
          isMoneyFund ? '货币基金不适用专业风险指标' : '该时间段内暂无净值数据'
        }
      />
    </Card>
  );
}

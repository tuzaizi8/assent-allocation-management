// 持仓分析页(图表为主):指标与全部图表收在一张大卡片内,档位 Select 是该卡卡头,
// 作用域即卡内全部小节——避免出现「选择器在一张卡里、被控制的内容在卡外」的割裂布局。
// 顶部「收益率对比」卡自包含(自带档位/基准下拉),不在此作用域内。
// 数据源 GET /portfolio/analytics/risk-metrics:指标在后端算,前端纯展示。
import { useState } from 'react';

import { DateField } from '@/components/shared/date-field';
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
import { useRiskMetrics } from '@/features/analytics/api/get-risk-metrics';
import { RiskMetricsPanel } from '@/features/analytics/components/risk-metrics-panel';
import {
  defaultCustomRange,
  normalizeCustomRange,
  periodToStartDate,
  PERIOD_CUSTOM,
} from '@/features/analytics/lib/period';
import { PortfolioBenchmarkChart } from '@/features/dashboard/components/portfolio-benchmark-chart';
import { useFundPeriods } from '@/features/funds/api/get-funds';
import { useIndices } from '@/features/indices/api/get-indices';

// 基准清单未加载/为空时的兜底初值(真实清单由 GET /index/list 下发,首项即沪深300,与后端默认一致)
const DEFAULT_BENCHMARK = '沪深300';
// 档位清单未加载/为空时的兜底初值(真实档位由 GET /fund/periods 下发)
const DEFAULT_PERIOD = '1年';

export default function PositionsAnalysisRoute() {
  const [period, setPeriod] = useState<string>(DEFAULT_PERIOD);
  // 自定义区间的草稿值:初始给近一年,选中「自定义」时不会先面对两个空字段
  const [customRange, setCustomRange] = useState(defaultCustomRange);
  const { data: periods } = useFundPeriods();
  // 哨兵档位「自定义」只加在这里,后端档位清单不动
  const periodOptions = [
    ...(periods?.length ? periods : [DEFAULT_PERIOD]),
    PERIOD_CUSTOM,
  ];
  const isCustom = period === PERIOD_CUSTOM;
  // 空值(日期字段的清除按钮)与反序都在这里收口:渲染用它,请求也用它
  const range = normalizeCustomRange(customRange);

  // 基准与顶部对比卡各自独立:只复用同一个清单来源,不动那个自包含组件
  const [selectedBenchmark, setSelectedBenchmark] = useState<string | null>(
    null,
  );
  const { data: indices, isLoading: indicesLoading } = useIndices();
  // 未选时取清单首项,不写死指数名(清单变化自适应);清单未到再兜后端默认值
  const benchmark =
    selectedBenchmark ?? indices?.[0]?.indexName ?? DEFAULT_BENCHMARK;

  const startDate = isCustom ? range.start : periodToStartDate(period);
  const { data, isLoading } = useRiskMetrics(
    startDate,
    // 档位口径下结束日交后端缺省(今天),只有自定义才显式给
    isCustom ? range.end : undefined,
    benchmark,
  );
  // 存成局部常量:TS 对属性访问链的收窄在 JSX 里会丢,别名后 null 检查才稳定
  const hasMetrics = (data?.metrics ?? null) != null;

  return (
    <div className="flex flex-col gap-4">
      {/* 组合 vs 基准收益率对比:仪表盘同款组件原样复用(自带档位与基准下拉),
          只有分析页多给一个「自定义」时间档 */}
      <PortfolioBenchmarkChart allowCustomRange />

      <Card className="gap-0 py-0 shadow-sm shadow-black/5">
        <CardHeader className="flex items-center gap-2 space-y-0 py-5 sm:flex-row">
          <div className="grid flex-1 gap-1">
            <CardTitle>关键指标</CardTitle>
            {/* 正常态不占位:标题下只留加载/空数据的提示,基准与交易日数不再重复展示 */}
            {(isLoading || !hasMetrics) && (
              <CardDescription>
                {isLoading ? '数据加载中…' : '暂无可用数据'}
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
                {periodOptions.map((option) => (
                  <SelectItem key={option} value={option}>
                    {option}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {/* 自定义区间:选中「自定义」后才出现;起始晚于结束时把结束日一起推到同日,不产生反序区间 */}
            {isCustom && (
              <>
                <DateField
                  id="metrics-range-start"
                  value={customRange.start}
                  placeholder="开始日期"
                  onChange={(start) =>
                    setCustomRange((r) => ({
                      start,
                      end: start > r.end ? start : r.end,
                    }))
                  }
                />
                <span className="text-muted-foreground text-sm">至</span>
                <DateField
                  id="metrics-range-end"
                  value={customRange.end}
                  placeholder="结束日期"
                  onChange={(end) =>
                    setCustomRange((r) => ({
                      start: end < r.start ? end : r.start,
                      end,
                    }))
                  }
                />
              </>
            )}
          </div>
        </CardHeader>

        {/* 小节内容收口在共享面板:持仓/基金两页的「关键指标」同源零复制 */}
        <RiskMetricsPanel
          data={data}
          isLoading={isLoading}
          metricsEmptyHint="暂无可用数据:请先在「历史持仓」生成记录后再试"
        />
      </Card>
    </div>
  );
}

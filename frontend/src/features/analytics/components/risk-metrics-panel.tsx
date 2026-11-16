// src/features/analytics/components/risk-metrics-panel.tsx —— 风险指标大卡内容区(共享)
// 持仓分析页与基金详情页的「关键指标」大卡共用同一套小节:指标条 + 年化走势/回撤修复
// + 回撤曲线 + 滚动波动率/收益分布 + 滚动夏普 + 月度热力图。卡片骨架与卡头选择器由
// 各页面自持(两端点不同、空态提示不同),这里只负责「载荷 → 小节」的纯展示,零逻辑。
import { motion, useReducedMotion } from 'motion/react';

import { ChartEmpty } from '@/components/shared/chart-empty';
import { CardContent } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { Skeleton } from '@/components/ui/skeleton';

import type { RiskMetricsPayload } from '../api/get-risk-metrics';
import { buildRiskMetricItems } from '../lib/metric-items';

import { AnnualizedChart } from './annualized-chart';
import { DrawdownChart } from './drawdown-chart';
import { EquityReturnChart } from './equity-return-chart';
import { MetricHelp } from './metric-help';
import { heatmapHeight, MonthlyHeatmap } from './monthly-heatmap';
import { ReturnHistogram } from './return-histogram';
import { RiskMetricCards } from './risk-metric-cards';
import { RollingRiskChart } from './rolling-risk-chart';
import { RollingSharpeChart } from './rolling-sharpe-chart';

/** 面板数据形状:两端点载荷的结构化公共子集(基金载荷无 dataQuality,同样满足) */
export type RiskMetricsPanelData = Omit<RiskMetricsPayload, 'dataQuality'>;

// 小节不各自套卡片边框:浅色主题下 --card 与 --background 同为纯白,卡片套卡片会变成
// 同色白底上的两层描边(框套框)。字号字重沿用原卡片标题,保持与卡头一致的层级观感。
// 只留标题 + 讲解图标:读图说明统一收进 hover card(lib/metric-glossary),标题下不再挂副标题。
const Section = ({
  title,
  helpKey,
  index,
  children,
}: {
  title: string;
  /** 有讲解的指标才传:传了标题后才会多出那个悬浮说明图标 */
  helpKey?: string;
  /** 小节序号:决定级联进场的延迟(封顶,避免靠后小节等太久) */
  index: number;
  children: React.ReactNode;
}) => {
  const reduceMotion = useReducedMotion();
  return (
    <motion.section
      className="flex flex-col gap-3"
      initial={reduceMotion ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.35,
        delay: Math.min(index, 6) * 0.05,
        ease: 'easeOut',
      }}
    >
      <div className="flex items-center gap-1.5">
        <h3 className="font-heading text-base leading-snug font-medium">
          {title}
        </h3>
        {helpKey && <MetricHelp helpKey={helpKey} />}
      </div>
      <div className="px-2 sm:px-4">{children}</div>
    </motion.section>
  );
};

/** 图表加载占位:与图表同高的骨架,换真图时不跳版 */
const Loading = ({ height = 230 }: { height?: number }) => (
  <Skeleton className="w-full rounded-lg" style={{ height }} />
);

export function RiskMetricsPanel({
  data,
  isLoading,
  metricsEmptyHint = '暂无可用数据',
}: {
  data: RiskMetricsPanelData | null | undefined;
  isLoading: boolean;
  /** 指标条的空态提示:持仓域引导去快照管理,基金域提示无净值,由页面按域给文案 */
  metricsEmptyHint?: string;
}) {
  // 存成局部常量:TS 对属性访问链的收窄在 JSX 里会丢,别名后 null 检查才稳定
  const metrics = data?.metrics ?? null;

  return (
    <CardContent className="flex flex-col gap-6 pb-6">
      {/* 指标条是卡内第一块,但不再套小节标题(标题已提升为卡标题);padding 与其它小节保持一致 */}
      <div className="px-2 sm:px-4">
        {isLoading ? (
          <Loading height={120} />
        ) : metrics ? (
          <RiskMetricCards items={buildRiskMetricItems(metrics)} />
        ) : (
          <div className="text-muted-foreground flex h-[120px] items-center justify-center text-sm">
            {metricsEmptyHint}
          </div>
        )}
      </div>

      <Separator />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_auto_1fr]">
        <Section title="年化收益率走势" helpKey="annualizedTrend" index={0}>
          {isLoading ? (
            <Loading />
          ) : data && data.annualizedSeries.length > 0 ? (
            <AnnualizedChart
              points={data.annualizedSeries}
              benchmark={data.benchmarkAnnualizedSeries}
            />
          ) : (
            <ChartEmpty text="暂无年化走势数据" />
          )}
        </Section>
        {/* 中间列专放竖线:纯靠 24px 间隙区分不出左右两栏;窄屏堆叠时隐藏 */}
        <Separator orientation="vertical" className="hidden lg:block" />
        <Section title="回撤修复" helpKey="equityCurve" index={1}>
          {isLoading ? (
            <Loading />
          ) : data && data.returnSeries.length > 0 ? (
            <EquityReturnChart
              series={data.returnSeries}
              drawdown={data.drawdownSeries}
              maxDrawdown={metrics?.maxDrawdown ?? null}
              recoveryDays={metrics?.recoveryDays ?? null}
            />
          ) : (
            <ChartEmpty text="暂无收益走势数据" />
          )}
        </Section>
      </div>

      <Separator />

      <Section title="回撤曲线" helpKey="drawdownCurve" index={2}>
        {isLoading ? (
          <Loading />
        ) : data && data.drawdownSeries.length > 0 ? (
          <DrawdownChart
            points={data.drawdownSeries}
            benchmark={data.benchmarkDrawdownSeries}
          />
        ) : (
          <ChartEmpty text="暂无回撤数据" />
        )}
      </Section>

      <Separator />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_auto_1fr]">
        <Section title="滚动波动率" helpKey="rollingVolatility" index={3}>
          {isLoading ? (
            <Loading />
          ) : data && data.rollingSeries.portfolioVol.length > 0 ? (
            <RollingRiskChart
              portfolio={data.rollingSeries.portfolioVol}
              benchmark={data.rollingSeries.benchmarkVol}
            />
          ) : (
            <ChartEmpty text="数据不足一个滚动窗口(60 个交易日)" />
          )}
        </Section>
        {/* 中间列专放竖线:纯靠 24px 间隙区分不出左右两栏;窄屏堆叠时隐藏 */}
        <Separator orientation="vertical" className="hidden lg:block" />
        <Section title="收益分布" helpKey="returnDistribution" index={4}>
          {isLoading ? (
            <Loading />
          ) : data && data.returnHistogram.counts.length > 0 ? (
            <ReturnHistogram
              histogram={data.returnHistogram}
              varValue={data.metrics?.var ?? null}
              cvarValue={data.metrics?.cvar ?? null}
            />
          ) : (
            <ChartEmpty text="暂无分布数据" />
          )}
        </Section>
      </div>

      <Separator />

      <Section title="滚动夏普" helpKey="rollingSharpe" index={5}>
        {isLoading ? (
          <Loading />
        ) : data && data.rollingSeries.sharpe.length > 0 ? (
          <RollingSharpeChart
            points={data.rollingSeries.sharpe}
            benchmark={data.rollingSeries.benchmarkSharpe}
          />
        ) : (
          <ChartEmpty text="数据不足一个滚动窗口(60 个交易日)" />
        )}
      </Section>

      <Separator />

      <Section title="月度收益热力图" helpKey="monthlyReturns" index={6}>
        {isLoading ? (
          <Loading />
        ) : data && data.monthlyReturns.length > 0 ? (
          <MonthlyHeatmap rows={data.monthlyReturns} />
        ) : (
          // 热力图高度随年数自适应(66~336px),占位按 2 行估高,避免另写一个会漂移的魔数
          <ChartEmpty text="暂无月度收益数据" height={heatmapHeight(2)} />
        )}
      </Section>
    </CardContent>
  );
}

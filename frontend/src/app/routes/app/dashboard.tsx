// 资产仪表盘:指标卡片 → 收益率对比与基金收益双卡网格。
// 全部数据走真实接口(指标卡=最新快照行、对比卡=TWR+指数、基金收益卡=daily-fund-profit);
// 原先下方的「持仓明细表」是整表假数据,已于 2026-09-23 整体移除——真实持仓看侧边栏
// 「持仓简况」与「持仓明细」两页,本页不再重复展示。
import { DashboardCards } from '@/features/dashboard/components/dashboard-cards';
import { FundDailyProfitChart } from '@/features/dashboard/components/fund-daily-profit-chart';
import { PortfolioBenchmarkChart } from '@/features/dashboard/components/portfolio-benchmark-chart';

export default function DashboardRoute() {
  return (
    // @container/main 供卡片网格断点;间距与各管理页对齐(不加 py,AdminLayout 已提供)
    <div className="@container/main flex flex-col gap-4">
      <DashboardCards />
      {/* 双列:左收益率对比、右各基金昨日收益;窄屏回落单列 */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <PortfolioBenchmarkChart />
        <FundDailyProfitChart />
      </div>
    </div>
  );
}

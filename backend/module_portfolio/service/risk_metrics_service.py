"""持仓风险指标 Service(独立于 analytics_service,便于分类管理)。

职责链:快照表日频市值 + 现金流 → **日频 TWR 收益率序列**(现金流修正与 TWR 累积
复用 AnalyticsService 公开化后的 `adjusted_pair` / `calculate_twr`) → QuantStats
`stats` 模块计算波动率/夏普/回撤等专业指标 → 组装 camelCase 响应。

与 analytics_service 的分层约定:这里只放**风险指标**的新逻辑;收益率组装的通用
机制(现金流修正、TWR 累积、数据质量载荷)留在 AnalyticsService 公开复用,逻辑零复制。

口径与边界:
- **不复用** comparison / history/returns 的采样(interval_days 默认 7、范围 1-90):
  风险指标要日频收益率,这里固定按自然日生成序列、再按基准指数交易日过滤;
- TWR 现金流修正的边界(段内买卖不参与修正)在日频(interval=1 天)下已最小化,
  但「当日申购/赎回按期初事件处理」仍见 `AnalyticsService.adjusted_pair` 的注释;
- 年化系数 **252**(交易日口径):序列已按基准指数交易日过滤,自然日(周末零收益)
  不参与统计,否则波动率会被稀释;
- 无风险利率取**中国国债 2 年期收益率在评估区间内的均值**(`AkshareService.get_risk_free_rate_annual`);
  取数失败或区间无数据时降级固定常量 `RISK_FREE_RATE_FALLBACK_ANNUAL`,不让外部源拖挂接口。
"""

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import quantstats as qs
from redis import asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from module_fund.service.akshare_service import (
    DEFAULT_BENCHMARK_INDEX,
    RISK_FREE_RATE_FALLBACK_ANNUAL,
    AkshareService,
)
from module_fund.service.chart_service import ChartService
from module_portfolio.dao.daily_cash_flow_dao import DailyCashFlowDao
from module_portfolio.dao.daily_snapshot_dao import DailySnapshotDao
from module_portfolio.dao.position_dao import PositionDao
from module_portfolio.dao.purchase_record_dao import PurchaseRecordDao
from module_portfolio.dao.redemption_record_dao import RedemptionRecordDao
from module_portfolio.service.analytics_service import (
    AnalyticsService,
    _generate_date_series,
    _removed_value_by_date,
    _oversell_days,
)
from module_portfolio.service.snapshot_service import SnapshotService
from utils.log import logger

# 年化系数:交易日口径(收益率序列已按基准指数交易日过滤)
TRADING_DAYS_PER_YEAR = 252
# 滚动风险序列(波动率/夏普)的窗口:60 交易日 ≈ 3 个月,平滑度与灵敏度的折中
ROLLING_WINDOW = 60

# QuantStats monthly_returns 的月份列(值均为小数,NaN 表示该月无数据)
_MONTH_KEYS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']


class RiskMetricsService:
    """持仓风险与绩效指标(年化波动率/最大回撤/夏普/索提诺/卡玛等)。"""

    @classmethod
    async def calculate_risk_metrics_services(
        cls,
        query_db: AsyncSession,
        redis: aioredis.Redis,
        user_id: int,
        start_date: date,
        end_date: date,
        benchmark_name: str = DEFAULT_BENCHMARK_INDEX,
    ) -> dict:
        """计算持仓风险指标(优先走快照快速路径,日频)。"""
        positions = await PositionDao.get_positions(query_db, user_id)
        if not positions:
            return cls._empty_payload()

        # 与 comparison 同一套数据口径:资金进出按「全部持仓(含已删)」取,
        # 全额赎回会软删持仓,其历史买卖不能因此漏算
        all_position_ids = [pos.position_id for pos in await PositionDao.get_all_positions(query_db, user_id)]
        dates = _generate_date_series(start_date, end_date, 1)

        # 读路径懒补:与 comparison 同因(净值当晚才发布,不补则当日收益恒为 0)
        await SnapshotService.ensure_fresh_services(query_db, redis, user_id)

        snapshots = await DailySnapshotDao.get_snapshots_in_range(query_db, user_id, start_date, end_date)
        if not snapshots:
            # 日频风险指标必须有逐日市值;实时兜底路径是 O(日期×持仓×净值) 的重查询,
            # 这里不静默回退,返回空载荷让前端提示先去快照管理生成快照
            logger.warning(f'[风险指标] 无快照数据 user_id={user_id},返回空载荷')
            return cls._empty_payload()

        cash_flows = await DailyCashFlowDao.get_cash_flows_in_range(query_db, user_id, start_date, end_date)
        # 下界多取一天:区间首段要剥离「区间前一日」的赎回(赎回按成交日就已离场,从期初剥离)
        totals_start = start_date - timedelta(days=1)
        purchase_totals = await PurchaseRecordDao.get_totals_by_date(query_db, all_position_ids, totals_start, end_date)
        redemption_totals = await RedemptionRecordDao.get_totals_by_date(query_db, all_position_ids, totals_start, end_date)

        daily_data = AnalyticsService.build_daily_data_from_snapshots(snapshots, cash_flows, dates)
        # 裁剪未建仓的前导段:「成立以来」等大区间从 2004 年起算,组合首个有市值的日子
        # 之前收益恒为 0,会稀释波动率/夏普(均值被拉平)。没有任何市值 = 纯空仓,直接空载荷
        first_active = next((i for i, d in enumerate(daily_data) if d['total_value'] > 0), None)
        if first_active is None:
            return cls._empty_payload()
        if first_active > 0:
            daily_data = daily_data[first_active:]
            dates = dates[first_active:]
        removed_values, _ = _removed_value_by_date(snapshots)
        gap_by_day = _oversell_days(
            snapshots,
            await RedemptionRecordDao.get_shares_by_date_and_fund(query_db, all_position_ids, totals_start, end_date),
        )

        benchmark_data = await AnalyticsService.get_benchmark_series(query_db, redis, benchmark_name, start_date, end_date)

        # 日频 TWR(100 基准累计) → 日收益率:相邻两日相除 - 1,段内现金流已由 adjusted_pair 剥离
        twr_series = AnalyticsService.calculate_twr(
            daily_data,
            dates,
            purchase_totals,
            redemption_totals,
            removed_values=removed_values,
            gap_days=set(gap_by_day),
        )
        returns_by_date: dict[date, float] = {}
        for i in range(1, len(dates)):
            prev, cur = twr_series[i - 1], twr_series[i]
            if prev > 0:
                returns_by_date[dates[i]] = cur / prev - 1

        # 交易日对齐:只保留基准指数有收盘的日期(非交易日组合与基准收益均为 0,
        # 剔除不改变统计量,却让两条序列逐日同频,贝塔/跟踪误差才可比)
        benchmark_data.sort(key=lambda x: x['date'])
        benchmark_close = {b['date']: b['close'] for b in benchmark_data}
        trade_dates: list[date] = []
        returns: list[float] = []
        benchmark_returns: list[float] = []
        prev_close: float | None = None
        for d in dates:
            close = benchmark_close.get(d)
            if close is None or close <= 0:
                continue
            daily_return = returns_by_date.get(d)
            if daily_return is not None and prev_close:
                trade_dates.append(d)
                returns.append(daily_return)
                benchmark_returns.append(close / prev_close - 1)
            prev_close = close

        if len(returns) < 2:
            logger.warning(f'[风险指标] 有效交易日不足 user_id={user_id} trade_days={len(returns)},返回空载荷')
            return cls._empty_payload()

        returns_series = pd.Series(returns, index=pd.DatetimeIndex(trade_dates))
        benchmark_series = pd.Series(benchmark_returns, index=pd.DatetimeIndex(trade_dates))
        # 无风险利率按**实际评估区间**取(裁剪前导段后的首末交易日,而不是请求的 start_date):
        # 「成立以来」请求从 2004 年起算,但组合可能 2021 才有市值,用 2004 年以来的国债均值会偏。
        # 夏普与滚动夏普都吃它,组合/基准共用同一个值才可比
        rf_annual = await AkshareService.get_risk_free_rate_annual(redis, trade_dates[0], trade_dates[-1])
        metrics = cls._compute_metrics(returns_series, benchmark_series, rf=rf_annual)
        if gap_by_day:
            logger.warning(
                f'[风险指标] 记录不完整 {len(gap_by_day)} 天(user_id={user_id}),'
                f'涉及基金={sorted({code for codes in gap_by_day.values() for code in codes})}'
            )

        return {
            'metrics': metrics,
            'drawdownSeries': cls._drawdown_series_payload(returns_series),
            'benchmarkDrawdownSeries': cls._drawdown_series_payload(benchmark_series),
            'returnSeries': cls._return_series_payload(returns_series),
            'monthlyReturns': cls._monthly_returns_payload(returns_series),
            # 组合与基准走同一条公式、同一日期轴:两条年化线才同基可比
            'annualizedSeries': cls._annualized_series_payload(returns_series),
            'benchmarkAnnualizedSeries': cls._annualized_series_payload(benchmark_series),
            'rollingSeries': cls._rolling_series_payload(returns_series, benchmark_series, rf=rf_annual),
            'returnHistogram': cls._histogram_payload(returns_series),
            'returnStats': cls._return_stats(returns_series),
            'dataQuality': AnalyticsService.data_quality_payload(gap_by_day),
            'tradeDays': len(returns),
            'benchmark': benchmark_name,
        }

    # ---------- 基金风险指标(复用同一套 QuantStats 内核) ----------

    @staticmethod
    def _returns_from_accum_nav(pairs: list[tuple[date, float]]) -> list[tuple[date, float]]:
        """从复权净值序列生成日收益率:相邻两日相除 - 1。

        复权净值已消除分红/拆分跳变,相除即合法日收益——单基金不需要持仓域的
        快照表、现金流与 TWR 修正。净值非正(坏点,回源时 NaN 落 0)的相邻对跳过,
        不让除零/负值混进统计。输入必须按日期升序。
        """
        returns: list[tuple[date, float]] = []
        for (prev_date, prev_nav), (cur_date, cur_nav) in zip(pairs, pairs[1:]):
            if prev_nav > 0 and cur_nav > 0:
                returns.append((cur_date, cur_nav / prev_nav - 1))
        return returns

    @classmethod
    async def calculate_fund_risk_metrics_services(
        cls,
        query_db: AsyncSession,
        redis: aioredis.Redis,
        fund_code: str,
        period: str,
        benchmark_name: str = DEFAULT_BENCHMARK_INDEX,
    ) -> dict:
        """计算单基金风险指标(指标内核与持仓版完全同源,仅收益率序列来源不同)。

        与 calculate_risk_metrics_services 的差异:
        - 收益率直接取自复权净值相邻相除(见 _returns_from_accum_nav),无快照/现金流依赖;
        - 时间档与基金详情收益率曲线同源(ChartService.filter_records_by_period,
          同一个档位真相源),指标评估区间 = 曲线展示区间,两端天然对齐;
        - 数据取自 AkshareService.get_fund_nav 的**源记录**(accum_nav 全精度),
          不经 get_yield_curve 的归一化与 round(4),避免从展示 payload 反推收益的舍入误差。
        """
        # 货币基金无净值,波动率/回撤/夏普对它没有意义:直接空载荷并带标记,
        # 前端据此显示「货币基金不适用」而非泛泛的暂无数据
        if await AkshareService.is_money_fund(query_db, fund_code):
            payload = cls._empty_fund_payload(fund_code, period, benchmark_name)
            payload['isMoneyFund'] = True
            return payload
        records = await AkshareService.get_fund_nav(query_db, redis, fund_code)
        filtered = ChartService.filter_records_by_period(records, period)
        pairs: list[tuple[date, float]] = []
        for record in filtered:
            try:
                parsed = date.fromisoformat(str(record.get('nav_date', '')).replace('/', '-'))
            except ValueError:
                continue
            pairs.append((parsed, float(record.get('accum_nav') or 0)))
        if len(pairs) < 2:
            logger.warning(f'[基金风险指标] 净值不足 fund_code={fund_code} period={period},返回空载荷')
            return cls._empty_fund_payload(fund_code, period, benchmark_name)

        fund_returns = cls._returns_from_accum_nav(pairs)

        # 基准对齐(与持仓版同语义):基准缺收盘的日期整对剔除,两条序列逐日同频,
        # 贝塔/信息比率才可比;基准整体缺失(外部源失败)时不拦指标,降级为无基准
        benchmark_data = await AnalyticsService.get_benchmark_series(
            query_db, redis, benchmark_name, fund_returns[0][0], fund_returns[-1][0]
        )
        benchmark_close = {b['date']: b['close'] for b in benchmark_data}
        bench_return_by_date: dict[date, float] = {}
        bench_prev_close: float | None = None
        for bench_date in sorted(benchmark_close):
            close = benchmark_close[bench_date]
            if close > 0 and bench_prev_close:
                bench_return_by_date[bench_date] = close / bench_prev_close - 1
            if close > 0:
                bench_prev_close = close

        trade_dates: list[date] = []
        returns: list[float] = []
        benchmark_returns: list[float] = []
        for fund_date, fund_return in fund_returns:
            bench_return = bench_return_by_date.get(fund_date)
            # 基准缺失时退化为「全部基金净值日都算交易日」;有基准时只保留双序列齐备日
            if benchmark_close and bench_return is None:
                continue
            trade_dates.append(fund_date)
            returns.append(fund_return)
            if bench_return is not None:
                benchmark_returns.append(bench_return)

        if len(returns) < 2:
            logger.warning(f'[基金风险指标] 有效交易日不足 fund_code={fund_code} days={len(returns)},返回空载荷')
            return cls._empty_fund_payload(fund_code, period, benchmark_name)

        returns_series = pd.Series(returns, index=pd.DatetimeIndex(trade_dates))
        benchmark_series = (
            pd.Series(benchmark_returns, index=pd.DatetimeIndex(trade_dates))
            if benchmark_close and len(benchmark_returns) == len(returns)
            else None
        )
        # 无风险利率按实际评估区间取(与持仓版同因:档位回溯起点 ≠ 净值实际起点)
        rf_annual = await AkshareService.get_risk_free_rate_annual(redis, trade_dates[0], trade_dates[-1])
        metrics = cls._compute_metrics(returns_series, benchmark_series, rf=rf_annual)

        return {
            'fundCode': fund_code,
            'period': period,
            'metrics': metrics,
            'drawdownSeries': cls._drawdown_series_payload(returns_series),
            'benchmarkDrawdownSeries': cls._drawdown_series_payload(benchmark_series) if benchmark_series is not None else [],
            'returnSeries': cls._return_series_payload(returns_series),
            'monthlyReturns': cls._monthly_returns_payload(returns_series),
            'annualizedSeries': cls._annualized_series_payload(returns_series),
            'benchmarkAnnualizedSeries': cls._annualized_series_payload(benchmark_series) if benchmark_series is not None else [],
            'rollingSeries': cls._rolling_series_payload(returns_series, benchmark_series, rf=rf_annual),
            'returnHistogram': cls._histogram_payload(returns_series),
            'returnStats': cls._return_stats(returns_series),
            'tradeDays': len(returns),
            'benchmark': benchmark_name,
        }

    @staticmethod
    def _empty_fund_payload(fund_code: str, period: str, benchmark_name: str) -> dict:
        """基金版空载荷:形状与正常响应一致,metrics=None 让前端按空态处理。

        不含 dataQuality:那是持仓域快照记录完整性的概念,基金净值序列没有这个维度。
        """
        return {
            'fundCode': fund_code,
            'period': period,
            'metrics': None,
            'drawdownSeries': [],
            'benchmarkDrawdownSeries': [],
            'returnSeries': [],
            'monthlyReturns': [],
            'annualizedSeries': [],
            'benchmarkAnnualizedSeries': [],
            'rollingSeries': {'portfolioVol': [], 'benchmarkVol': [], 'sharpe': [], 'benchmarkSharpe': []},
            'returnHistogram': {'binEdges': [], 'counts': []},
            'returnStats': {'winDays': 0, 'loseDays': 0, 'flatDays': 0},
            'tradeDays': 0,
            'benchmark': benchmark_name,
        }

    # ---------- 指标计算(纯函数,可单测) ----------

    @staticmethod
    def _annualized_series_payload(returns: pd.Series, min_days: int = 21) -> list[dict]:
        """逐日年化收益率走势(%):第 n 个交易日把「起点到该日的累计增长」年化一次。

        口径与 QuantStats 的 `cagr` 同源:输入就是本服务喂给 qs 的那条**交易日对齐后**
        日收益序列,年化系数 252,故末点值等于收益序列末点的年化。刻意不再用
        `cum_by_date`(TWR 全自然日链):那里累计区间是自然日、而这里的 n 是交易日,
        分子分母不同源,还会让年化图末点与「收益走势」末点对不上。

        n < min_days 的早期噪声大(一两天的大涨会被年化成天文数字),从第 21 个交易日起画。
        """
        payload = []
        for n, (d, growth) in enumerate((1 + returns).cumprod().items(), start=1):
            if n < min_days:
                continue
            growth = float(growth)
            # 写 not growth > 0:顺带吃掉 NaN(它与任何数比较都是 False,`<= 0` 会把 NaN 放行)
            if not growth > 0:
                continue
            payload.append({
                'date': d.strftime('%Y-%m-%d'),
                'value': round((growth ** (TRADING_DAYS_PER_YEAR / n) - 1) * 100, 2),
            })
        return payload

    @staticmethod
    def _return_series_payload(returns: pd.Series) -> list[dict]:
        """逐日累计收益率(%),与 drawdownSeries / maxDrawdown 同一条路径。

        刻意用**对齐后**的日收益序列复利累乘,而不是 TWR 全量日期链(那还含非交易日):
        两条路径会分叉,曲线上量出的「最高点→最低点」跌幅与 metrics.maxDrawdown 对不上
        (实测差 1.22 个百分点),前端标注就会画错位置。
        """
        cumulative = (1 + returns).cumprod()
        return [
            {'date': d.strftime('%Y-%m-%d'), 'value': round(float(v - 1) * 100, 2)}
            for d, v in cumulative.items()
        ]

    @classmethod
    def _rolling_series_payload(
        cls, returns: pd.Series, benchmark: pd.Series | None, rf: float = RISK_FREE_RATE_FALLBACK_ANNUAL
    ) -> dict:
        """60 交易日滚动风险序列:组合/基准波动率(%)与组合/基准滚动夏普;NaN 前导段丢弃。

        rf 是整段共用的无风险利率:QuantStats 的 rolling_sharpe 只接受标量,做不到逐日 rf。
        """
        rolling_vol = qs.stats.rolling_volatility(
            returns, rolling_period=ROLLING_WINDOW, periods_per_year=TRADING_DAYS_PER_YEAR
        )
        rolling_bench = (
            qs.stats.rolling_volatility(
                benchmark, rolling_period=ROLLING_WINDOW, periods_per_year=TRADING_DAYS_PER_YEAR
            )
            if benchmark is not None
            else None
        )
        rolling_sharpe = qs.stats.rolling_sharpe(
            returns, rf=rf, rolling_period=ROLLING_WINDOW, periods_per_year=TRADING_DAYS_PER_YEAR
        )
        # 基准侧同函数同参数:两条线同窗口、同无风险利率,才可横向比高低
        rolling_bench_sharpe = (
            qs.stats.rolling_sharpe(
                benchmark, rf=rf, rolling_period=ROLLING_WINDOW, periods_per_year=TRADING_DAYS_PER_YEAR
            )
            if benchmark is not None
            else None
        )

        def vol_payload(s: pd.Series | None) -> list[dict]:
            if s is None:
                return []
            return [
                {'date': d.strftime('%Y-%m-%d'), 'value': round(float(v) * 100, 2)}
                for d, v in s.items()
                if pd.notna(v)
            ]

        def sharpe_payload(s: pd.Series | None) -> list[dict]:
            # 夏普是比值,不是百分数,故不乘 100
            if s is None:
                return []
            return [
                {'date': d.strftime('%Y-%m-%d'), 'value': round(float(v), 4)}
                for d, v in s.items()
                if pd.notna(v)
            ]

        return {
            'portfolioVol': vol_payload(rolling_vol),
            'benchmarkVol': vol_payload(rolling_bench),
            'sharpe': sharpe_payload(rolling_sharpe),
            'benchmarkSharpe': sharpe_payload(rolling_bench_sharpe),
        }

    @staticmethod
    def _histogram_payload(returns: pd.Series, bins: int = 20) -> dict:
        """日收益分布直方图:20 个等宽 bin,值为百分数;VaR/CVaR 标线位置前端从 metrics 取。"""
        counts, edges = np.histogram(returns.to_numpy() * 100, bins=bins)
        return {
            'binEdges': [round(float(e), 2) for e in edges],
            'counts': [int(c) for c in counts],
        }

    @staticmethod
    def _return_stats(returns: pd.Series) -> dict:
        """胜/负/平交易日数:环形图与胜率指标同源,避免前端从百分比反推出舍入误差。"""
        values = returns.to_numpy()
        return {
            'winDays': int((values > 0).sum()),
            'loseDays': int((values < 0).sum()),
            'flatDays': int((values == 0).sum()),
        }

    @staticmethod
    def _drawdown_periods(drawdown: pd.Series) -> list[dict]:
        """把回撤序列切成连续水下段,返回每段的起止/谷底/持续天数/修复信息。

        语义约定(自研,精确可控):
        - start:该段第一个水下日(dd < 0);end:该段**最后一个水下日**;
        - valley:段内 dd 最小的日期,depth = 该最小值(小数);
        - days = start→end 的**自然日数(含首尾)**;
        - recoveryDate = end 之后**第一个 dd == 0 的交易日**;序列在水下结束时未修复,
          recoveryDate/recoveryDays 为 None。
        """
        periods: list[dict] = []
        start = None
        valley_date = None
        valley_value = 0.0
        last_underwater = None
        for d, value in drawdown.items():
            if value < 0:
                if start is None:
                    start = d
                    valley_date, valley_value = d, value
                last_underwater = d
                if value < valley_value:
                    valley_date, valley_value = d, value
            elif start is not None:
                periods.append({
                    'start': start,
                    'valley': valley_date,
                    'end': last_underwater,
                    'days': (last_underwater - start).days + 1,
                    'depth': valley_value,
                    'recoveryDate': d,
                    'recoveryDays': (d - valley_date).days,
                })
                start = None
        if start is not None:
            # 序列在水下结束:未修复
            periods.append({
                'start': start,
                'valley': valley_date,
                'end': last_underwater,
                'days': (last_underwater - start).days + 1,
                'depth': valley_value,
                'recoveryDate': None,
                'recoveryDays': None,
            })
        return periods

    @classmethod
    def _compute_metrics(
        cls, returns: pd.Series, benchmark: pd.Series | None, rf: float = RISK_FREE_RATE_FALLBACK_ANNUAL
    ) -> dict:
        """用 QuantStats stats 计算全部指标(输入为日收益率小数序列)。

        所有 NaN(如全零收益下 sharpe 除零)统一降级为 None,不让 JSON 序列化炸掉。
        rf 由调用侧按评估区间取好传进来(默认值是兜底常量,便于纯函数单测)。
        """
        annual_volatility = float(qs.stats.volatility(returns, periods=TRADING_DAYS_PER_YEAR))
        max_drawdown = float(qs.stats.max_drawdown(returns))
        # 下行波动率(empyrical 口径):sqrt(mean(min(r - mar, 0)^2)) * sqrt(年化系数),mar=0。
        # QuantStats 0.0.81 没有 downside_risk 函数,手写一行,与手写跟踪误差同款处理。
        downside_volatility = float(
            np.sqrt(np.mean(np.minimum(returns.to_numpy(), 0.0) ** 2)) * math.sqrt(TRADING_DAYS_PER_YEAR)
        )

        # 回撤分段:自研切片(见 _drawdown_periods),不用 qs.stats.drawdown_details——
        # 其 0.0.81 的 end 语义是「最后一个水下日」且日期为字符串,修复天数要自己算才精确
        drawdown = qs.stats.to_drawdown_series(returns)
        periods = cls._drawdown_periods(drawdown)
        max_period = min(periods, key=lambda p: p['depth']) if periods else None
        longest_days = max((p['days'] for p in periods), default=0)

        def pct(value) -> float | None:
            # inf/-inf(如全零收益下 sharpe 的除零结果)与 NaN 一并降级为 None
            return round(float(value) * 100, 2) if value is not None and np.isfinite(value) else None

        def ratio(value) -> float | None:
            return round(float(value), 4) if value is not None and np.isfinite(value) else None

        # VaR/CVaR 取**实测(历史模拟)分位**,不用 qs.stats.value_at_risk 的正态近似:
        # 本页给的是 20 bin 的实测直方图,只有实测分位才与柱子自洽(标线左侧恰好是最差的
        # 5% 天数),「最差那 5% 的日子平均亏多少」这句文案才字面成立。qs 的 var 走
        # 均值 - 1.645 倍标准差,日收益肥尾时标线左侧的天数会多于 5%。
        q05 = float(returns.quantile(0.05))
        tail = returns[returns <= q05]

        metrics: dict = {
            'annualVolatility': pct(annual_volatility),
            'maxDrawdown': pct(max_drawdown),
            'maxDrawdownStart': max_period['start'].strftime('%Y-%m-%d') if max_period else None,
            'maxDrawdownValley': max_period['valley'].strftime('%Y-%m-%d') if max_period else None,
            # end = 该段最后一个水下交易日(修复发生在其后的第一个交易日)
            'maxDrawdownEnd': max_period['end'].strftime('%Y-%m-%d') if max_period else None,
            'recoveryDays': max_period['recoveryDays'] if max_period else None,
            'longestDrawdownDays': longest_days,
            'sharpe': ratio(qs.stats.sharpe(returns, rf=rf, periods=TRADING_DAYS_PER_YEAR)),
            # 实际用到的无风险利率(百分数):前端夏普卡副文本要显示它,不能再写死 1.5%
            'riskFreeRate': pct(rf),
            'sortino': ratio(qs.stats.sortino(returns)),
            'calmar': ratio(qs.stats.calmar(returns)),
            'downsideVolatility': pct(downside_volatility),
            'winRate': pct(qs.stats.win_rate(returns)),
            'var': pct(q05),
            'cvar': pct(tail.mean()) if len(tail) else None,
        }

        # 基准侧:信息比率 / 贝塔(含 alpha)/ 跟踪误差;基准缺失或长度不一致时降级为 None
        if benchmark is not None and len(benchmark) == len(returns):
            greeks = qs.stats.greeks(returns, benchmark)
            metrics['informationRatio'] = ratio(qs.stats.information_ratio(returns, benchmark))
            metrics['beta'] = ratio(greeks.get('beta'))
            metrics['alpha'] = ratio(greeks.get('alpha'))
            metrics['trackingError'] = pct((returns - benchmark).std() * math.sqrt(TRADING_DAYS_PER_YEAR))
        else:
            metrics['informationRatio'] = None
            metrics['beta'] = None
            metrics['alpha'] = None
            metrics['trackingError'] = None
        return metrics

    @staticmethod
    def _drawdown_series_payload(returns: pd.Series) -> list[dict]:
        """回撤序列(underwater):转成百分比负值,供前端画 0 基线面积图。"""
        drawdown = qs.stats.to_drawdown_series(returns)
        return [{'date': d.strftime('%Y-%m-%d'), 'dd': round(float(v) * 100, 2)} for d, v in drawdown.items()]

    @staticmethod
    def _monthly_returns_payload(returns: pd.Series) -> list[dict]:
        """月度收益表:年份行 × 12 月列(+ 当年累计),值转百分比、无数据为 None。"""
        monthly_df = qs.stats.monthly_returns(returns)
        payload = []
        for year, row in monthly_df.iterrows():
            months = [
                round(float(row[key]) * 100, 2) if pd.notna(row[key]) else None for key in _MONTH_KEYS
            ]
            year_total = row['EOY']
            payload.append({
                'year': int(year),
                'months': months,
                'yearTotal': round(float(year_total) * 100, 2) if pd.notna(year_total) else None,
            })
        return payload

    @staticmethod
    def _empty_payload() -> dict:
        """空载荷:无持仓/无快照/有效交易日不足时返回,前端按空态处理(形状与正常响应一致)。"""
        return {
            'metrics': None,
            'drawdownSeries': [],
            'benchmarkDrawdownSeries': [],
            'returnSeries': [],
            'monthlyReturns': [],
            'annualizedSeries': [],
            'benchmarkAnnualizedSeries': [],
            'rollingSeries': {'portfolioVol': [], 'benchmarkVol': [], 'sharpe': [], 'benchmarkSharpe': []},
            'returnHistogram': {'binEdges': [], 'counts': []},
            'returnStats': {'winDays': 0, 'loseDays': 0, 'flatDays': 0},
            'dataQuality': AnalyticsService.data_quality_payload({}),
            'tradeDays': 0,
            'benchmark': DEFAULT_BENCHMARK_INDEX,
        }

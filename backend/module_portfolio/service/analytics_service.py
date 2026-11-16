"""持仓分析 Service(业务逻辑层)。

职责:收益率分析(TWR 时间加权 / MWR 金额加权 / Modified Dietz 年化)
+ 历史持仓查询 + 持仓占比历史 + 基准对比。
"""

from collections import defaultdict
from datetime import date, timedelta

from redis import asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions.exceptions import ServiceWarning
from module_fund.dao.fund_dao import FundDao
from module_fund.service.akshare_service import DEFAULT_BENCHMARK_INDEX, AkshareService
from module_portfolio.dao.daily_cash_flow_dao import DailyCashFlowDao
from module_portfolio.dao.daily_snapshot_dao import DailySnapshotDao
from module_portfolio.dao.position_dao import PositionDao
from module_portfolio.dao.purchase_record_dao import PurchaseRecordDao
from module_portfolio.dao.redemption_record_dao import RedemptionRecordDao
from module_portfolio.service.position_calc_util import (
    MoneyAccumCurve,
    daily_profit,
    filter_effective_records,
    money_market_value_on,
    nav_value_from_map,
    shares_held_at_close_pairs,
    shares_held_on_pairs,
)
from module_portfolio.service.position_service import PositionService
from module_portfolio.service.snapshot_service import SnapshotService
from utils.log import logger


# 「赎回回款金额」与「组合实际被移走的市值」的容差:分位级差异(手续费、净值来源)不算数据不完整
REMOVED_VALUE_TOLERANCE = 1.0


def _removed_value_by_date(snapshots: list) -> tuple[dict[date, float], dict[date, list[str]]]:
    """按日汇总「组合实际被移走的市值」与涉及基金(纯内存,由逐基金快照推导)。

    赎回是期末事件:份额要到**次一快照日**才消失,故归属于赎回当日、按当日净值计价——与
    `snapshot_service._build_snapshot_rows`「份额取市值族(赎回次日起才扣除)」的约定同源。
    数据一致时它约等于回款金额;记录缺了早期买入时(超卖)它会明显小于回款,而那部分差额
    不该被当成收益(2026-09-20 实测:9 天、累计虚增 179.03 元)。
    """
    by_date: dict[date, dict[str, tuple[float, float]]] = {}
    for row in snapshots:
        by_date.setdefault(row.snapshot_date, {})[row.fund_code] = (float(row.shares), float(row.nav))
    removed: dict[date, float] = defaultdict(float)
    funds: dict[date, list[str]] = defaultdict(list)
    days = sorted(by_date)
    for day, next_day in zip(days, days[1:]):
        today, tomorrow = by_date[day], by_date[next_day]
        for code, (shares, nav) in today.items():
            drop = shares - tomorrow.get(code, (0.0, 0.0))[0]
            if drop > 1e-9:
                removed[day] += drop * nav
                funds[day].append(code)
    return removed, funds


def _oversell_days(snapshots: list, redemption_shares: dict[tuple[date, str], float]) -> dict[date, list[str]]:
    """按日找出「赎回份额 > 当日快照持有份额」的基金({日期: [基金]})——记录不完整的直接证据。

    赎回份额取自赎回记录、持有份额取自快照,都按基金比对。这些天回款会大于组合实际被移走的市值,
    差额不是收益;而「回款与快照市值差 1% 上下」是净值时点(当天只公布了上一根)造成的**正常**差异,
    不算数据缺口——所以不能用「回款 > 移走市值」当判据,必须用份额本身比。
    """
    held: dict[date, dict[str, float]] = {}
    for row in snapshots:
        held.setdefault(row.snapshot_date, {})[row.fund_code] = float(row.shares)
    gap: dict[date, list[str]] = defaultdict(list)
    for (day, code), shares in redemption_shares.items():
        on_day = held.get(day)
        if on_day is None:
            continue
        if shares - on_day.get(code, 0.0) > 1e-6:
            gap[day].append(code)
    return {day: sorted(codes) for day, codes in gap.items()}


def _generate_date_series(start_date: date, end_date: date, interval_days: int) -> list[date]:
    """生成采样日期序列(保证首尾日期都在序列中)。"""
    dates = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current = current + timedelta(days=interval_days)
        if current > end_date:
            if dates[-1] != end_date:
                dates.append(end_date)
            break
    return dates


def _calc_daily_fund_profit(
    nav_records: list[dict],
    purchases: list[tuple[str, float]],
    redemptions: list[tuple[str, float]],
    offset: int,
) -> dict | None:
    """计算单基金某净值档的日收益(纯函数,无 IO,便于单测锁口径)。

    offset=0 为最新净值日(今日档)、1 为上一净值日(昨日档),以此类推。
    收益口径:「档位前一净值日末已持有的份额 × (档位净值 − 前一净值日净值)」——
    买入 ≤ 前一净值日计入、赎回 < 前一净值日扣除(T+1 语义,赎回当日仍持有),
    今日买入不计入今日收益。份额与收益均走 module_portfolio.service.position_calc_util 公共工具。

    与持仓列表行上的 daily_profit 差异仅剩**作用域**:本端点按 fund_code 全量
    (含同基金旧仓的已删赎回,便于「这只基金前后一共赚了多少」),列表行按
    position_id 当前仓;两者数值精度已统一为 round 4。
    前一净值日末未持有(份额≤0,如建仓首日算昨日档)返回 None,该基金不进该档。
    """
    idx = len(nav_records) - 1 - offset
    if idx < 1:
        return None
    nav_date = nav_records[idx].get('nav_date') or ''
    prev_nav_date = nav_records[idx - 1].get('nav_date') or ''
    nav = nav_records[idx].get('unit_nav') or 0
    prev_nav = nav_records[idx - 1].get('unit_nav') or 0
    if not nav_date or not prev_nav_date:
        return None

    shares = shares_held_at_close_pairs(purchases, redemptions, prev_nav_date)
    if shares <= 0:
        return None
    return {
        'navDate': nav_date,
        'prevNavDate': prev_nav_date,
        'nav': nav,
        'prevNav': prev_nav,
        'shares': shares,
        'dailyProfit': daily_profit(shares, nav, prev_nav),
    }


def _money_daily_fund_profit_row(
    curve: MoneyAccumCurve,
    purchases: list[tuple[str, float]],
    redemptions: list[tuple[str, float]],
    offset: int,
) -> dict | None:
    """货币基金日收益行(与 _calc_daily_fund_profit 同形状,纯函数)。

    净值恒 1.0,净值差恒 0——收益来自每日收益结转,每笔交易从成交日起复利
    (与持仓卡/快照同口径)。市值差两端的交易集合必须冻结在 prev 收盘时点:
    若直接取各自时点的市值,窗口内的赎回流出会被当成当日亏损、买入流入会被
    当成当日盈利——申赎是资金进出不是盈亏。冻结边界与 shares 字段所用的
    shares_held_at_close_pairs(日收益族)逐字一致:买入 ≤ prev 计入、赎回
    ≤ prev 扣除(其持有期收益已在 latest=prev 的那一档结转完),窗口内申赎
    的份额仍享受整段窗口收益,与普通基金「prev 收盘份额 × 净值差」口径对齐。
    """
    latest, prev = curve.nth_dates(offset)
    if not latest or not prev:
        return None
    prev_date = date.fromisoformat(prev)
    shares = shares_held_at_close_pairs(purchases, redemptions, prev)
    if shares <= 0:
        # 与普通基金同规则:prev 收盘未持有(份额≤0)不进该档,
        # 也顺带挡掉「赎回流出一度被记成巨亏」的行
        return None
    buy_pairs = [(date.fromisoformat(d), s) for d, s in purchases]
    sell_pairs = [(date.fromisoformat(d), s) for d, s in redemptions]
    buys_fixed = [(d, s) for d, s in buy_pairs if d <= prev_date]
    sells_fixed = [(d, s) for d, s in sell_pairs if d > prev_date]

    def value_at(d: date) -> float:
        return money_market_value_on(buys_fixed, sells_fixed, curve, d)
    return {
        'navDate': latest,
        'prevNavDate': prev,
        'nav': 1.0,
        'prevNav': 1.0,
        'shares': shares,
        'dailyProfit': value_at(date.fromisoformat(latest)) - value_at(prev_date),
    }


class AnalyticsService:
    """持仓分析服务层。"""

    # ---------- 单持仓收益率 ----------

    @classmethod
    async def get_holding_return_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, position_id: int, user_id: int, as_of_date: date
    ) -> dict:
        """获取持仓简单收益率((市值-成本)/成本)。"""
        detail = await PositionService.get_position_at_date_services(query_db, redis, position_id, user_id, as_of_date)
        if not detail:
            raise ServiceWarning(message='持仓不存在')
        holding_return = (
            (detail['currentValue'] - detail['totalCost']) / detail['totalCost'] if detail['totalCost'] > 0 else 0
        )
        return {
            'positionId': position_id,
            'fundCode': detail['fundCode'],
            'fundName': detail['fundName'],
            'asOfDate': as_of_date.isoformat(),
            'holdingReturn': holding_return,
            'currentValue': detail['currentValue'],
            'totalCost': detail['totalCost'],
            'profit': detail['profit'],
        }

    @classmethod
    async def calculate_position_dietz_return_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, position_id: int, user_id: int, as_of_date: date
    ) -> dict:
        """获取持仓 Modified Dietz 年化收益率。

        Modified Dietz = (V1 - V0 - CF) / (V0 + WAF);年化 = (1+dietz)^(365/天数) - 1。
        """
        detail = await PositionService.get_position_at_date_services(query_db, redis, position_id, user_id, as_of_date)
        if not detail:
            raise ServiceWarning(message='持仓不存在')

        purchases = await PurchaseRecordDao.get_purchase_records(query_db, position_id)
        redemptions = await RedemptionRecordDao.get_redemption_records(query_db, position_id)
        purchases = [p for p in purchases if p.purchase_date <= as_of_date]
        redemptions = [r for r in redemptions if r.redemption_date <= as_of_date]
        if not purchases:
            raise ServiceWarning(message='无买入记录')

        start_date = min(p.purchase_date for p in purchases)
        total_days = (as_of_date - start_date).days
        if total_days <= 0:
            raise ServiceWarning(message='持有天数不足，无法计算年化收益率')

        # V0 = 0(首次买入前无持仓),期末市值取 query_date 视图(currentValue 已按历史份额×期末净值计算)
        v1 = detail['currentValue']

        net_cash_flow = 0.0
        weighted_flow = 0.0
        for p in purchases:
            # 首次买入是 V0 的一部分,不计入区间现金流
            if p.purchase_date == start_date:
                continue
            if start_date < p.purchase_date <= as_of_date:
                amount = float(p.shares) * float(p.cost_price)
                net_cash_flow -= amount
                weighted_flow -= amount * ((as_of_date - p.purchase_date).days / total_days)
        for r in redemptions:
            if start_date < r.redemption_date <= as_of_date:
                amount = float(r.shares) * float(r.nav_price)
                net_cash_flow += amount
                weighted_flow += amount * ((as_of_date - r.redemption_date).days / total_days)

        denominator = weighted_flow
        if denominator == 0:
            raise ServiceWarning(message='无法计算年化收益率（可能缺少数据）')
        dietz_return = (v1 - net_cash_flow) / denominator
        annualized = cls._annualize(dietz_return, total_days)

        holding_return = (
            (detail['currentValue'] - detail['totalCost']) / detail['totalCost'] if detail['totalCost'] > 0 else 0
        )
        return {
            'positionId': position_id,
            'fundCode': detail['fundCode'],
            'fundName': detail['fundName'],
            'asOfDate': as_of_date.isoformat(),
            'annualizedReturn': annualized,
            'holdingReturn': holding_return,
            'totalDays': total_days,
            'startDate': start_date.isoformat(),
            'endDate': as_of_date.isoformat(),
        }

    # ---------- 组合收益率 ----------

    @classmethod
    async def get_portfolio_at_date_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int, query_date: date
    ) -> dict:
        """获取用户在指定日期的持仓快照(逐持仓历史份额/成本汇总)。"""
        positions = await PositionDao.get_positions(query_db, user_id)
        historical_positions = []
        total_value = 0.0
        for pos in positions:
            detail = await PositionService.get_position_at_date_services(
                query_db, redis, pos.position_id, user_id, query_date
            )
            if detail:
                historical_positions.append(detail)
                total_value += detail['currentValue']
        return {
            'queryDate': query_date.isoformat(),
            'positions': historical_positions,
            'totalValue': round(total_value, 2),
        }

    @classmethod
    async def calculate_modified_dietz_return_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int, start_date: date, end_date: date
    ) -> float | None:
        """计算区间 Modified Dietz 收益率(小数形式)。"""
        positions = await PositionDao.get_positions(query_db, user_id)

        portfolio_start = await cls.get_portfolio_at_date_services(query_db, redis, user_id, start_date)
        v0 = portfolio_start['totalValue']
        portfolio_end = await cls.get_portfolio_at_date_services(query_db, redis, user_id, end_date)
        v1 = portfolio_end['totalValue']

        total_days = (end_date - start_date).days
        if total_days <= 0:
            return None

        net_cash_flow = 0.0
        weighted_flow = 0.0
        for pos in positions:
            # 待确认交易不算:金额未定,计入会让区间现金流与实际不符
            purchases = filter_effective_records(await PurchaseRecordDao.get_purchase_records(query_db, pos.position_id))
            redemptions = filter_effective_records(
                await RedemptionRecordDao.get_redemption_records(query_db, pos.position_id)
            )
            for p in purchases:
                if start_date < p.purchase_date <= end_date:
                    amount = float(p.shares) * float(p.cost_price)
                    net_cash_flow -= amount
                    weighted_flow -= amount * ((end_date - p.purchase_date).days / total_days)
            for r in redemptions:
                if start_date < r.redemption_date <= end_date:
                    amount = float(r.shares) * float(r.nav_price)
                    net_cash_flow += amount
                    weighted_flow += amount * ((end_date - r.redemption_date).days / total_days)

        denominator = v0 + weighted_flow
        if denominator == 0:
            return None
        return (v1 - v0 - net_cash_flow) / denominator

    @classmethod
    async def get_portfolio_return_history_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int,
        start_date: date, end_date: date, interval_days: int = 7
    ) -> dict:
        """获取持仓收益率历史(折线图:简单收益率 + Modified Dietz 资金加权收益率)。"""
        positions = await PositionDao.get_positions(query_db, user_id)
        if not positions:
            return {'dates': [], 'returns': [], 'weightedReturns': [], 'values': []}

        earliest_date = None
        for pos in positions:
            # 待确认买入不算建仓日:它的日期可能晚于已生效交易,份额也尚未确定
            purchases = filter_effective_records(await PurchaseRecordDao.get_purchase_records(query_db, pos.position_id))
            for p in purchases:
                if earliest_date is None or p.purchase_date < earliest_date:
                    earliest_date = p.purchase_date
        if earliest_date is None:
            return {'dates': [], 'returns': [], 'weightedReturns': [], 'values': []}

        if start_date < earliest_date:
            start_date = earliest_date
        dates = _generate_date_series(start_date, end_date, interval_days)

        results = []
        for i, d in enumerate(dates):
            portfolio = await cls.get_portfolio_at_date_services(query_db, redis, user_id, d)
            if portfolio['positions']:
                total_cost = sum(p['totalCost'] for p in portfolio['positions'])
                total_value = portfolio['totalValue']
                profit_rate = (total_value - total_cost) / total_cost * 100 if total_cost > 0 else 0
                start_for_dietz = earliest_date if i == 0 else dates[i - 1]
                weighted_return = await cls.calculate_modified_dietz_return_services(
                    query_db, redis, user_id, start_for_dietz, d
                )
                results.append({
                    'date': d.isoformat(),
                    'total_value': total_value,
                    'profit_rate': profit_rate,
                    'weighted_return': weighted_return * 100 if weighted_return is not None else 0,
                })

        return {
            'dates': [r['date'] for r in results],
            'returns': [r['profit_rate'] for r in results],
            'weightedReturns': [r['weighted_return'] for r in results],
            'values': [r['total_value'] for r in results],
        }

    @classmethod
    async def calculate_portfolio_analytics_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int,
        start_date: date, end_date: date, interval_days: int = 7, benchmark_name: str = DEFAULT_BENCHMARK_INDEX
    ) -> dict:
        """计算持仓组合收益率分析(TWR/MWR/基准对比,优先走快照快速路径)。"""
        positions = await PositionDao.get_positions(query_db, user_id)
        if not positions:
            return {
                'dates': [], 'twr': [], 'mwr': [], 'benchmark': [],
                'portfolioValue': [], 'totalInvested': [], 'annualizedReturn': 0,
                'dataQuality': cls.data_quality_payload({}),
            }
        # 但不管用哪个口径,资金进出都必须按「全部持仓(含已删)」取:全额赎回会把持仓软删,
        # 其历史买卖不能因此漏算(快照与现金流表同此口径)
        all_position_ids = [pos.position_id for pos in await PositionDao.get_all_positions(query_db, user_id)]

        dates = _generate_date_series(start_date, end_date, interval_days)

        # 读路径懒补:快照只在「交易后回填」与「手动生成/重建」两处写入,而净值当晚才发布、个别
        # 基金还会滞后一两天——不补的话当日市值会沿用上一根净值(当日收益恒为 0)或停在更早的旧根上。
        # 判定与执行见 SnapshotService.ensure_fresh_services(失败静默,不影响本接口返回)。
        await SnapshotService.ensure_fresh_services(query_db, redis, user_id)

        snapshots = await DailySnapshotDao.get_snapshots_in_range(query_db, user_id, start_date, end_date)
        cash_flows = await DailyCashFlowDao.get_cash_flows_in_range(query_db, user_id, start_date, end_date)
        # 剥离用「当日申购/赎回总额」而不是 cash_flows 的当日净额:同一天既有买入又有赎回时
        # 净额会被抵消,按「净额为正才算赎回」剥离就取不到那笔赎回 → 它会变成凭空亏损。
        # 下界多取一天:区间首段要剥离「区间前一日」的赎回(赎回按成交日就已离场,从期初剥离)。
        totals_start = start_date - timedelta(days=1)
        purchase_totals = await PurchaseRecordDao.get_totals_by_date(
            query_db, all_position_ids, totals_start, end_date
        )
        redemption_totals = await RedemptionRecordDao.get_totals_by_date(
            query_db, all_position_ids, totals_start, end_date
        )

        if snapshots:
            daily_data = cls.build_daily_data_from_snapshots(snapshots, cash_flows, dates)
        else:
            # 逐笔买卖只有实时兜底路径用得上,命中快照时不必按持仓逐个查流水(每持仓两次查询)
            all_transactions = await cls._load_transactions_in_range(query_db, positions, start_date, end_date)
            daily_data = await cls._build_daily_data_realtime(query_db, redis, positions, dates, all_transactions)

        # 记录不完整(赎回份额 > 当日持有份额)的日子:用「组合实际被移走的市值」给现金流调整兜底;
        # 无快照(实时兜底路径)时留空 → 退回按回款金额调整的既有口径
        removed_values, _ = _removed_value_by_date(snapshots) if snapshots else ({}, {})
        gap_by_day = (
            _oversell_days(
                snapshots,
                await RedemptionRecordDao.get_shares_by_date_and_fund(
                    query_db, all_position_ids, totals_start, end_date
                ),
            )
            if snapshots
            else {}
        )
        gap_days = set(gap_by_day)

        benchmark_data = await cls.get_benchmark_series(query_db, redis, benchmark_name, start_date, end_date)
        twr_series = cls.calculate_twr(
            daily_data,
            dates,
            purchase_totals,
            redemption_totals,
            removed_values=removed_values,
            gap_days=gap_days,
        )
        mwr_series = cls._calculate_mwr(
            daily_data,
            dates,
            purchase_totals,
            redemption_totals,
            removed_values=removed_values,
            gap_days=gap_days,
        )
        benchmark_normalized = cls._normalize_benchmark(benchmark_data, dates)
        if gap_days:
            logger.warning(
                f'[分析] 收益率调整:记录不完整 {len(gap_days)} 天(user_id={user_id}),'
                f'涉及基金={sorted({code for codes in gap_by_day.values() for code in codes})}'
            )

        # 年化:Modified Dietz 整体收益率复利年化(现金流按期中均匀发生近似)
        annualized_return = 0
        if len(dates) > 1:
            total_days = (dates[-1] - dates[0]).days
            if total_days > 0:
                v0 = daily_data[0]['total_value']
                v1 = daily_data[-1]['total_value']
                net_cash_flow = daily_data[-1]['total_invested'] - daily_data[0]['total_invested']
                weighted_capital = v0 + abs(net_cash_flow) * 0.5
                if weighted_capital > 0:
                    dietz_return = (v1 - v0 - net_cash_flow) / weighted_capital
                    annualized_return = cls._annualize(dietz_return, total_days)

        return {
            'dates': [d.isoformat() for d in dates],
            'twr': [round(v, 2) for v in twr_series],
            'mwr': [round(v, 2) for v in mwr_series],
            'benchmark': benchmark_normalized,
            'portfolioValue': [round(d['total_value'], 2) for d in daily_data],
            'totalInvested': [round(d['total_invested'], 2) for d in daily_data],
            'annualizedReturn': round(annualized_return * 100, 2),
            'dataQuality': cls.data_quality_payload(gap_by_day),
        }

    @staticmethod
    def data_quality_payload(gap_by_day: dict[date, list[str]]) -> dict:
        """数据质量信息:记录不完整(赎回份额 > 当日持有份额)的日期与涉及基金。

        这些天的份额记录缺了更早的买入,收益率已按「不产生收益」处理(见 `adjusted_pair`),
        前端据此在卡片上给一行轻提示;补齐历史买入后该列表会自然清空。
        """
        days = sorted(gap_by_day)
        return {
            'incompleteDates': [day.isoformat() for day in days],
            'funds': sorted({code for day in days for code in gap_by_day[day]}),
            'note': '这些天的基金历史记录不完整（早于导出区间起点的买入缺失），该段收益率已按不产生收益处理',
        }

    # ---------- 内部构建 ----------

    @classmethod
    def build_daily_data_from_snapshots(cls, snapshots: list, cash_flows: list, dates: list[date]) -> list[dict]:
        """从快照与现金流构建每日数据(快速路径)。

        无快照日期沿用最近有效市值——快照只在交易日生成,非交易日市值不变。
        """
        snapshots_by_date = defaultdict(dict)
        for s in snapshots:
            snapshots_by_date[s.snapshot_date][s.fund_code] = s
        cash_flows_by_date = {cf.flow_date: cf for cf in cash_flows}

        daily_data = []
        last_valid_value = 0.0
        last_valid_invested = 0.0
        for d in dates:
            date_snapshots = snapshots_by_date.get(d, {})
            date_cf = cash_flows_by_date.get(d)
            if date_snapshots:
                total_value = sum(s.market_value for s in date_snapshots.values())
                last_valid_value = total_value
            else:
                total_value = last_valid_value
            if date_cf:
                invested = date_cf.cumulative_invested
                last_valid_invested = invested
            else:
                invested = last_valid_invested
            daily_data.append({'date': d, 'total_value': total_value, 'total_invested': invested})
        return daily_data

    @classmethod
    async def _load_transactions_in_range(
        cls, query_db: AsyncSession, positions: list, start_date: date, end_date: date
    ) -> list[dict]:
        """取区间内逐笔买卖(仅实时兜底路径用于累计投入),命中快照时无需查询。"""
        transactions = []
        for pos in positions:
            # 待确认交易不算(与快照、现金流口径一致):份额未定、到账未知
            purchases = filter_effective_records(await PurchaseRecordDao.get_purchase_records(query_db, pos.position_id))
            redemptions = filter_effective_records(
                await RedemptionRecordDao.get_redemption_records(query_db, pos.position_id, include_deleted=True)
            )
            for p in purchases:
                if start_date <= p.purchase_date <= end_date:
                    transactions.append({
                        'date': p.purchase_date,
                        'type': 'buy',
                        'amount': float(p.shares) * float(p.cost_price),
                    })
            for r in redemptions:
                if start_date <= r.redemption_date <= end_date:
                    transactions.append({
                        'date': r.redemption_date,
                        'type': 'sell',
                        'amount': float(r.shares) * float(r.nav_price),
                    })
        return transactions

    @classmethod
    async def _build_daily_data_realtime(
        cls, query_db: AsyncSession, redis: aioredis.Redis, positions: list,
        dates: list[date], all_transactions: list[dict]
    ) -> list[dict]:
        """实时计算每日数据(慢速路径,无快照时兜底)。

        预取:净值与买卖流水都在日期循环外取齐——此前循环内逐日重复
        `get_fund_by_code`/买卖流水查询,量级是 len(dates)×len(positions)×3,
        慢路径的耗时主要来自这里。
        """
        fund_nav_cache: dict[str, dict[str, dict]] = {}
        # (基金代码, [(买入日, 份额)], [(赎回日, 份额)]):循环内只做纯计算
        position_series: list[tuple[str, list[tuple[date, float]], list[tuple[date, float]]]] = []
        money_curves: dict[str, MoneyAccumCurve] = {}
        for pos in positions:
            fund = await FundDao.get_fund_by_code(query_db, pos.fund_code)
            if not fund:
                continue
            if fund.code not in fund_nav_cache:
                nav_data = await AkshareService.get_fund_nav(query_db, redis, fund.code)
                if nav_data:
                    fund_nav_cache[fund.code] = {r['nav_date']: r for r in nav_data}
            if AkshareService.is_money_fund_type(fund.fund_type) and fund_nav_cache.get(fund.code):
                # 货币基金:按每日收益结转复利算市值,与快照/持仓卡同一口径
                series = await AkshareService.get_money_fund_nav_series(query_db, redis, fund.code)
                if series:
                    money_curves[fund.code] = MoneyAccumCurve(series)
            purchases = await PurchaseRecordDao.get_purchase_records(query_db, pos.position_id)
            redemptions = await RedemptionRecordDao.get_redemption_records(
                query_db, pos.position_id, include_deleted=True
            )
            position_series.append((
                fund.code,
                [(p.purchase_date, float(p.shares)) for p in purchases],
                [(r.redemption_date, float(r.shares)) for r in redemptions],
            ))

        daily_data = []
        for d in dates:
            total_value = 0.0
            for fund_code, purchases, redemptions in position_series:
                # 市值族口径(赎回当日仍持有):与快照路径与 TWR 的现金流调整假设一致——
                # 此前这里用「赎回当日即扣除」,导致有/无快照的市值与 TWR 不一致
                shares = shares_held_on_pairs(purchases, redemptions, d)
                if shares <= 0:
                    continue
                curve = money_curves.get(fund_code)
                if curve is not None:
                    total_value += money_market_value_on(purchases, redemptions, curve, d)
                    continue
                nav_dict = fund_nav_cache.get(fund_code)
                if not nav_dict:
                    # 净值完全缺失(三级缓存与库都没有):跳过该基金,与快照路径「拿不到 nav 即 continue」同口径;
                    # 若按净值 1.0 把份额当市值,同一区间「有/无快照」会算出不同市值与 TWR
                    continue
                nav = nav_value_from_map(nav_dict, d)
                if nav is None:
                    # 该日期早于基金首根净值:用最早可得净值近似
                    nav = nav_dict[min(nav_dict)].get('unit_nav', 0)
                total_value += shares * float(nav)

            invested = sum(t['amount'] for t in all_transactions if t['date'] <= d and t['type'] == 'buy')
            daily_data.append({'date': d, 'total_value': total_value, 'total_invested': invested})
        return daily_data

    @staticmethod
    def _annualize(dietz_return: float, total_days: int) -> float:
        """Modified Dietz 收益率复利年化。

        底数 <= 0(区间内本金亏光)时返回 -1(即年化 -100%):直接做分数次幂会得到复数,
        后续 round 与 JSON 序列化都会抛错,而「亏光」的年化本就有明确下限。
        """
        base = 1 + dietz_return
        if base <= 0:
            return -1.0
        return base ** (365.0 / total_days) - 1

    @staticmethod
    @staticmethod
    def _period_flow_sum(
        totals: dict, t0: date, t1: date, *, include_start: bool, include_end: bool
    ) -> float:
        """采样区间内的现金流合计(键为日期;O(n) 遍历,交易笔数极小不构成开销)。

        申购窗口 (t0, t1]:t0 当天的申购已由上一段(期末=t0)计入期初;
        赎回窗口 [t0, t1):t1 当天的赎回按市值族当日仍持有,由下一段期初剥离。
        """
        total = 0.0
        for day, value in totals.items():
            if day < t0 or day > t1:
                continue
            if day == t0 and not include_start:
                continue
            if day == t1 and not include_end:
                continue
            total += value
        return total

    def adjusted_pair(
        daily_data: list[dict],
        dates: list[date],
        purchase_totals: dict[date, float],
        redemption_totals: dict[date, float],
        i: int,
        *,
        removed_values: dict[date, float] | None = None,
        gap_days: set[date] | None = None,
    ) -> tuple[float, float] | None:
        """取第 i 个采样点的(调整后期初市值, 调整后期末市值);不可计算返回 None。

        现金流时序修正(TWR/MWR 共用,口径唯一):**赎回与申购都是「期初事件」**——
        期初市值先剥掉赎回(份额按成交日净值就已离场)、再加回当日申购。为什么申购也计期初:
        导出件里记的是**确认日(T+1)**,而份额按**成交日(T)**净值成交、次一采样日才出现在
        快照里 —— 那笔钱从 T 日收盘起就已承担涨跌。若只把它当「当日现金流」从期末扣掉,
        等于假设"这笔钱当天收盘才进来",于是每笔买入的次一采样日都会多扣一次当天的涨跌:
        2021-03-24 真实 −1.94% 被算成 −5.85%、镜像地 2021-03-30 的 +1.50% 被算成 +5.56%
        (建仓初期本金小,一笔买入占组合 200%~700%,误差被放大到 ±5%)。

        现金分红是同一字段的**负额**(资金回流),且当天净值已除息 ⇒ 仍计入期末:
        `(除息后市值 + 回款) / 除息前市值` 才是「分红不产生收益」,把它也加到期初会破坏该性质。

        取数必须用「当日申购/赎回总额」而不是现金流表的当日净额:同一天既有买入
        又有赎回时净额会被抵消,`max(净额, 0)` 取不到赎回,那笔赎回就变成凭空亏损。

        **修正窗口是整个采样区间,不是采样日当天**(2026-10-08 升级):申购取
        (T0, T1]、赎回取 [T0, T1)。此前只剥离两个采样日当天的现金流,落在两个
        采样点之间的大额买卖完全不参与修正,被整段当成收益/亏损——实证:350
        买入单周 +34%、700 赎回单周 −30%(货币基金回溯录入)。边界语义与原
        实现一致:申购在 T0 当天由上一段(期末=T0)处理,赎回在 T1 当天市值族
        仍持有、由下一段期初剥离。现金分红若记的是到账日而非除息日,仍会有
        小额残留(金额小,另行观察)。

        `gap_days` / `removed_values`:仅当该日是「赎回份额 > 当日持有份额」的**记录不完整日**时,
        才把回款换成「组合实际被移走的市值」(且仅在回款明显更大时)——那部分差额不是收益。
        其余日子一律沿用回款金额:净值时点造成的 ~1% 差异属正常,不能当成缺口削掉收益。
        """
        bmv = daily_data[i - 1]['total_value']
        emv = daily_data[i]['total_value']
        t0, t1 = dates[i - 1], dates[i]
        purchase = AnalyticsService._period_flow_sum(
            purchase_totals, t0, t1, include_start=False, include_end=True
        )
        redemption = AnalyticsService._period_flow_sum(
            redemption_totals, t0, t1, include_start=True, include_end=False
        )
        if gap_days and removed_values is not None and dates[i - 1] in gap_days:
            removed = removed_values.get(dates[i - 1])
            if removed is not None and redemption - removed > REMOVED_VALUE_TOLERANCE:
                redemption = removed
        # 当日资金进出可能同时含申购(正)与现金分红(负):前者计期初、后者留期末
        adjusted_bmv = bmv + max(purchase, 0.0) - redemption
        if bmv <= 0 or adjusted_bmv <= 0:
            return None
        return adjusted_bmv, emv - min(purchase, 0.0)

    @classmethod
    def calculate_twr(
        cls,
        daily_data: list[dict],
        dates: list[date],
        purchase_totals: dict[date, float],
        redemption_totals: dict[date, float],
        *,
        removed_values: dict[date, float] | None = None,
        gap_days: set[date] | None = None,
    ) -> list[float]:
        """计算时间加权收益率序列(100 基准累积值,逐段复利连乘)。"""
        if len(daily_data) < 2:
            # 采样点不足:按日期序列长度给基准占位(日期序列为空即返回空),
            # 否则单点序列会让 twr 与 dates/基准序列下标错位
            return [100.0] * len(dates)

        twr_series = [100.0]
        cumulative = 1.0
        for i in range(1, len(daily_data)):
            pair = cls.adjusted_pair(
                daily_data,
                dates,
                purchase_totals,
                redemption_totals,
                i,
                removed_values=removed_values,
                gap_days=gap_days,
            )
            if pair is None:
                twr_series.append(twr_series[-1])
                continue
            adjusted_bmv, adjusted_emv = pair
            cumulative *= adjusted_emv / adjusted_bmv
            twr_series.append(round(cumulative * 100, 4))
        return twr_series

    @classmethod
    def _calculate_mwr(
        cls,
        daily_data: list[dict],
        dates: list[date],
        purchase_totals: dict[date, float],
        redemption_totals: dict[date, float],
        *,
        removed_values: dict[date, float] | None = None,
        gap_days: set[date] | None = None,
    ) -> list[float]:
        """计算金额加权收益率序列(分段百分比,调整逻辑与 TWR 共用 adjusted_pair)。"""
        if len(daily_data) < 2:
            # 同 TWR:按日期序列长度给基准占位,保证与 dates 下标一致
            return [0.0] * len(dates)

        mwr_series = [0.0]
        for i in range(1, len(daily_data)):
            pair = cls.adjusted_pair(
                daily_data,
                dates,
                purchase_totals,
                redemption_totals,
                i,
                removed_values=removed_values,
                gap_days=gap_days,
            )
            if pair is None:
                mwr_series.append(0.0)
                continue
            adjusted_bmv, adjusted_emv = pair
            mwr_series.append(round((adjusted_emv / adjusted_bmv - 1) * 100, 2))
        return mwr_series

    @classmethod
    async def get_benchmark_series(
        cls, query_db: AsyncSession, redis: aioredis.Redis,
        benchmark_name: str, start_date: date, end_date: date
    ) -> list[dict]:
        """获取基准指数区间行情(失败返回空,不阻断分析)。"""
        try:
            benchmark_dict = await AkshareService.get_benchmark_nav(query_db, redis, [benchmark_name])
            all_records = benchmark_dict.get(benchmark_name, [])
            result = []
            for record in all_records:
                d = record.get('nav_date', '')
                if isinstance(d, str) and d:
                    try:
                        parsed = date.fromisoformat(d.replace('/', '-'))
                    except ValueError:
                        continue
                    if start_date <= parsed <= end_date:
                        result.append({'date': parsed, 'close': float(record.get('close', 0))})
            return result
        except Exception as e:
            logger.warning(f'[分析] 基准数据获取失败 name={benchmark_name} | {e}')
            return []

    @classmethod
    def _normalize_benchmark(cls, benchmark_data: list[dict], dates: list[date]) -> list[float]:
        """将基准指数归一化到 100 基准(非交易日沿用最近收盘价)。"""
        if not benchmark_data:
            return [100.0] * len(dates)
        benchmark_data.sort(key=lambda x: x['date'])
        first_close = next((b['close'] for b in benchmark_data if b['close'] > 0), None)
        if not first_close:
            return [100.0] * len(dates)

        benchmark_map = {b['date']: b['close'] for b in benchmark_data}
        result = []
        for d in dates:
            close = benchmark_map.get(d)
            if close:
                result.append(round((close / first_close) * 100, 2))
            else:
                for b in reversed(benchmark_data):
                    if b['date'] <= d and b['close'] > 0:
                        result.append(round((b['close'] / first_close) * 100, 2))
                        break
                else:
                    result.append(100.0)
        return result

    # ---------- 持仓占比历史 ----------

    @classmethod
    async def get_allocation_history_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int, start_date: date, end_date: date
    ) -> dict:
        """获取每日持仓占比历史(依赖快照表;读前先过一遍懒补,快照落后于净值时会自动重算)。"""
        # 同上:快照落后于当前净值时先补齐,否则占比曲线末段会停在旧净值上
        await SnapshotService.ensure_fresh_services(query_db, redis, user_id)
        snapshots = await DailySnapshotDao.get_snapshots_in_range(query_db, user_id, start_date, end_date)

        date_map: dict[str, dict[str, float]] = {}
        all_fund_codes = set()
        for snap in snapshots:
            d = snap.snapshot_date.isoformat()
            date_map.setdefault(d, {})
            date_map[d][snap.fund_code] = snap.market_value
            all_fund_codes.add(snap.fund_code)

        fund_names = {}
        for code in all_fund_codes:
            fund = await FundDao.get_fund_by_code(query_db, code)
            fund_names[code] = fund.name if fund else code

        sorted_dates = sorted(date_map.keys())
        totals = [
            {'date': d, 'totalValue': round(sum(date_map[d].values()), 2)}
            for d in sorted_dates
        ]

        allocations = []
        for fund_code in sorted(all_fund_codes):
            fund_allocations = []
            fund_changes = []
            fund_status = []
            prev_allocation = None
            for d in sorted_dates:
                fund_mv = date_map[d].get(fund_code, 0.0)
                total_mv = sum(date_map[d].values()) if date_map[d] else 0.0
                allocation = (fund_mv / total_mv) * 100 if total_mv > 0 else 0.0
                fund_allocations.append(round(allocation, 2))
                if prev_allocation is None:
                    fund_changes.append(None)
                    fund_status.append('新增' if fund_code in date_map[d] else '持平')
                else:
                    change = allocation - prev_allocation
                    fund_changes.append(round(change, 2))
                    if change > 0.1:
                        fund_status.append('上升')
                    elif change < -0.1:
                        fund_status.append('下降')
                    else:
                        fund_status.append('持平')
                prev_allocation = allocation
            allocations.append({
                'fundCode': fund_code,
                'fundName': fund_names.get(fund_code, fund_code),
                'allocations': fund_allocations,
                'changes': fund_changes,
                'status': fund_status,
            })

        return {'dates': sorted_dates, 'allocations': allocations, 'totals': totals}

    # ---------- 逐基金日收益(昨日/今日双档) ----------

    @classmethod
    async def get_daily_fund_profit_services(
        cls, query_db: AsyncSession, redis: aioredis.Redis, user_id: int
    ) -> dict:
        """获取逐基金日收益(最新净值日「今日」档 + 上一净值日「昨日」档)。

        一次请求两档并列返回:净值 T+1 发布后「今日」档滚动到新净值日,
        「昨日」档固定留在上一净值日,两档不再互相覆盖(与日历日过滤的
        旧方案的本质差异)。每只基金按它自己的净值序列独立计算档位日期,
        顶层日期取各行最大值(信息性,个别基金净值发布不同步时以行为准)。
        """
        positions = await PositionDao.get_positions(query_db, user_id)
        if not positions:
            return {'latestNavDate': '', 'prevNavDate': '', 'latest': [], 'prev': []}

        latest_rows: list[dict] = []
        prev_rows: list[dict] = []
        for pos in positions:
            fund = await FundDao.get_fund_by_code(query_db, pos.fund_code)
            if not fund:
                continue
            nav_records = await AkshareService.get_fund_nav(query_db, redis, fund.code)
            if not nav_records:
                continue
            purchases = [
                (str(p.purchase_date), float(p.shares))
                for p in await PurchaseRecordDao.get_purchase_records(query_db, pos.position_id)
            ]
            redemptions = [
                (str(r.redemption_date), float(r.shares))
                for r in await RedemptionRecordDao.get_redemption_records(
                    query_db, pos.position_id, include_deleted=True
                )
            ]

            money_curve = None
            if AkshareService.is_money_fund_type(fund.fund_type):
                money_series = await AkshareService.get_money_fund_nav_series(query_db, redis, fund.code)
                if money_series:
                    money_curve = MoneyAccumCurve(money_series)

            for offset, bucket in ((0, latest_rows), (1, prev_rows)):
                if money_curve is not None:
                    row = _money_daily_fund_profit_row(money_curve, purchases, redemptions, offset)
                else:
                    row = _calc_daily_fund_profit(nav_records, purchases, redemptions, offset)
                if row:
                    row['fundCode'] = fund.code
                    row['fundName'] = fund.name
                    bucket.append(row)

        return {
            'latestNavDate': max((r['navDate'] for r in latest_rows), default=''),
            'prevNavDate': max((r['navDate'] for r in prev_rows), default=''),
            'latest': latest_rows,
            'prev': prev_rows,
        }
